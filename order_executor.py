import os
import contextlib
import logging
import sqlite3
import json
import hashlib
import datetime
import time
import ccxt
from typing import Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


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
            'options': {
                'defaultType': 'future',
                'adjustForTimeDifference': True,
                'recvWindow': 20000,
            },
        })
        with contextlib.suppress(Exception):
            self.exchange.load_time_difference()
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

            # Non-entry orders (exits, partials) must be reduceOnly so that a race
            # against a native SL cannot open an unintended counter-position.
            order_params: dict = {}
            if order_reason != 'entry':
                order_params['reduceOnly'] = True

            order = self.exchange.create_order(
                symbol=symbol,
                type=order_type,
                side=side,
                amount=amount,
                price=price,
                params=order_params,
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

            if order_reason == 'entry':
                confirmed_fill = self._confirm_entry_fill(symbol, side, finalized)
                if not confirmed_fill:
                    message = (
                        f"Entry order fill not confirmed from exchange for {symbol}; "
                        f"order_id={order_id}. Position open skipped to avoid inaccurate SL/TP."
                    )
                    self._mark_intent_failed(effective_key, message)
                    logger.error(message)
                    return OrderResult(
                        success=False,
                        order_id=order_id,
                        message=message,
                        order_data=finalized,
                        idempotency_key=effective_key,
                    )
                finalized.update(confirmed_fill)

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

    def set_native_initial_protection(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        quantity: Optional[float] = None,
    ) -> Dict[str, Any]:
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
        # Native TP is a full-position fallback only; strategy partials are handled
        # by explicit reduce-only market exits in the bot loop.
        tp_amount = None

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
            amount=tp_amount,
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

    def cancel_all_native_stops(self, symbol: str) -> Dict[str, Any]:
        """Clear stopLoss/takeProfit/trailingStop in one idempotent request."""
        zero_payload = {
            'stopLoss': '0',
            'takeProfit': '0',
            'trailingStop': '0',
            'positionIdx': 0,
        }

        result = self._set_trading_stop_safe(symbol, operation='cancel_all_native_stops', payload=zero_payload)
        if result.get('ok', False):
            logger.info('Native stop cancel confirmed for %s', symbol)
        else:
            logger.warning(
                'Native stop cancel warning for %s: warnings=%s',
                symbol,
                result.get('warnings', []),
            )

        return {
            'ok': bool(result.get('ok', False)),
            'operation': 'cancel_all_native_stops',
            'warnings': result.get('warnings', []),
            'native_sl_active': False,
            'native_tp_active': False,
            'native_trail_active': False,
            'native_sl_price': None,
        }

    def clear_native_protection(self, symbol: str) -> Dict[str, Any]:
        """Backward-compatible alias for clearing all native stops."""
        return self.cancel_all_native_stops(symbol)

    def cancel_order_by_id(self, symbol: str, order_id: str) -> Dict[str, Any]:
        """Cancel a single resting order by id. Treats already-gone orders as success."""
        if not order_id:
            return {'ok': False, 'operation': 'cancel_order_by_id', 'warnings': [{'error': 'missing_order_id'}]}

        if self.dry_run:
            logger.info(f"DRY_RUN: cancel order {order_id} for {symbol}")
            return {'ok': True, 'operation': 'cancel_order_by_id', 'warnings': []}

        try:
            self.exchange.cancel_order(order_id, symbol)
            return {'ok': True, 'operation': 'cancel_order_by_id', 'warnings': []}
        except ccxt.OrderNotFound:
            return {'ok': True, 'operation': 'cancel_order_by_id', 'warnings': [{'note': 'order_not_found'}]}
        except Exception as exc:
            logger.warning(f"cancel_order_by_id failed for {symbol} order={order_id}: {type(exc).__name__}: {exc}")
            return {
                'ok': False,
                'operation': 'cancel_order_by_id',
                'warnings': [{'error_type': type(exc).__name__, 'error': str(exc)}],
            }

    def fetch_live_position_size(self, symbol: str) -> Optional[float]:
        """Return the absolute live position contracts for symbol from the exchange.

        Returns 0.0 when the position is confirmed flat, None when the fetch
        fails (caller should treat None as unknown and not assume flat).
        """
        try:
            position = self.exchange.fetch_position(symbol)
            contracts = position.get('contracts') if isinstance(position, dict) else None
            if contracts is None:
                return None
            return abs(float(contracts))
        except Exception as exc:
            logger.warning('Could not fetch live position size for %s: %s', symbol, str(exc))
            return None

    def ensure_native_protection_for_position(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        trailing_active: bool,
        quantity: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Re-arm native protection for a live position during startup reconciliation."""
        if trailing_active:
            return self.set_native_trailing(symbol)
        return self.set_native_initial_protection(symbol, side, entry_price, quantity)

    def _resolve_partial_tp_amount(self, symbol: str, quantity: Optional[float]) -> Optional[float]:
        """Legacy helper retained for compatibility; native TP is full-position only."""
        return None

    def _build_ccxt_trading_stop_params(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Map internal payload fields to CCXT create_order trading-stop params."""
        params: Dict[str, Any] = {
            'tradingStopEndpoint': True,
            # Belt-and-suspenders safety: native stops should never open new exposure.
            'reduceOnly': True,
        }

        if 'positionIdx' in payload and payload['positionIdx'] is not None:
            params['positionIdx'] = int(payload['positionIdx'])

        if 'slTriggerBy' in payload and payload['slTriggerBy'] is not None:
            params['slTriggerBy'] = str(payload['slTriggerBy'])

        if 'stopLoss' in payload:
            value = payload['stopLoss']
            if value is not None:
                value_str = str(value).strip().lower()
                if value_str in {'0', '0.0'}:
                    params['stopLoss'] = '0'
                else:
                    params['stopLossPrice'] = str(value)

        if 'takeProfit' in payload:
            value = payload['takeProfit']
            if value is not None:
                value_str = str(value).strip().lower()
                if value_str in {'0', '0.0'}:
                    params['takeProfit'] = '0'
                else:
                    params['takeProfitPrice'] = str(value)

        if 'trailingStop' in payload:
            value = payload['trailingStop']
            if value is not None:
                value_str = str(value).strip().lower()
                if value_str in {'0', '0.0'}:
                    params['trailingStop'] = '0'
                else:
                    params['trailingAmount'] = str(value)

        return params


    def _set_trading_stop_safe(
        self,
        symbol: str,
        *,
        operation: str,
        payload: Dict[str, Any],
        amount: Optional[float] = None,
        side: Optional[str] = None,
        entry_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Set trading stops using CCXT unified create_order trading-stop endpoint only."""
        if self.dry_run:
            logger.info('DRY_RUN native stop %s for %s payload=%s', operation, symbol, payload)
            return {'ok': True, 'warnings': []}

        try:
            params = self._build_ccxt_trading_stop_params(payload)
            order_amount = abs(float(amount)) if amount is not None else 0.0
            self.exchange.create_order(
                symbol=symbol,
                type='market',
                side='buy',
                amount=order_amount,
                price=None,
                params=params,
            )
            logger.info('Native stop set successfully via ccxt.create_order tradingStopEndpoint: %s operation=%s params=%s amount=%s', symbol, operation, params, order_amount)
            return {'ok': True, 'warnings': []}
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
                'ccxt_method': 'create_order',
            }
            logger.warning('Native stop warning (ccxt create_order failed): %s', json.dumps(warning_payload, default=str))
            return {
                'ok': False,
                'warnings': [
                    {
                        'operation': operation,
                        'error_type': error_type,
                        'error': str(exc),
                    }
                ],
            }

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

    @staticmethod
    def _extract_confirmed_fill(order_data: Dict[str, Any]) -> Optional[Dict[str, float]]:
        """Extract filled quantity and average fill price from exchange order payload."""
        if not isinstance(order_data, dict):
            return None

        try:
            filled = float(order_data.get('filled') or 0.0)
        except (TypeError, ValueError):
            filled = 0.0

        avg_raw = order_data.get('avg_fill_price', order_data.get('average'))
        try:
            avg_fill_price = float(avg_raw or 0.0)
        except (TypeError, ValueError):
            avg_fill_price = 0.0

        if filled > 0 and avg_fill_price > 0:
            return {
                'filled': filled,
                'avg_fill_price': avg_fill_price,
            }
        return None

    def _fetch_position_entry_snapshot(self, symbol: str, side: str) -> Optional[Dict[str, float]]:
        """Fallback confirmation for entry fills via current exchange position snapshot."""
        if not hasattr(self.exchange, 'fetch_position'):
            return None

        try:
            position = self.exchange.fetch_position(symbol)
        except Exception as exc:
            logger.warning('fetch_position failed while confirming entry fill for %s: %s', symbol, exc)
            return None

        if not isinstance(position, dict):
            return None

        pos_side = str(position.get('side') or '').lower()
        requested = str(side or '').lower()
        if requested == 'buy' and pos_side not in {'long', 'buy'}:
            return None
        if requested == 'sell' and pos_side not in {'short', 'sell'}:
            return None

        try:
            contracts = float(position.get('contracts') or 0.0)
        except (TypeError, ValueError):
            contracts = 0.0

        entry_candidates = [position.get('entryPrice'), position.get('average'), position.get('avgPrice')]
        entry_price = 0.0
        for candidate in entry_candidates:
            try:
                entry_price = float(candidate or 0.0)
            except (TypeError, ValueError):
                entry_price = 0.0
            if entry_price > 0:
                break

        if contracts > 0 and entry_price > 0:
            return {
                'filled': abs(contracts),
                'avg_fill_price': entry_price,
            }
        return None

    def _confirm_entry_fill(self, symbol: str, side: str, order_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Confirm entry fill from exchange data to avoid fallback-price SL/TP calculations."""
        direct_fill = self._extract_confirmed_fill(order_data)
        if direct_fill:
            return {
                'fill_confirmed': True,
                'fill_source': 'order',
                **direct_fill,
            }

        snapshot_fill = self._fetch_position_entry_snapshot(symbol, side)
        if snapshot_fill:
            return {
                'fill_confirmed': True,
                'fill_source': 'position_snapshot',
                **snapshot_fill,
            }

        return None
