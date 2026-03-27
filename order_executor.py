import os
import logging
import sqlite3
import json
import hashlib
import datetime
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


class OrderExecutor:
    """Executes orders on Bybit exchange using CCXT."""

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

            order = self.exchange.create_order(
                symbol=symbol,
                type=order_type,
                side=side,
                amount=amount,
                price=price
            )
            logger.info(f"Order executed: {order['id']}")
            self._mark_intent_success(effective_key, str(order.get('id')), order)
            return OrderResult(
                success=True,
                order_id=order['id'],
                message="Order executed successfully",
                order_data=order,
                idempotency_key=effective_key,
            )

        except ccxt.ExchangeError as e:
            logger.error(f"Exchange error: {str(e)}")
            self._mark_intent_failed(effective_key, str(e))
            return OrderResult(success=False, order_id=None, message=str(e), idempotency_key=effective_key)
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            self._mark_intent_failed(effective_key, str(e))
            return OrderResult(success=False, order_id=None, message=str(e), idempotency_key=effective_key)

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
