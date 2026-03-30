import os
import logging
import sqlite3
import json
import hashlib
import datetime
import time
import ccxt
from typing import Dict, Any, Optional
from dataclasses import dataclass

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class OrderResult:
    """Result of an order execution."""
    success: bool
    order_id: Optional[str]
    message: str
    order_data: Optional[Dict[str, Any]] = None
    idempotency_key: Optional[str] = None


class LeverageSetError(Exception):
    """Raised when leverage cannot be set before an entry order."""


class OrderExecutor:
    """Executes orders on Bybit exchange using CCXT."""

    NATIVE_STOP_LOSS_PCT = 0.025
    NATIVE_TAKE_PROFIT_PCT = 0.05
    NATIVE_TRAILING_CALLBACK = '0.015'

    IDEMPOTENCY_DDL = '''
    CREATE TABLE IF NOT EXISTS order_idempotency (
        idempotency_key TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        order_id TEXT,
        request_json TEXT NOT NULL,
        response_json TEXT,
        error_message TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_order_idempotency_status_updated
    ON order_idempotency(status, updated_at);
    '''

    def __init__(self, api_key: str, api_secret: str):
        """
        Initialize OrderExecutor with Bybit credentials.

        Args:
            api_key: Bybit API key
            api_secret: Bybit API secret
        """
        self.dry_run = os.getenv('DRY_RUN', 'false').lower() == 'true'
        self.exchange = ccxt.bybit({
            'apiKey': api_key,
            'secret': api_secret,
            'enableRateLimit': True,
            'options': {'defaultType': 'future'}
        })
        self.order_status_timeout_seconds = int(os.getenv('ORDER_STATUS_TIMEOUT_SECONDS', '30'))
        self.order_status_poll_interval_seconds = float(os.getenv('ORDER_STATUS_POLL_INTERVAL_SECONDS', '1.5'))
        self.idempotency_db_path = os.getenv('ORDER_EXECUTOR_DB', 'usdt_paper_bot_v2.db')
        self.idempotency_db = sqlite3.connect(self.idempotency_db_path)
        self.idempotency_db.row_factory = sqlite3.Row
        self._ensure_idempotency_schema()
        logger.info(f"OrderExecutor initialized. DRY_RUN={self.dry_run}")

    def execute_order(
        self,
        symbol: str,
        order_type: str,
        side: str,
        amount: float,
        price: Optional[float] = None,
        idempotency_key: Optional[str] = None,
        *,
        order_reason: str = 'unspecified',
        leverage: Optional[float] = None,
    ) -> OrderResult:
        """
        Execute an order on Bybit.

        Args:
            symbol: Trading pair (e.g., 'BTC/USDT')
            order_type: 'market' or 'limit'
            side: 'buy' or 'sell'
            amount: Order quantity
            price: Price for limit orders

        Returns:
            OrderResult with execution details
        """
        request_payload = {
            'symbol': symbol,
            'order_type': order_type,
            'side': side,
            'amount': float(amount),
            'price': None if price is None else float(price),
        }
        effective_key = idempotency_key or self._default_idempotency_key(request_payload)

        existing = self._load_intent(effective_key)
        if existing and existing['status'] == 'success':
            logger.info(f"Duplicate order suppressed for idempotency_key={effective_key}")
            response_data = self._safe_json_load(existing['response_json'])
            return OrderResult(
                success=True,
                order_id=existing['order_id'],
                message='Duplicate prevented by idempotency key',
                order_data=response_data,
                idempotency_key=effective_key,
            )
        if existing and existing['status'] == 'pending':
            return OrderResult(
                success=False,
                order_id=existing['order_id'],
                message='Order with this idempotency key is still pending',
                idempotency_key=effective_key,
            )

        self._upsert_intent(effective_key, 'pending', request_payload)

        try:
            if self.dry_run:
                logger.info(
                    f"DRY_RUN: {side.upper()} {amount} {symbol} "
                    f"@ {price} ({order_type})"
                )
                dry_run_order = {
                    'id': 'DRY_RUN_ID',
                    'symbol': symbol,
                    'type': order_type,
                    'side': side,
                    'amount': amount,
                    'price': price,
                }
                self._mark_intent_success(effective_key, 'DRY_RUN_ID', dry_run_order)
                return OrderResult(
                    success=True,
                    order_id="DRY_RUN_ID",
                    message="Order executed in dry run mode",
                    order_data=dry_run_order,
                    idempotency_key=effective_key,
                )

            # Branch C: leverage must be confirmed before entry order placement.
            if order_reason == 'entry':
                if leverage is None:
                    raise LeverageSetError(f'Entry order missing leverage for {symbol}')
                self._ensure_leverage(symbol, leverage)

            order = self.exchange.create_order(
                symbol=symbol,
                type=order_type,
                side=side,
                amount=amount,
                price=price
            )

            finalized = self._finalize_exchange_order(symbol, order)
            terminal_status = str(finalized.get('terminal_status') or finalized.get('status') or '').lower()
            order_id = str(finalized.get('id') or order.get('id') or '')
            if not order_id:
                raise RuntimeError('Exchange did not return an order id')

            if terminal_status in {'canceled', 'cancelled', 'rejected', 'expired', 'failed'}:
                message = f"Order reached terminal non-fill state: {terminal_status}"
                self._mark_intent_failed(effective_key, message)
                return OrderResult(
                    success=False,
                    order_id=order_id,
                    message=message,
                    order_data=finalized,
                    idempotency_key=effective_key,
                )

            logger.info(f"Order executed: {order_id} status={terminal_status or 'unknown'}")
            self._mark_intent_success(effective_key, order_id, finalized)
            return OrderResult(
                success=True,
                order_id=order_id,
                message="Order executed successfully",
                order_data=finalized,
                idempotency_key=effective_key,
            )

        except LeverageSetError as e:
            self._mark_intent_failed(effective_key, str(e))
            return OrderResult(success=False, order_id=None, message=str(e), idempotency_key=effective_key)
        except ccxt.ExchangeError as e:
            logger.error(f"Exchange error: {str(e)}")
            self._mark_intent_failed(effective_key, str(e))
            return OrderResult(success=False, order_id=None, message=str(e), idempotency_key=effective_key)
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            self._mark_intent_failed(effective_key, str(e))
            return OrderResult(success=False, order_id=None, message=str(e), idempotency_key=effective_key)

    def _ensure_leverage(self, symbol: str, leverage: float) -> None:
        """Set and confirm leverage before submitting an entry order."""
        try:
            leverage_value = float(leverage)
        except (TypeError, ValueError) as exc:
            raise LeverageSetError(f'Leverage setup failed for {symbol} at {leverage}x: invalid leverage') from exc

        if leverage_value <= 0:
            raise LeverageSetError(f'Leverage setup failed for {symbol} at {leverage}x: leverage must be > 0')

        if leverage_value.is_integer():
            leverage_value = int(leverage_value)

        try:
            self.exchange.set_leverage(
                leverage_value,
                symbol,
                params={
                    'buyLeverage': leverage_value,
                    'sellLeverage': leverage_value,
                },
            )
        except Exception as exc:
            # Some Bybit account modes reject explicit buy/sell leverage params.
            try:
                self.exchange.set_leverage(leverage_value, symbol)
                logger.info('Leverage confirmed via fallback call: %s = %sx', symbol, leverage)
                return
            except Exception as fallback_exc:
                fallback_text = str(fallback_exc).lower()
                if '110043' in fallback_text or 'leverage not modified' in fallback_text:
                    logger.info('Leverage already set (idempotent): %s = %sx', symbol, leverage)
                    return
                message = (
                    f'Leverage setup failed for {symbol} at {leverage}x: '
                    f'primary_error={exc}; fallback_error={fallback_exc}'
                )
                logger.error(message)
                raise LeverageSetError(message) from fallback_exc

        logger.info(f'Leverage confirmed: {symbol} = {leverage}x')

    def set_native_initial_protection(self, symbol: str, side: str, entry_price: float) -> Dict[str, Any]:
        """Set native fixed SL (MarkPrice) and final TP safety net for an open position."""
        normalized_side = str(side or '').strip().lower()
        try:
            entry = float(entry_price)
        except (TypeError, ValueError):
            return {
                'ok': False,
                'operation': 'set_initial',
                'error_type': 'invalid_entry_price',
                'error': f'Invalid entry_price={entry_price}',
                'warnings': [],
                'native_sl_active': False,
                'native_tp_active': False,
                'native_trail_active': False,
                'native_sl_price': None,
            }

        if entry <= 0:
            return {
                'ok': False,
                'operation': 'set_initial',
                'error_type': 'invalid_entry_price',
                'error': f'entry_price must be > 0, got {entry}',
                'warnings': [],
                'native_sl_active': False,
                'native_tp_active': False,
                'native_trail_active': False,
                'native_sl_price': None,
            }

        is_long = normalized_side in {'long', 'buy'}
        sl_price = entry * (1.0 - self.NATIVE_STOP_LOSS_PCT) if is_long else entry * (1.0 + self.NATIVE_STOP_LOSS_PCT)
        tp_price = entry * (1.0 + self.NATIVE_TAKE_PROFIT_PCT) if is_long else entry * (1.0 - self.NATIVE_TAKE_PROFIT_PCT)

        sl_payload = {
            'stopLoss': str(sl_price),
            'slTriggerBy': 'MarkPrice',
            'positionIdx': 0,
        }
        tp_payload = {
            'takeProfit': str(tp_price),
            'positionIdx': 0,
        }

        sl_result = self._set_trading_stop_safe(
            symbol,
            operation='set_initial_sl',
            payload=sl_payload,
            side=normalized_side,
            entry_price=entry,
        )
        tp_result = self._set_trading_stop_safe(
            symbol,
            operation='set_initial_tp',
            payload=tp_payload,
            side=normalized_side,
            entry_price=entry,
        )

        warnings = sl_result['warnings'] + tp_result['warnings']
        return {
            'ok': bool(sl_result['ok'] and tp_result['ok']),
            'operation': 'set_initial',
            'warnings': warnings,
            'native_sl_active': bool(sl_result['ok']),
            'native_tp_active': bool(tp_result['ok']),
            'native_trail_active': False,
            'native_sl_price': sl_price if sl_result['ok'] else None,
        }

    def set_native_trailing(self, symbol: str) -> Dict[str, Any]:
        """Activate native trailing callback and clear fixed SL/TP protection."""
        trail_payload = {
            'trailingStop': self.NATIVE_TRAILING_CALLBACK,
            'positionIdx': 0,
        }
        clear_fixed_payload = {
            'stopLoss': '0',
            'takeProfit': '0',
            'positionIdx': 0,
        }

        trail_result = self._set_trading_stop_safe(
            symbol,
            operation='set_trailing',
            payload=trail_payload,
        )
        clear_result = self._set_trading_stop_safe(
            symbol,
            operation='clear_fixed_for_trailing',
            payload=clear_fixed_payload,
        )

        warnings = trail_result['warnings'] + clear_result['warnings']
        return {
            'ok': bool(trail_result['ok'] and clear_result['ok']),
            'operation': 'set_trailing',
            'warnings': warnings,
            'native_sl_active': False,
            'native_tp_active': False,
            'native_trail_active': bool(trail_result['ok']),
            'native_sl_price': None,
        }

    def clear_native_protection(self, symbol: str) -> Dict[str, Any]:
        """Clear all native stop settings; never raises on failure."""
        zero_payload = {
            'stopLoss': '0',
            'takeProfit': '0',
            'trailingStop': '0',
            'positionIdx': 0,
        }
        none_payload = {
            'stopLoss': None,
            'takeProfit': None,
            'trailingStop': None,
            'positionIdx': 0,
        }

        primary = self._set_trading_stop_safe(symbol, operation='clear_all', payload=zero_payload)
        fallback = {'ok': False, 'warnings': []}
        if not primary['ok']:
            fallback = self._set_trading_stop_safe(symbol, operation='clear_all_fallback_none', payload=none_payload)

        warnings = primary['warnings'] + fallback['warnings']
        return {
            'ok': bool(primary['ok'] or fallback['ok']),
            'operation': 'clear_all',
            'warnings': warnings,
            'native_sl_active': False,
            'native_tp_active': False,
            'native_trail_active': False,
            'native_sl_price': None,
        }

    def ensure_native_protection_for_position(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        trailing_active: bool,
    ) -> Dict[str, Any]:
        """Re-arm native protection for a live position during startup reconciliation."""
        if trailing_active:
            return self.set_native_trailing(symbol)
        return self.set_native_initial_protection(symbol, side, entry_price)

    def _set_trading_stop_safe(
        self,
        symbol: str,
        *,
        operation: str,
        payload: Dict[str, Any],
        side: Optional[str] = None,
        entry_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Call exchange.set_trading_stop with warning-only failure semantics."""
        if self.dry_run:
            logger.info('DRY_RUN native stop %s for %s payload=%s', operation, symbol, payload)
            return {'ok': True, 'warnings': []}

        warnings = []
        try:
            self.exchange.set_trading_stop(symbol, params=payload)
            return {'ok': True, 'warnings': warnings}
        except Exception as exc:
            error_type = type(exc).__name__
            warning_payload = {
                'symbol': symbol,
                'operation': operation,
                'position_side': side,
                'entry_price': entry_price,
                'native_payload': payload,
                'error_type': error_type,
                'error': str(exc),
            }
            logger.warning('Native stop warning: %s', json.dumps(warning_payload, default=str))
            warnings.append(
                {
                    'operation': operation,
                    'error_type': error_type,
                    'error': str(exc),
                }
            )
            return {'ok': False, 'warnings': warnings}

    def _ensure_idempotency_schema(self) -> None:
        cursor = self.idempotency_db.cursor()
        cursor.executescript(self.IDEMPOTENCY_DDL)
        self.idempotency_db.commit()

    def _load_intent(self, idempotency_key: str) -> Optional[sqlite3.Row]:
        cursor = self.idempotency_db.cursor()
        return cursor.execute(
            'SELECT idempotency_key, status, order_id, response_json FROM order_idempotency WHERE idempotency_key = ?',
            (idempotency_key,),
        ).fetchone()

    def _upsert_intent(self, idempotency_key: str, status: str, request_payload: Dict[str, Any]) -> None:
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        payload_json = json.dumps(request_payload, separators=(',', ':'))
        cursor = self.idempotency_db.cursor()
        cursor.execute(
            '''
            INSERT INTO order_idempotency (
                idempotency_key, status, order_id, request_json,
                response_json, error_message, created_at, updated_at
            ) VALUES (?, ?, NULL, ?, NULL, NULL, ?, ?)
            ON CONFLICT(idempotency_key) DO UPDATE SET
                status=excluded.status,
                request_json=excluded.request_json,
                updated_at=excluded.updated_at,
                error_message=NULL
            ''',
            (idempotency_key, status, payload_json, now_iso, now_iso),
        )
        self.idempotency_db.commit()

    def _mark_intent_success(self, idempotency_key: str, order_id: str, response_data: Dict[str, Any]) -> None:
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cursor = self.idempotency_db.cursor()
        cursor.execute(
            '''
            UPDATE order_idempotency
            SET status = 'success',
                order_id = ?,
                response_json = ?,
                error_message = NULL,
                updated_at = ?
            WHERE idempotency_key = ?
            ''',
            (order_id, json.dumps(response_data, separators=(',', ':')), now_iso, idempotency_key),
        )
        self.idempotency_db.commit()

    def _mark_intent_failed(self, idempotency_key: str, error_message: str) -> None:
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cursor = self.idempotency_db.cursor()
        cursor.execute(
            '''
            UPDATE order_idempotency
            SET status = 'failed',
                error_message = ?,
                updated_at = ?
            WHERE idempotency_key = ?
            ''',
            (error_message[:1000], now_iso, idempotency_key),
        )
        self.idempotency_db.commit()

    @staticmethod
    def _safe_json_load(raw: Optional[str]) -> Optional[Dict[str, Any]]:
        if not raw:
            return None
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
            return {'raw': data}
        except Exception:
            return None

    @staticmethod
    def _default_idempotency_key(request_payload: Dict[str, Any]) -> str:
        canonical = json.dumps(request_payload, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(canonical.encode('utf-8')).hexdigest()

    def _finalize_exchange_order(self, symbol: str, order: Dict[str, Any]) -> Dict[str, Any]:
        """Poll terminal states when available and enrich payload with fill summary."""
        order_id = str(order.get('id') or '')
        if not order_id:
            return dict(order)

        finalized = dict(order)
        if hasattr(self.exchange, 'fetch_order'):
            terminal = self._await_terminal_order(symbol, order_id)
            if terminal is not None:
                finalized.update(terminal)

        fill_summary = self._build_fill_summary(symbol, order_id)
        if fill_summary:
            finalized.update(fill_summary)

        status = str(finalized.get('status') or '').lower()
        if status:
            finalized['terminal_status'] = status

        return finalized

    def _await_terminal_order(self, symbol: str, order_id: str) -> Optional[Dict[str, Any]]:
        terminal_statuses = {'closed', 'canceled', 'cancelled', 'rejected', 'expired', 'failed'}
        deadline = time.time() + max(1, self.order_status_timeout_seconds)
        last_snapshot: Optional[Dict[str, Any]] = None

        while time.time() < deadline:
            try:
                snapshot = self.exchange.fetch_order(order_id, symbol)
                if isinstance(snapshot, dict):
                    last_snapshot = snapshot
                    status = str(snapshot.get('status') or '').lower()
                    if status in terminal_statuses:
                        return snapshot
            except Exception as exc:
                logger.warning('fetch_order polling failed for %s/%s: %s', symbol, order_id, exc)
                break
            time.sleep(max(0.1, self.order_status_poll_interval_seconds))

        return last_snapshot

    def _build_fill_summary(self, symbol: str, order_id: str) -> Dict[str, Any]:
        if not hasattr(self.exchange, 'fetch_my_trades'):
            return {}

        try:
            trades = self.exchange.fetch_my_trades(symbol=symbol, limit=200)
        except Exception as exc:
            logger.warning('fetch_my_trades failed for %s/%s: %s', symbol, order_id, exc)
            return {}

        order_trades = [
            t for t in (trades or [])
            if str(t.get('order') or t.get('orderId') or '') == str(order_id)
        ]
        if not order_trades:
            return {}

        total_qty = 0.0
        total_notional = 0.0
        total_fee = 0.0
        for trade in order_trades:
            try:
                qty = abs(float(trade.get('amount') or 0.0))
                px = float(trade.get('price') or 0.0)
            except (TypeError, ValueError):
                continue

            if qty <= 0 or px <= 0:
                continue

            total_qty += qty
            total_notional += qty * px
            fee_obj = trade.get('fee') or {}
            fee_cost = fee_obj.get('cost') if isinstance(fee_obj, dict) else None
            try:
                total_fee += abs(float(fee_cost or 0.0))
            except (TypeError, ValueError):
                pass

        if total_qty <= 0:
            return {}

        return {
            'filled': total_qty,
            'avg_fill_price': total_notional / total_qty,
            'fill_fee_cost': total_fee,
            'trade_count': len(order_trades),
        }
