#!/usr/bin/env python3
"""Validation suite for the live bot testnet workflow."""

from __future__ import annotations

import contextlib
import dataclasses
import datetime
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

import ccxt
import alert_dispatcher as alert_dispatcher_module

from alert_dispatcher import AlertDispatcher
from observability import FundingTracker
from order_executor import OrderExecutor
from startup_reconciler import StartupReconciler
from usdt_paper_bot_v2 import PaperPosition, Aribot, derive_pnl_pct


logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
LOGGER = logging.getLogger('test_live_bot')
REPO_ROOT = Path(__file__).resolve().parent


@dataclasses.dataclass
class TestResult:
    number: int
    name: str
    status: str
    criteria: list[str]
    details: str
    duration_seconds: float


def run_timed_test(number: int, name: str, criteria: list[str], func: Callable[[], tuple[str, str]]) -> TestResult:
    started = time.perf_counter()
    try:
        status, details = func()
    except Exception as exc:
        status = 'FAIL'
        details = f'{type(exc).__name__}: {exc}'
    duration = time.perf_counter() - started
    return TestResult(number, name, status, criteria, details, duration)


def get_bybit_env_mode() -> str:
    raw = str(os.getenv('BYBIT_TESTNET', 'true')).strip().lower()
    return 'testnet' if raw in {'1', 'true', 'yes', 'on'} else 'mainnet'


def get_bybit_api_credentials() -> tuple[str, str]:
    """Resolve API credentials by environment mode with sensible fallback."""
    mode = get_bybit_env_mode()
    if mode == 'testnet':
        key_candidates = ['BYBIT_TEST_KEY', 'BYBIT_TRADE_API_KEY']
        secret_candidates = ['BYBIT_TEST_SECRET', 'BYBIT_TRADE_API_SECRET']
    else:
        key_candidates = ['BYBIT_TRADE_API_KEY', 'BYBIT_TEST_KEY']
        secret_candidates = ['BYBIT_TRADE_API_SECRET', 'BYBIT_TEST_SECRET']

    api_key = ''
    api_secret = ''
    for var_name in key_candidates:
        value = os.getenv(var_name, '').strip().strip("'").strip('"')
        if value:
            api_key = value
            break
    for var_name in secret_candidates:
        value = os.getenv(var_name, '').strip().strip("'").strip('"')
        if value:
            api_secret = value
            break

    return api_key, api_secret


def init_testnet_exchange() -> Optional[ccxt.bybit]:
    api_key, api_secret = get_bybit_api_credentials()
    if not api_key or not api_secret:
        return None

    mode = get_bybit_env_mode()
    exchange = ccxt.bybit({
        'apiKey': api_key,
        'secret': api_secret,
        'enableRateLimit': True,
        'options': {
            'defaultType': 'future',
            'adjustForTimeDifference': True,
            'recvWindow': 20000,
        },
    })
    exchange.set_sandbox_mode(mode == 'testnet')
    # Proactively sync server/client clock to avoid retCode 10002 on signed calls.
    with contextlib.suppress(Exception):
        exchange.load_time_difference()
    return exchange


def normalize_symbol(symbol: str) -> str:
    return symbol.replace(':', '').replace('/', '').replace('-', '').upper()


def get_required_testnet_symbol() -> tuple[Optional[str], Optional[str]]:
    candidates = [
        ('BRANCH_A_TESTNET_SYMBOL', os.getenv('BRANCH_A_TESTNET_SYMBOL', '').strip()),
        ('TESTNET_SYMBOL', os.getenv('TESTNET_SYMBOL', '').strip()),
    ]
    for env_name, value in candidates:
        if value:
            return value, None
    return None, 'Missing symbol env. Set BRANCH_A_TESTNET_SYMBOL (preferred) or TESTNET_SYMBOL.'


def extract_position_side(position: dict[str, Any]) -> str:
    side = str(position.get('side') or position.get('positionSide') or '').strip().lower()
    if side in {'long', 'buy'}:
        return 'long'
    if side in {'short', 'sell'}:
        return 'short'
    info = position.get('info') or {}
    info_side = str(info.get('side') or '').strip().lower()
    if info_side in {'buy', 'long'}:
        return 'long'
    if info_side in {'sell', 'short'}:
        return 'short'
    raise RuntimeError(f'Unable to determine position side from payload: {position}')


def extract_position_contracts(position: dict[str, Any]) -> float:
    info = position.get('info') or {}
    contracts = position.get('contracts')
    if contracts is None:
        contracts = info.get('size')
    if contracts is None:
        contracts = info.get('positionValue')
    return abs(float(contracts or 0.0))


def find_open_testnet_position(exchange: ccxt.bybit, symbol: str) -> dict[str, Any]:
    positions = exchange.fetch_positions([symbol])
    target = normalize_symbol(symbol)
    for position in positions:
        contracts = extract_position_contracts(position)
        if contracts <= 0:
            continue
        raw_symbol = str(position.get('symbol') or '')
        info = position.get('info') or {}
        info_symbol = str(info.get('symbol') or '')
        if normalize_symbol(raw_symbol) == target or normalize_symbol(info_symbol) == target:
            return position
    raise RuntimeError(
        f'No open testnet position for {symbol}. Open a small position first, then rerun validation.'
    )


def find_any_position_for_symbol(exchange: ccxt.bybit, symbol: str) -> dict[str, Any]:
    positions = exchange.fetch_positions([symbol])
    target = normalize_symbol(symbol)
    for position in positions:
        raw_symbol = str(position.get('symbol') or '')
        info = position.get('info') or {}
        info_symbol = str(info.get('symbol') or '')
        if normalize_symbol(raw_symbol) == target or normalize_symbol(info_symbol) == target:
            return position
    raise RuntimeError(f'No position payload returned for {symbol}')


def set_trading_stop_exchange(exchange: ccxt.bybit, symbol: str, params: dict[str, Any]) -> Any:
    if hasattr(exchange, 'set_trading_stop'):
        return exchange.set_trading_stop(symbol, params=params)
    if hasattr(exchange, 'setTradingStop'):
        return exchange.setTradingStop(symbol, params)

    market = exchange.market(symbol)
    payload = {
        'category': 'linear',
        'symbol': market.get('id') or symbol.replace('/', '').replace(':', ''),
    }
    payload.update(params)
    return exchange.privatePostV5PositionTradingStop(payload)


def extract_margin_relative_pct(position: dict[str, Any]) -> Optional[float]:
    pct = position.get('percentage')
    if pct is not None:
        return float(pct)
    info = position.get('info') or {}
    for key in ('unrealisedPnlPcnt', 'unrealizedPnlPcnt'):
        if key in info and info.get(key) is not None:
            raw = float(info[key])
            if abs(raw) <= 1.0:
                return raw * 100.0
            return raw
    return None


def get_live_reference_price(exchange: ccxt.bybit, symbol: str) -> float:
    ticker = exchange.fetch_ticker(symbol)
    candidates = [
        ticker.get('last'),
        ticker.get('mark'),
        ticker.get('close'),
        (ticker.get('info') or {}).get('markPrice'),
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        value = float(candidate)
        if value > 0:
            return value
    raise RuntimeError(f'Unable to extract live ticker price for {symbol}. ticker={ticker}')


def compute_avg_fill_price(trades: Iterable[dict[str, Any]]) -> float:
    total_qty = 0.0
    total_notional = 0.0
    for trade in trades:
        qty = abs(float(trade.get('amount') or 0.0))
        px = float(trade.get('price') or 0.0)
        if qty <= 0 or px <= 0:
            continue
        total_qty += qty
        total_notional += qty * px
    if total_qty <= 0:
        raise RuntimeError('No valid fills found while computing average fill price')
    return total_notional / total_qty


def poll_closed_order(exchange: ccxt.bybit, symbol: str, order_id: str, timeout_seconds: int = 30) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_order = None
    while time.time() < deadline:
        last_error = None
        with contextlib.suppress(Exception):
            last_order = exchange.fetch_order(order_id, symbol, {'acknowledged': True})
        if last_order is None:
            with contextlib.suppress(TypeError, Exception):
                last_order = exchange.fetch_order(order_id, symbol)
        if last_order is None and hasattr(exchange, 'fetch_closed_order'):
            with contextlib.suppress(Exception):
                last_order = exchange.fetch_closed_order(order_id, symbol)
        if last_order is None and hasattr(exchange, 'fetch_open_order'):
            with contextlib.suppress(Exception):
                last_order = exchange.fetch_open_order(order_id, symbol)
        if last_order is None:
            time.sleep(2)
            continue
        status = str(last_order.get('status', '')).lower()
        if status == 'closed':
            return last_order
        if status in {'canceled', 'cancelled', 'rejected', 'expired'}:
            raise RuntimeError(f'Order {order_id} reached terminal non-fill state: {status}; order={last_order}')
        time.sleep(2)
    raise TimeoutError(f'Order {order_id} did not close within {timeout_seconds}s; last_order={last_order}')


def ensure_open_reference_position(exchange: ccxt.bybit, symbol: str) -> tuple[dict[str, Any], bool, str, float]:
    """Return an open position for symbol, creating a tiny probe position when needed."""
    try:
        existing = find_open_testnet_position(exchange, symbol)
        return existing, False, 'buy', 0.0
    except Exception:
        pass

    side = (os.getenv('BRANCH_A_TEST_SIDE') or os.getenv('TESTNET_ORDER_SIDE') or 'buy').strip().lower()
    if side not in {'buy', 'sell'}:
        side = 'buy'

    qty_raw = (os.getenv('BRANCH_A_TEST_QTY') or os.getenv('TESTNET_ORDER_QTY') or '0.001').strip()
    try:
        qty = float(qty_raw)
    except ValueError as exc:
        raise RuntimeError(f'Invalid BRANCH_A_TEST_QTY/TESTNET_ORDER_QTY value: {qty_raw}') from exc
    if qty <= 0:
        raise RuntimeError(f'BRANCH_A_TEST_QTY/TESTNET_ORDER_QTY must be > 0, got {qty}')

    order = exchange.create_order(symbol=symbol, type='market', side=side, amount=qty)
    order_id = str(order.get('id') or '')
    if not order_id:
        raise RuntimeError(f'Probe open order returned no id for {symbol}: {order}')

    poll_closed_order(exchange, symbol, order_id, timeout_seconds=40)
    opened = find_open_testnet_position(exchange, symbol)
    return opened, True, side, qty


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        text = str(value).strip()
        if text == '':
            return None
        lowered = text.lower()
        if lowered in {'none', 'null'}:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _normalize_key(raw_key: str) -> str:
    return ''.join(ch for ch in raw_key.lower() if ch.isalnum())


def _extract_numeric_candidates(payload: Any, key_aliases: set[str]) -> list[tuple[str, Optional[float]]]:
    results: list[tuple[str, Optional[float]]] = []

    def walk(value: Any, prefix: str = '') -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                key_text = str(key)
                path = f'{prefix}.{key_text}' if prefix else key_text
                if _normalize_key(key_text) in key_aliases:
                    results.append((path, _safe_float(child)))
                walk(child, path)
        elif isinstance(value, list):
            for idx, child in enumerate(value):
                walk(child, f'{prefix}[{idx}]' if prefix else f'[{idx}]')

    walk(payload)
    return results


def _read_native_stop_snapshot(position_payload: dict[str, Any]) -> dict[str, Any]:
    stop_aliases = {'stoploss', 'stoplossprice', 'stoplossvalue', 'sl', 'slprice'}
    tp_aliases = {'takeprofit', 'takeprofitprice', 'tp', 'tpprice'}
    trailing_aliases = {'trailingstop', 'trailingstopdistance', 'trailstop'}

    stop_candidates = _extract_numeric_candidates(position_payload, stop_aliases)
    tp_candidates = _extract_numeric_candidates(position_payload, tp_aliases)
    trailing_candidates = _extract_numeric_candidates(position_payload, trailing_aliases)

    stop_loss = next((value for _, value in stop_candidates if value is not None), None)
    take_profit = next((value for _, value in tp_candidates if value is not None), None)
    trailing_stop = next((value for _, value in trailing_candidates if value is not None), None)

    observed_paths = [path for path, _ in (stop_candidates + tp_candidates + trailing_candidates)]
    return {
        'stop_loss': stop_loss,
        'take_profit': take_profit,
        'trailing_stop': trailing_stop,
        'stop_paths': [path for path, _ in stop_candidates],
        'tp_paths': [path for path, _ in tp_candidates],
        'trailing_paths': [path for path, _ in trailing_candidates],
        'observed_any_native_paths': bool(observed_paths),
    }


def _fetch_positions_for_symbol(exchange: ccxt.bybit, symbol: str) -> list[dict[str, Any]]:
    with contextlib.suppress(Exception):
        positions = exchange.fetch_positions([symbol])
        if isinstance(positions, list):
            return [p for p in positions if isinstance(p, dict)]

    positions = exchange.fetch_positions()
    if not isinstance(positions, list):
        return []
    return [p for p in positions if isinstance(p, dict)]


def _find_open_position(exchange: ccxt.bybit, symbol: str, expected_side: str) -> Optional[dict[str, Any]]:
    expected = 'long' if expected_side in {'buy', 'long'} else 'short'
    candidates = _fetch_positions_for_symbol(exchange, symbol)
    selected: Optional[dict[str, Any]] = None
    for pos in candidates:
        pos_symbol = str(pos.get('symbol') or '')
        if pos_symbol != symbol:
            continue
        contracts = pos.get('contracts')
        if contracts is None and isinstance(pos.get('info'), dict):
            contracts = pos['info'].get('size')
        qty = abs(float(contracts or 0.0))
        if qty <= 0:
            continue
        side = str(pos.get('side') or '').lower()
        if not side:
            side = 'long' if float(contracts or 0.0) > 0 else 'short'
        if side == 'buy':
            side = 'long'
        if side == 'sell':
            side = 'short'
        if side != expected:
            continue
        selected = pos
        break
    return selected


def _poll_position_snapshot(
    exchange: ccxt.bybit,
    symbol: str,
    expected_side: str,
    predicate: Callable[[dict[str, Any]], bool],
    timeout_seconds: int = 35,
) -> tuple[dict[str, Any], dict[str, Any]]:
    deadline = time.time() + timeout_seconds
    last_position = None
    last_snapshot = {
        'stop_loss': None,
        'take_profit': None,
        'trailing_stop': None,
        'stop_paths': [],
        'tp_paths': [],
        'trailing_paths': [],
        'observed_any_native_paths': False,
    }

    while time.time() < deadline:
        position = _find_open_position(exchange, symbol, expected_side)
        if position is None:
            time.sleep(2)
            continue

        snapshot = _read_native_stop_snapshot(position)
        last_position = position
        last_snapshot = snapshot
        if predicate(snapshot):
            return position, snapshot
        time.sleep(2)

    raise TimeoutError(
        f'Position snapshot predicate did not match within {timeout_seconds}s; '
        f'last_snapshot={last_snapshot}, last_position={last_position}'
    )


def parse_numeric_env(name: str, default: float) -> float:
    raw_value = os.getenv(name, '').strip()
    if not raw_value:
        return float(default)
    try:
        return float(raw_value)
    except ValueError as exc:
        raise ValueError(f'{name} must be numeric, got {raw_value!r}') from exc


def extract_position_leverage(position: dict[str, Any]) -> Optional[float]:
    info = position.get('info') or {}
    leverage_candidates = [
        position.get('leverage'),
        info.get('leverage'),
        info.get('buyLeverage'),
        info.get('sellLeverage'),
    ]
    for candidate in leverage_candidates:
        if candidate is None:
            continue
        try:
            return float(candidate)
        except (TypeError, ValueError):
            continue
    return None


def close_position_best_effort(exchange: ccxt.bybit, symbol: str, side: str, quantity: float) -> None:
    flatten_side = 'sell' if side == 'buy' else 'buy'
    with contextlib.suppress(Exception):
        exchange.create_order(
            symbol=symbol,
            type='market',
            side=flatten_side,
            amount=quantity,
            params={'reduceOnly': True},
        )


def run_branch_c_leverage_validation_case(
    symbol: str,
    expected_leverage: float,
    quantity: float,
    side: str,
) -> tuple[bool, str]:
    api_key, api_secret = get_bybit_api_credentials()
    if not api_key or not api_secret:
        return False, 'Missing BYBIT_TEST_KEY/BYBIT_TEST_SECRET or BYBIT_TRADE_API_KEY/BYBIT_TRADE_API_SECRET for Bybit leverage validation.'

    if quantity <= 0:
        return False, f'Invalid quantity for {symbol}: expected > 0, got {quantity}'

    with tempfile.TemporaryDirectory() as temp_dir:
        mode = get_bybit_env_mode()
        previous_db = os.environ.get('ORDER_EXECUTOR_DB')
        os.environ['ORDER_EXECUTOR_DB'] = str(Path(temp_dir) / 'order_executor.db')
        executor = None
        result = None
        try:
            executor = OrderExecutor(api_key, api_secret)
            executor.dry_run = False
            executor.exchange.set_sandbox_mode(mode == 'testnet')

            result = executor.execute_order(
                symbol,
                'market',
                side,
                quantity,
                order_reason='entry',
                leverage=expected_leverage,
            )
            if not result.success:
                return False, f'Entry order failed for {symbol} at {expected_leverage}x: {result.message}'

            try:
                position = find_open_testnet_position(executor.exchange, symbol)
            except Exception as exc:
                try:
                    position = find_any_position_for_symbol(executor.exchange, symbol)
                except Exception:
                    return False, f'Could not fetch open position for {symbol} after entry: {type(exc).__name__}: {exc}'

            observed_leverage = extract_position_leverage(position)
            if observed_leverage is None:
                return False, f'Unable to parse position leverage for {symbol}. position={position}'

            if abs(observed_leverage - float(expected_leverage)) > 1e-9:
                return False, (
                    f'Leverage mismatch for {symbol}: expected {expected_leverage}x, '
                    f'observed {observed_leverage}x'
                )

            filled_qty = float((result.order_data or {}).get('filled') or quantity)
            return True, f'symbol={symbol}, expected={expected_leverage}x, observed={observed_leverage}x, qty={filled_qty}'
        finally:
            if executor is not None:
                cleanup_qty = quantity
                if result is not None and result.order_data:
                    cleanup_qty = float(result.order_data.get('filled') or quantity)
                close_position_best_effort(executor.exchange, symbol, side, cleanup_qty)
                executor.idempotency_db.close()
            if previous_db is None:
                os.environ.pop('ORDER_EXECUTOR_DB', None)
            else:
                os.environ['ORDER_EXECUTOR_DB'] = previous_db


def seed_positions_db(db_path: Path, symbol: str = 'TEST/USDT:USDT') -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS positions (
                symbol TEXT PRIMARY KEY,
                side TEXT,
                entry_price REAL,
                quantity REAL,
                timestamp TEXT,
                stop_loss REAL,
                trailing_stop_level REAL,
                trailing_stop_active INTEGER,
                peak_pnl_percentage REAL,
                current_price REAL,
                pnl REAL,
                pnl_percentage REAL,
                partial_exits_json TEXT DEFAULT '[]',
                native_sl_active INTEGER DEFAULT 0,
                native_tp_active INTEGER DEFAULT 0,
                native_trail_active INTEGER DEFAULT 0,
                native_sl_price REAL
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS closed_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                side TEXT,
                entry_price REAL,
                exit_price REAL,
                quantity REAL,
                pnl REAL,
                pnl_percentage REAL,
                reason TEXT,
                open_time TEXT,
                close_time TEXT
            )
            '''
        )
        conn.execute(
            '''
            INSERT OR REPLACE INTO positions (
                symbol, side, entry_price, quantity, timestamp,
                stop_loss, trailing_stop_level, trailing_stop_active,
                peak_pnl_percentage, current_price, pnl, pnl_percentage,
                partial_exits_json, native_sl_active, native_tp_active,
                native_trail_active, native_sl_price
            ) VALUES (?, ?, ?, ?, ?, NULL, NULL, 0, 0, ?, 0, 0, '[]', 0, 0, 0, NULL)
            ''',
            (
                symbol,
                'long',
                100.0,
                1.0,
                datetime.datetime.now().isoformat(),
                100.0,
            ),
        )
        conn.commit()
    finally:
        conn.close()


@contextlib.contextmanager
def patched_bot_workspace() -> Iterable[Path]:
    with tempfile.TemporaryDirectory() as temp_dir:
        workdir = Path(temp_dir)
        for file_name in [
            'usdt_paper_bot_v2.py',
            'observability.py',
            'secret_loader.py',
            'alert_dispatcher.py',
            'order_executor.py',
            'startup_reconciler.py',
            'leverage_buckets.json',
        ]:
            shutil.copy2(REPO_ROOT / file_name, workdir / file_name)

        bot_file = workdir / 'usdt_paper_bot_v2.py'
        bot_code = bot_file.read_text(encoding='utf-8')
        bot_code = bot_code.replace('self.loop_interval_seconds = 60', 'self.loop_interval_seconds = 2')
        bot_code = bot_code.replace(
            "should_scan_entries = (cycle == 1) or self.is_signal_window()",
            'should_scan_entries = False',
        )
        bot_code = bot_code.replace('self.startup_reconciler.startup_gate()', 'pass')
        bot_file.write_text(bot_code, encoding='utf-8')
        yield workdir


class FakeNoPositionExchange:
    def fetch_positions(self):
        return []

    def fetch_my_trades(self, symbol=None, limit=200):
        return []


class FakeFundingExchange:
    def fetch_funding_rate(self, symbol):
        return {'fundingRate': 0.0001, 'markPrice': 100.0}


class FakeExchangeCreateOrder:
    def __init__(self):
        self.create_order_calls = 0

    def create_order(self, *args, **kwargs):
        self.create_order_calls += 1
        return {'id': 'should-not-be-called'}


class FakeExchangeLeverageOrder:
    def __init__(self, fail_set_leverage: bool = False):
        self.fail_set_leverage = fail_set_leverage
        self.calls = []

    def set_leverage(self, leverage, symbol, params=None):
        self.calls.append(('set_leverage', leverage, symbol, params))
        if self.fail_set_leverage:
            raise ccxt.ExchangeError('set_leverage rejected')
        return {'retCode': 0}

    def create_order(self, **kwargs):
        self.calls.append(('create_order', kwargs))
        return {
            'id': 'order-123',
            'status': 'closed',
            'filled': kwargs.get('amount', 0),
            'average': 100.0,
        }

    def fetch_order(self, order_id, symbol):
        return {'id': order_id, 'status': 'closed'}

    def fetch_my_trades(self, symbol=None, limit=200):
        return []


class FakeGhostPositionExchange:
    def fetch_positions(self):
        return [
            {
                'symbol': 'GHOST/USDT:USDT',
                'contracts': 1.5,
                'entryPrice': 105.0,
                'side': 'long',
                'info': {},
            }
        ]

    def fetch_my_trades(self, symbol=None, limit=200):
        return []


class FakeExchangeWithPctFields:
    def fetch_positions(self):
        return [
            {
                'symbol': 'BTC/USDT:USDT',
                'contracts': 1.0,
                'entryPrice': 100.0,
                'side': 'long',
                'percentage': -99.0,
                'unrealizedPnl': -10.0,
                'info': {
                    'unrealizedPnlPcnt': '-0.99',
                    'size': '1',
                },
            }
        ]

    def fetch_my_trades(self, symbol=None, limit=200):
        return []


class FakeExchangeTradingStop:
    def __init__(self, fail_operations: Optional[set[str]] = None):
        self.fail_operations = fail_operations or set()
        self.calls = []

    @staticmethod
    def _operation_from_params(params: dict[str, Any]) -> str:
        if 'trailingStop' in params and params.get('trailingStop') == '0.015':
            return 'set_trailing'
        if params.get('stopLoss') == '0' and params.get('takeProfit') == '0' and 'trailingStop' not in params:
            return 'clear_fixed_for_trailing'
        if params.get('stopLoss') == '0' and params.get('takeProfit') == '0' and params.get('trailingStop') == '0':
            return 'clear_all'
        if params.get('stopLoss') is None and params.get('takeProfit') is None and params.get('trailingStop') is None:
            return 'clear_all_fallback_none'
        if 'stopLoss' in params and params.get('slTriggerBy') == 'MarkPrice':
            return 'set_initial_sl'
        if 'takeProfit' in params:
            return 'set_initial_tp'
        return 'unknown'

    def set_trading_stop(self, symbol: str, params: Optional[dict[str, Any]] = None):
        params = params or {}
        operation = self._operation_from_params(params)
        self.calls.append((symbol, operation, params))
        if operation in self.fail_operations:
            raise ccxt.ExchangeError(f'{operation} forced failure')
        return {'retCode': 0, 'retMsg': 'OK'}


class FakeNativeStopExecutor:
    def __init__(self):
        self.initial_calls = []
        self.trailing_calls = []
        self.clear_calls = []
        self.ensure_calls = []
        self.initial_result = {
            'ok': True,
            'warnings': [],
            'native_sl_active': True,
            'native_tp_active': True,
            'native_trail_active': False,
            'native_sl_price': 97.5,
        }
        self.trailing_result = {
            'ok': True,
            'warnings': [],
            'native_sl_active': False,
            'native_tp_active': False,
            'native_trail_active': True,
            'native_sl_price': None,
        }
        self.clear_result = {
            'ok': True,
            'warnings': [],
            'native_sl_active': False,
            'native_tp_active': False,
            'native_trail_active': False,
            'native_sl_price': None,
        }
        self.ensure_result = dict(self.initial_result)

    def set_native_initial_protection(self, symbol: str, side: str, entry_price: float) -> dict[str, Any]:
        self.initial_calls.append((symbol, side, entry_price))
        return dict(self.initial_result)

    def set_native_trailing(self, symbol: str) -> dict[str, Any]:
        self.trailing_calls.append(symbol)
        return dict(self.trailing_result)

    def clear_native_protection(self, symbol: str) -> dict[str, Any]:
        self.clear_calls.append(symbol)
        return dict(self.clear_result)

    def ensure_native_protection_for_position(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        trailing_active: bool,
    ) -> dict[str, Any]:
        self.ensure_calls.append((symbol, side, entry_price, trailing_active))
        return dict(self.ensure_result)


class FakePosition:
    symbol = 'BTC/USDT:USDT'
    side = 'long'
    quantity = 2.0
    current_price = 100.0
    entry_price = 100.0


class CapturingDispatcher(AlertDispatcher):
    def __init__(self):
        super().__init__(bot_token='x', chat_id='y')
        self.captured_messages = []

    def send_message(self, text: str) -> bool:
        self.captured_messages.append(text)
        return True


def _build_telegram_test_bot(dispatcher: Any, authorized_chat_id: str = '111') -> tuple[Aribot, list[tuple[str, Any]]]:
    bot = Aribot.__new__(Aribot)
    bot.logger = LOGGER
    bot.alert_dispatcher = dispatcher
    bot.telegram_chat_id = authorized_chat_id
    bot.telegram_last_update_id = 0
    bot.bot_mode = 'paper'
    bot.last_regime_signal = 'UNKNOWN'
    bot.current_balance = 10000.0
    bot.session_start_balance = 10000.0
    bot.loop_cycle_count = 0
    bot.cooldown_until_utc = None
    bot.manual_entry_paused = False
    bot.manual_override_timestamp_utc = None
    bot.daily_drawdown_paused = False
    bot.positions = {}
    bot.total_pnl = 0.0
    bot.winning_trades = 0
    bot.losing_trades = 0
    bot.shutdown_requested = False
    bot.shutdown_exit_code = 0
    bot.kill_switch_file = 'kill_switch.flag'
    bot.telegram_confirmation_ttl_seconds = 90
    bot.telegram_pending_confirmations = {}
    bot.emit_structured_event = lambda *_args, **_kwargs: None
    bot.db = sqlite3.connect(':memory:', detect_types=sqlite3.PARSE_DECLTYPES)
    bot.db.row_factory = sqlite3.Row
    bot.db.execute(
        '''
        CREATE TABLE IF NOT EXISTS closed_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            side TEXT,
            entry_price REAL,
            exit_price REAL,
            quantity REAL,
            pnl REAL,
            pnl_percentage REAL,
            reason TEXT,
            open_time TEXT,
            close_time TEXT
        )
        '''
    )
    bot.db.commit()
    persisted_state: list[tuple[str, Any]] = []

    def _set_state_value(key: str, value: Any) -> None:
        persisted_state.append((key, value))

    bot.set_state_value = _set_state_value
    return bot, persisted_state


def test_1_order_placement() -> tuple[str, str]:
    criteria = [
        'A real market order is placed on Bybit testnet via ccxt.',
        'An exchange_order_id is returned.',
        'Fill polling reaches closed state and average fill price is computed from trades.',
    ]

    exchange = init_testnet_exchange()
    if exchange is None:
        return 'SKIP', 'Missing BYBIT_TEST_KEY/BYBIT_TEST_SECRET for testnet order placement.'

    symbol = os.getenv('TESTNET_SYMBOL', '').strip()
    quantity_raw = os.getenv('TESTNET_ORDER_QTY', '').strip()
    side = os.getenv('TESTNET_ORDER_SIDE', 'buy').strip().lower()
    if not symbol or not quantity_raw:
        return 'SKIP', 'Set TESTNET_SYMBOL and TESTNET_ORDER_QTY to run the real order placement test.'

    quantity = float(quantity_raw)
    leverage_raw = os.getenv('TESTNET_LEVERAGE', '').strip()
    if leverage_raw:
        try:
            exchange.set_leverage(int(float(leverage_raw)), symbol)
        except Exception as exc:
            LOGGER.warning('Failed to set leverage for %s: %s', symbol, exc)

    order = exchange.create_order(symbol=symbol, type='market', side=side, amount=quantity)
    order_id = order.get('id')
    if not order_id:
        return 'FAIL', f'Exchange did not return order id: {order}'

    try:
        closed_order = poll_closed_order(exchange, symbol, order_id, timeout_seconds=30)
        trades = exchange.fetch_my_trades(symbol=symbol, limit=50)
        order_trades = [trade for trade in trades if str(trade.get('order')) == str(order_id)]
        avg_fill_price = compute_avg_fill_price(order_trades)
    finally:
        with contextlib.suppress(Exception):
            flatten_side = 'sell' if side == 'buy' else 'buy'
            filled_qty = float(order.get('filled') or quantity)
            exchange.create_order(
                symbol=symbol,
                type='market',
                side=flatten_side,
                amount=filled_qty,
                params={'reduceOnly': True},
            )

    if avg_fill_price <= 0:
        return 'FAIL', f'Average fill price was not positive: {avg_fill_price}'

    return 'PASS', (
        f'order_id={order_id}, status={closed_order.get("status")}, '
        f'avg_fill_price={avg_fill_price:.8f}, trades={len(order_trades)}; '
        f'criteria={"; ".join(criteria)}'
    )


def test_2_reconciler() -> tuple[str, str]:
    criteria = [
        'An exchange-only ghost position is detected during startup reconciliation.',
        'startup_gate blocks startup when manual review is required.',
    ]

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / 'reconciler.db'
        seed_positions_db(db_path, symbol='LOCAL/USDT:USDT')
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            reconciler = StartupReconciler(FakeGhostPositionExchange(), conn, LOGGER)
            report = reconciler.reconcile_startup_state()
            startup_blocked = False
            try:
                reconciler.startup_gate()
            except RuntimeError:
                startup_blocked = True
        finally:
            conn.close()

    ghost_flagged = any(item.category == 'ghost_position' for item in report.items)
    if ghost_flagged and report.manual_review_required and startup_blocked:
        return 'PASS', f'Ghost/manual review detected and startup_gate blocked launch. report={report}'

    return 'FAIL', (
        'Ghost position was not enforced as startup blocker. '
        f'Current report categories={[item.category for item in report.items]}, '
        f'manual_review_required={report.manual_review_required}, startup_blocked={startup_blocked}'
    )


def test_3_kill_switch() -> tuple[str, str]:
    criteria = [
        'While the bot is running, writing kill_switch.flag triggers emergency shutdown.',
        'All persisted positions are closed/removed.',
        'Process exits within 60 seconds with intentional kill-switch exit code.',
    ]

    with patched_bot_workspace() as workdir:
        bot_source = (workdir / 'usdt_paper_bot_v2.py').read_text(encoding='utf-8')
        db_name = 'usdt_bot_v2.db' if "self.db_file = 'usdt_bot_v2.db'" in bot_source else 'usdt_paper_bot_v2.db'
        db_path = workdir / db_name
        seed_positions_db(db_path)

        env = os.environ.copy()
        env['BOT_MODE'] = 'paper'
        env['BYBIT_TESTNET'] = 'true'
        env['KILL_SWITCH_FILE'] = str(workdir / 'kill_switch.flag')
        env['PYTHONPATH'] = str(workdir)

        process = subprocess.Popen(
            ['python', 'usdt_paper_bot_v2.py'],
            cwd=workdir,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        log_candidates = [
            workdir / 'usdt_paper_trading_log.txt',
            workdir / 'usdt_trading_log.txt',
        ]
        deadline = time.time() + 45
        while time.time() < deadline:
            for log_path in log_candidates:
                if log_path.exists() and 'Cycle 1' in log_path.read_text(encoding='utf-8', errors='replace'):
                    break
            else:
                if process.poll() is not None:
                    return 'FAIL', f'Bot exited before kill-switch trigger. exit_code={process.returncode}'
                time.sleep(1)
                continue
            break
        else:
            process.terminate()
            return 'FAIL', 'Timed out waiting for bot to enter the main loop before kill-switch test.'

        (workdir / 'kill_switch.flag').write_text('triggered\n', encoding='utf-8')

        kill_deadline = time.time() + 60
        while time.time() < kill_deadline:
            if process.poll() is not None:
                break
            time.sleep(1)
        else:
            process.kill()
            return 'FAIL', 'Bot did not exit within 60 seconds of kill-switch trigger.'

        conn = sqlite3.connect(db_path)
        try:
            open_count = conn.execute('SELECT COUNT(*) FROM positions').fetchone()[0]
        finally:
            conn.close()

        if process.returncode != 42:
            return 'FAIL', f'Expected exit code 42 for intentional kill switch, got {process.returncode}'
        if open_count != 0:
            return 'FAIL', f'Expected positions to be closed/removed, found {open_count} remaining.'

        return 'PASS', f'Kill switch exited with code 42 and closed all persisted positions. criteria={"; ".join(criteria)}'


def test_4_funding_tracker() -> tuple[str, str]:
    criteria = [
        'A mocked funding payment is written to funding_payments.',
        'The returned funding delta is applied as a deduction to reported PnL for a long position.',
    ]

    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    tracker = FundingTracker(FakeFundingExchange(), conn, lambda **_: None, run_id='test-run')
    tracker.ensure_schema()

    starting_pnl = 50.0
    funding_delta = tracker.track_open_positions([FakePosition()], time.time())
    ending_pnl = starting_pnl + funding_delta
    row = conn.execute('SELECT COUNT(*) FROM funding_payments').fetchone()[0]
    conn.close()

    if row != 1:
        return 'FAIL', f'Expected 1 funding row, found {row}'
    if not funding_delta < 0:
        return 'FAIL', f'Expected negative funding deduction for long position, got {funding_delta}'
    if not ending_pnl < starting_pnl:
        return 'FAIL', f'Expected PnL to be reduced by funding, start={starting_pnl} end={ending_pnl}'

    return 'PASS', f'Funding row persisted and PnL reduced from {starting_pnl:.2f} to {ending_pnl:.2f}'


def test_5_dry_run() -> tuple[str, str]:
    criteria = [
        'With DRY_RUN=true, order execution returns success without reaching the exchange.',
        'Exchange create_order is never called.',
    ]

    previous_dry_run = os.environ.get('DRY_RUN')
    os.environ['DRY_RUN'] = 'true'
    try:
        executor = OrderExecutor('dummy_key', 'dummy_secret')
        fake_exchange = FakeExchangeCreateOrder()
        executor.exchange = fake_exchange
        result = executor.execute_order('BTC/USDT:USDT', 'market', 'buy', 0.001)
    finally:
        if previous_dry_run is None:
            os.environ.pop('DRY_RUN', None)
        else:
            os.environ['DRY_RUN'] = previous_dry_run

    if not result.success:
        return 'FAIL', f'DRY_RUN execution should succeed, got {result}'
    if fake_exchange.create_order_calls != 0:
        return 'FAIL', f'Exchange create_order was called {fake_exchange.create_order_calls} times in DRY_RUN mode'
    return 'PASS', f'DRY_RUN returned order_id={result.order_id} without touching exchange.'


def test_6_idempotency() -> tuple[str, str]:
    criteria = [
        'Submitting the same idempotency key twice does not send duplicate exchange orders.',
        'Second response is served from idempotency ledger.',
    ]

    with tempfile.TemporaryDirectory() as temp_dir:
        previous_db = os.environ.get('ORDER_EXECUTOR_DB')
        os.environ['ORDER_EXECUTOR_DB'] = str(Path(temp_dir) / 'order_executor.db')
        try:
            executor = OrderExecutor('dummy_key', 'dummy_secret')
            fake_exchange = FakeExchangeCreateOrder()
            executor.exchange = fake_exchange

            os.environ['DRY_RUN'] = 'false'
            executor.dry_run = False

            key = 'intent-btc-buy-001'
            first = executor.execute_order('BTC/USDT:USDT', 'market', 'buy', 0.001, idempotency_key=key)
            second = executor.execute_order('BTC/USDT:USDT', 'market', 'buy', 0.001, idempotency_key=key)
            executor.idempotency_db.close()
        finally:
            if previous_db is None:
                os.environ.pop('ORDER_EXECUTOR_DB', None)
            else:
                os.environ['ORDER_EXECUTOR_DB'] = previous_db

    if not first.success or not second.success:
        return 'FAIL', f'Expected both attempts to return success, got first={first}, second={second}'
    if fake_exchange.create_order_calls != 1:
        return 'FAIL', f'Expected 1 exchange call due to idempotency, got {fake_exchange.create_order_calls}'
    if 'Duplicate prevented by idempotency key' not in second.message:
        return 'FAIL', f'Second call did not report duplicate prevention: {second.message}'

    return 'PASS', f'Idempotency key suppressed duplicate exchange call. criteria={"; ".join(criteria)}'


def test_7_stop_loss_every_tick() -> tuple[str, str]:
    criteria = [
        'Stop loss is evaluated during each update_positions() cycle.',
        'A breached stop triggers close_position within the same cycle.',
    ]

    bot = Aribot.__new__(Aribot)
    pos = PaperPosition('BTC/USDT:USDT', 'long', 100.0, 1.0, datetime.datetime.now())
    pos.stop_loss = 95.0

    bot.positions = {'BTC/USDT:USDT': pos}
    bot.max_hold_minutes = 10_000
    bot.persist_position = lambda *_args, **_kwargs: None
    bot.record_partial_realization = lambda *_args, **_kwargs: None
    bot.persist_runtime_state = lambda *_args, **_kwargs: None
    bot.logger = LOGGER
    bot.current_balance = 10_000.0
    bot.total_pnl = 0.0

    closed = []
    bot.close_position = lambda symbol, reason: closed.append((symbol, reason))
    bot.analyze_market = lambda symbol, for_entry=False: {'current_price': 94.0}

    bot.update_positions()

    if not closed:
        return 'FAIL', 'Expected stop-loss breach to trigger close_position in same update cycle.'
    symbol, reason = closed[0]
    if reason != 'stop_loss':
        return 'FAIL', f'Expected stop_loss reason, got {reason} for {symbol}'

    return 'PASS', f'Stop-loss was checked and closed {symbol} during update cycle.'


def test_8_telegram_alert_routing() -> tuple[str, str]:
    criteria = [
        'position_opened triggers alert dispatch.',
        'position_closed triggers alert dispatch.',
        'non-alert info events remain suppressed.',
    ]

    dispatcher = CapturingDispatcher()
    open_sent = dispatcher.dispatch_event('INFO', 'position_opened', 'Opened.', symbol='BTC/USDT:USDT')
    close_sent = dispatcher.dispatch_event('INFO', 'position_closed', 'Closed.', symbol='BTC/USDT:USDT')
    silent_sent = dispatcher.dispatch_event('INFO', 'loop_cycle_completed', 'Cycle done.')

    if not open_sent or not close_sent:
        return 'FAIL', f'Expected open/close alert dispatch. open={open_sent} close={close_sent}'
    if silent_sent:
        return 'FAIL', 'Expected non-alert informational event to be suppressed.'
    if len(dispatcher.captured_messages) != 2:
        return 'FAIL', f'Expected 2 captured alerts, got {len(dispatcher.captured_messages)}'

    return 'PASS', f'Alert routing confirmed for open/close events. criteria={"; ".join(criteria)}'


def test_9_live_balance_sync_rebases_drawdown_baseline() -> tuple[str, str]:
    criteria = [
        'On first authenticated startup, exchange balance sync updates current_balance.',
        'Daily drawdown baseline is rebased from the 10000 seed to the synced exchange balance.',
        'Immediate daily drawdown halt is avoided for a fresh live run with no trades.',
    ]

    bot = Aribot.__new__(Aribot)
    bot.live_execution_enabled = True
    bot.daily_drawdown_paused = False
    bot.positions = {}
    bot.total_trades = 0
    bot.total_pnl = 0.0
    bot.initial_balance = 10000.0
    bot.current_balance = 501.03
    bot.session_start_balance = 10000.0
    bot.logger = LOGGER

    rebased = bot.rebase_daily_drawdown_baseline_after_live_sync()
    if not rebased:
        return 'FAIL', 'Expected baseline rebasing to occur after first live balance sync.'
    if abs(bot.session_start_balance - 501.03) > 1e-9:
        return 'FAIL', f'Expected session_start_balance=501.03, got {bot.session_start_balance}'

    drawdown = (bot.current_balance - bot.session_start_balance) / bot.session_start_balance
    if drawdown <= -0.05:
        return 'FAIL', f'Expected post-rebase drawdown to be above breaker threshold, got {drawdown}'

    return 'PASS', f'Baseline rebased to {bot.session_start_balance:.2f}; drawdown={drawdown:.4f}'


def test_10_entry_order_sets_leverage_before_create_order() -> tuple[str, str]:
    criteria = [
        'Entry order sets leverage before create_order.',
        'Bybit leverage params include both buyLeverage and sellLeverage.',
    ]

    with tempfile.TemporaryDirectory() as temp_dir:
        previous_db = os.environ.get('ORDER_EXECUTOR_DB')
        os.environ['ORDER_EXECUTOR_DB'] = str(Path(temp_dir) / 'order_executor.db')
        try:
            executor = OrderExecutor('dummy_key', 'dummy_secret')
            fake_exchange = FakeExchangeLeverageOrder()
            executor.exchange = fake_exchange
            executor.dry_run = False
            result = executor.execute_order(
                'BTC/USDT:USDT',
                'market',
                'buy',
                0.001,
                order_reason='entry',
                leverage=5,
            )
            executor.idempotency_db.close()
        finally:
            if previous_db is None:
                os.environ.pop('ORDER_EXECUTOR_DB', None)
            else:
                os.environ['ORDER_EXECUTOR_DB'] = previous_db

    if not result.success:
        return 'FAIL', f'Expected entry order success, got: {result.message}'
    if len(fake_exchange.calls) < 2:
        return 'FAIL', f'Expected set_leverage then create_order calls, got: {fake_exchange.calls}'
    if fake_exchange.calls[0][0] != 'set_leverage' or fake_exchange.calls[1][0] != 'create_order':
        return 'FAIL', f'Expected leverage call before create_order, got sequence: {fake_exchange.calls}'

    _, leverage_value, symbol, params = fake_exchange.calls[0]
    if leverage_value != 5 or symbol != 'BTC/USDT:USDT':
        return 'FAIL', f'Unexpected set_leverage args: {fake_exchange.calls[0]}'
    if not isinstance(params, dict) or params.get('buyLeverage') != 5 or params.get('sellLeverage') != 5:
        return 'FAIL', f'Expected buy/sell leverage params=5, got: {params}'

    return 'PASS', f'Entry leverage call ordering and params confirmed. criteria={"; ".join(criteria)}'


def test_11_entry_order_aborts_when_set_leverage_fails() -> tuple[str, str]:
    criteria = [
        'If leverage setup fails, order execution aborts.',
        'create_order is never called after leverage failure.',
    ]

    with tempfile.TemporaryDirectory() as temp_dir:
        previous_db = os.environ.get('ORDER_EXECUTOR_DB')
        os.environ['ORDER_EXECUTOR_DB'] = str(Path(temp_dir) / 'order_executor.db')
        try:
            executor = OrderExecutor('dummy_key', 'dummy_secret')
            fake_exchange = FakeExchangeLeverageOrder(fail_set_leverage=True)
            executor.exchange = fake_exchange
            executor.dry_run = False
            result = executor.execute_order(
                'BTC/USDT:USDT',
                'market',
                'buy',
                0.001,
                order_reason='entry',
                leverage=5,
            )
            executor.idempotency_db.close()
        finally:
            if previous_db is None:
                os.environ.pop('ORDER_EXECUTOR_DB', None)
            else:
                os.environ['ORDER_EXECUTOR_DB'] = previous_db

    if result.success:
        return 'FAIL', 'Expected leverage setup failure to abort order, but result was success.'

    create_calls = [call for call in fake_exchange.calls if call[0] == 'create_order']
    if create_calls:
        return 'FAIL', f'create_order should not run after leverage failure, got calls={fake_exchange.calls}'

    if 'Leverage setup failed' not in result.message:
        return 'FAIL', f'Expected leverage failure context in message, got: {result.message}'

    return 'PASS', f'Leverage failure aborted entry before create_order. criteria={"; ".join(criteria)}'


def test_12_non_entry_order_skips_leverage_precheck() -> tuple[str, str]:
    criteria = [
        'Non-entry order does not require leverage parameter.',
        'Non-entry order skips set_leverage and still executes create_order.',
    ]

    with tempfile.TemporaryDirectory() as temp_dir:
        previous_db = os.environ.get('ORDER_EXECUTOR_DB')
        os.environ['ORDER_EXECUTOR_DB'] = str(Path(temp_dir) / 'order_executor.db')
        try:
            executor = OrderExecutor('dummy_key', 'dummy_secret')
            fake_exchange = FakeExchangeLeverageOrder()
            executor.exchange = fake_exchange
            executor.dry_run = False
            result = executor.execute_order(
                'BTC/USDT:USDT',
                'market',
                'sell',
                0.001,
                order_reason='partial_profit',
            )
            executor.idempotency_db.close()
        finally:
            if previous_db is None:
                os.environ.pop('ORDER_EXECUTOR_DB', None)
            else:
                os.environ['ORDER_EXECUTOR_DB'] = previous_db

    if not result.success:
        return 'FAIL', f'Expected non-entry order to succeed without leverage, got: {result.message}'

    leverage_calls = [call for call in fake_exchange.calls if call[0] == 'set_leverage']
    create_calls = [call for call in fake_exchange.calls if call[0] == 'create_order']
    if leverage_calls:
        return 'FAIL', f'Non-entry order should skip set_leverage, got calls={fake_exchange.calls}'
    if not create_calls:
        return 'FAIL', f'Expected create_order call for non-entry order, got calls={fake_exchange.calls}'

    return 'PASS', f'Non-entry path skipped leverage precheck correctly. criteria={"; ".join(criteria)}'


def test_13_derive_pnl_pct_price_based_long_short() -> tuple[str, str]:
    criteria = [
        'Long and short pnl percentages are derived from entry/current prices only.',
        'buy/sell aliases match long/short behavior.',
        'Invalid entry values return 0.0 as a fail-safe.',
    ]

    checks = [
        ('long_loss', derive_pnl_pct(100, 97.5, 'long'), -2.5),
        ('short_gain', derive_pnl_pct(100, 97.5, 'short'), 2.5),
        ('long_gain', derive_pnl_pct(100, 103, 'long'), 3.0),
        ('short_loss', derive_pnl_pct(100, 103, 'short'), -3.0),
        ('buy_alias', derive_pnl_pct(100, 101, 'buy'), 1.0),
        ('sell_alias', derive_pnl_pct(100, 101, 'sell'), -1.0),
        ('invalid_entry', derive_pnl_pct(0, 101, 'long'), 0.0),
    ]

    failures = []
    for name, actual, expected in checks:
        if abs(actual - expected) > 1e-9:
            failures.append(f'{name}: expected {expected}, got {actual}')

    if failures:
        return 'FAIL', '; '.join(failures)

    return 'PASS', f'Price-based derivation checks passed. criteria={"; ".join(criteria)}'


def test_14_startup_reconciler_ignores_exchange_percentage_fields() -> tuple[str, str]:
    criteria = [
        'Startup reconciler does not ingest Bybit percentage fields into local positions.',
        'Upsert bootstrap stores pnl_percentage=0.0 and waits for runtime price refresh.',
    ]

    with tempfile.TemporaryDirectory() as temp_dir:
        conn = sqlite3.connect(Path(temp_dir) / 'reconciler_pct.db')
        conn.row_factory = sqlite3.Row
        try:
            seed_positions_db(Path(temp_dir) / 'reconciler_pct.db', symbol='LOCAL/USDT:USDT')
            reconciler = StartupReconciler(FakeExchangeWithPctFields(), conn, LOGGER)
            ex_pos = reconciler.fetch_open_exchange_positions()['BTC/USDT:USDT']
            reconciler.upsert_local_position_from_exchange('BTC/USDT:USDT', ex_pos, fallback_side='long')

            row = conn.execute(
                'SELECT entry_price, current_price, pnl_percentage FROM positions WHERE symbol = ?',
                ('BTC/USDT:USDT',),
            ).fetchone()
        finally:
            conn.close()

    if row is None:
        return 'FAIL', 'Expected reconciler upsert to create/update local position row.'
    if abs(float(row['pnl_percentage']) - 0.0) > 1e-9:
        return 'FAIL', f'Expected neutral pnl_percentage=0.0 at upsert, got {row["pnl_percentage"]}'
    if abs(float(row['entry_price']) - float(row['current_price'])) > 1e-9:
        return 'FAIL', f'Expected current_price to bootstrap from entry_price, got row={dict(row)}'

    return 'PASS', f'Reconciler ignored exchange percentage fields as required. criteria={"; ".join(criteria)}'


def test_15_recovery_recomputes_price_based_pct_before_stop_checks() -> tuple[str, str]:
    criteria = [
        'Startup recovery recomputes pnl_percentage from entry/current prices.',
        'Stale cached pnl_percentage does not trigger false stop-loss on restart.',
    ]

    bot = Aribot.__new__(Aribot)
    bot.logger = LOGGER

    pos = PaperPosition('BTC/USDT:USDT', 'long', 100.0, 1.0, datetime.datetime.now())
    pos.pnl_percentage = -30.0
    bot.positions = {pos.symbol: pos}

    closed = []
    persisted = []
    bot.close_position = lambda symbol, reason: closed.append((symbol, reason))
    bot.persist_position = lambda p: persisted.append((p.symbol, p.pnl_percentage))
    bot.analyze_market = lambda symbol: {'current_price': 99.0}

    bot.reconcile_positions_on_startup()

    updated_pct = bot.positions[pos.symbol].pnl_percentage
    if abs(updated_pct - (-1.0)) > 1e-9:
        return 'FAIL', f'Expected recomputed pnl_percentage=-1.0, got {updated_pct}'
    if closed:
        return 'FAIL', f'Expected no recovery stop close at -1.0%, got closes={closed}'
    if not persisted:
        return 'FAIL', 'Expected startup recovery to persist recomputed position state.'

    return 'PASS', f'Recovery used price-derived pct and avoided false stop-loss. criteria={"; ".join(criteria)}'


def test_16_native_initial_protection_warns_without_raising() -> tuple[str, str]:
    criteria = [
        'set_native_initial_protection returns structured warning status on API failure.',
        'Failure is non-blocking and does not raise exceptions to caller.',
    ]

    with tempfile.TemporaryDirectory() as temp_dir:
        previous_db = os.environ.get('ORDER_EXECUTOR_DB')
        os.environ['ORDER_EXECUTOR_DB'] = str(Path(temp_dir) / 'order_executor.db')
        try:
            executor = OrderExecutor('dummy_key', 'dummy_secret')
            executor.dry_run = False
            fake_exchange = FakeExchangeTradingStop(fail_operations={'set_initial_sl'})
            executor.exchange = fake_exchange
            result = executor.set_native_initial_protection('BTC/USDT:USDT', 'long', 100.0)
            executor.idempotency_db.close()
        finally:
            if previous_db is None:
                os.environ.pop('ORDER_EXECUTOR_DB', None)
            else:
                os.environ['ORDER_EXECUTOR_DB'] = previous_db

    if result.get('ok', True):
        return 'FAIL', f'Expected partial failure status, got result={result}'
    if result.get('native_tp_active') is not True:
        return 'FAIL', f'Expected TP branch to remain active when SL branch fails, got result={result}'
    if len(fake_exchange.calls) != 2:
        return 'FAIL', f'Expected 2 set_trading_stop calls (SL + TP), got {fake_exchange.calls}'

    return 'PASS', f'Native initial protection failure returned warning status without raise. criteria={"; ".join(criteria)}'


def test_17_open_position_continues_when_native_initial_fails() -> tuple[str, str]:
    criteria = [
        'Position open continues even when native initial protection call fails.',
        'Native status flags remain inactive when exchange confirmation is missing.',
    ]

    bot = Aribot.__new__(Aribot)
    bot.positions = {}
    bot.max_open_positions = 10
    bot.logger = LOGGER
    bot.current_balance = 10000.0
    bot.entry_risk_pct = 0.11
    bot.atr_volatility_cutoff = 0.05
    bot.atr_size_scalar = 0.5
    bot.round_trip_fee_rate = 0.0011
    bot.live_execution_enabled = True
    bot.total_trades = 0
    bot.get_leverage_for_symbol = lambda _symbol: (5.0, 'major')
    bot.persist_runtime_state = lambda: None
    bot.emit_structured_event = lambda *_args, **_kwargs: None
    bot.submit_market_order = lambda **kwargs: (True, {'filled': kwargs['quantity'], 'avg_fill_price': 100.0})

    persisted = []
    bot.persist_position = lambda pos: persisted.append((pos.symbol, pos.native_sl_active, pos.native_tp_active))

    fake_native = FakeNativeStopExecutor()
    fake_native.initial_result = {
        'ok': False,
        'warnings': [{'operation': 'set_initial', 'error': 'forced'}],
        'native_sl_active': False,
        'native_tp_active': False,
        'native_trail_active': False,
        'native_sl_price': None,
    }
    bot.order_executor = fake_native

    opened = bot.open_position({'symbol': 'BTC/USDT:USDT', 'current_price': 100.0, 'signal': 'BUY', 'atr_ratio': 0.01})
    if not opened:
        return 'FAIL', 'Expected open_position to succeed despite native-stop warning.'
    if 'BTC/USDT:USDT' not in bot.positions:
        return 'FAIL', 'Expected position to be present after successful open flow.'
    if len(fake_native.initial_calls) != 1:
        return 'FAIL', f'Expected exactly one native initial attempt, got {fake_native.initial_calls}'

    pos = bot.positions['BTC/USDT:USDT']
    if pos.native_sl_active or pos.native_tp_active or pos.native_trail_active:
        return 'FAIL', f'Expected native flags to remain inactive on failure, got sl/tp/trail={pos.native_sl_active}/{pos.native_tp_active}/{pos.native_trail_active}'
    if not persisted:
        return 'FAIL', 'Expected position persistence to still run in open flow.'

    return 'PASS', f'Open flow stayed non-blocking on native-stop failure. criteria={"; ".join(criteria)}'


def test_18_trailing_activation_sets_native_trailing_and_clears_fixed() -> tuple[str, str]:
    criteria = [
        'When trailing activates internally, native trailing is requested.',
        'Native fixed SL/TP flags are cleared and trail flag becomes active.',
    ]

    bot = Aribot.__new__(Aribot)
    bot.logger = LOGGER
    bot.live_execution_enabled = True
    bot.max_hold_minutes = 10_000
    bot.current_balance = 10_000.0
    bot.total_pnl = 0.0
    bot.persist_runtime_state = lambda: None
    bot.record_partial_realization = lambda *_args, **_kwargs: None
    bot.close_position = lambda *_args, **_kwargs: None

    pos = PaperPosition('BTC/USDT:USDT', 'long', 100.0, 1.0, datetime.datetime.now())
    pos.profit_taking_levels = [0.5, 0.6, 0.7]
    pos.native_sl_active = True
    pos.native_tp_active = True
    bot.positions = {pos.symbol: pos}

    fake_native = FakeNativeStopExecutor()
    bot.order_executor = fake_native
    bot.analyze_market = lambda _symbol, for_entry=False: {'current_price': 103.0}
    bot.persist_position = lambda *_args, **_kwargs: None

    bot.update_positions()

    if len(fake_native.trailing_calls) != 1:
        return 'FAIL', f'Expected trailing activation to call native trailing once, got {fake_native.trailing_calls}'
    if not pos.trailing_stop_active:
        return 'FAIL', 'Expected internal trailing stop to be active after +2% threshold.'
    if not pos.native_trail_active or pos.native_sl_active or pos.native_tp_active:
        return 'FAIL', (
            'Expected native flags trail-only after activation, '
            f'got sl/tp/trail={pos.native_sl_active}/{pos.native_tp_active}/{pos.native_trail_active}'
        )

    return 'PASS', f'Trailing transition updated native-stop state as expected. criteria={"; ".join(criteria)}'


def test_19_close_position_clears_native_non_blocking() -> tuple[str, str]:
    criteria = [
        'Close flow attempts native-stop clear when live execution is enabled.',
        'Native clear failure does not block local close completion.',
    ]

    bot = Aribot.__new__(Aribot)
    bot.logger = LOGGER
    bot.live_execution_enabled = True
    bot.current_balance = 10_000.0
    bot.total_pnl = 0.0
    bot.winning_trades = 0
    bot.losing_trades = 0
    bot.consecutive_losses = 0
    bot.max_consecutive_losses = 3
    bot.cooldown_candles = 2
    bot.closed_trades = []
    bot.persist_runtime_state = lambda: None
    bot.emit_structured_event = lambda *_args, **_kwargs: None
    removed = []
    bot.remove_persisted_position = lambda symbol: removed.append(symbol)
    bot.record_closed_trade = lambda *_args, **_kwargs: None

    persisted_flags = []
    bot.persist_position = lambda p: persisted_flags.append((p.native_sl_active, p.native_tp_active, p.native_trail_active, p.native_sl_price))

    pos = PaperPosition('BTC/USDT:USDT', 'long', 100.0, 0.0, datetime.datetime.now())
    pos.native_sl_active = True
    pos.native_tp_active = True
    pos.native_trail_active = True
    pos.native_sl_price = 97.5
    bot.positions = {pos.symbol: pos}

    fake_native = FakeNativeStopExecutor()
    fake_native.clear_result = {
        'ok': False,
        'warnings': [{'operation': 'clear_all', 'error': 'forced clear failure'}],
        'native_sl_active': False,
        'native_tp_active': False,
        'native_trail_active': False,
        'native_sl_price': None,
    }
    bot.order_executor = fake_native

    bot.close_position('BTC/USDT:USDT', 'manual_test')

    if fake_native.clear_calls != ['BTC/USDT:USDT']:
        return 'FAIL', f'Expected one native clear call, got {fake_native.clear_calls}'
    if bot.positions:
        return 'FAIL', f'Expected local position to close despite clear warning, remaining={bot.positions}'
    if removed != ['BTC/USDT:USDT']:
        return 'FAIL', f'Expected persisted position removal, got {removed}'
    if not persisted_flags:
        return 'FAIL', 'Expected close flow to persist cleared native flags before deletion.'

    sl_active, tp_active, trail_active, sl_price = persisted_flags[-1]
    if sl_active or tp_active or trail_active or sl_price is not None:
        return 'FAIL', f'Expected cleared native flags before remove, got {persisted_flags[-1]}'

    return 'PASS', f'Close flow remained non-blocking when native clear failed. criteria={"; ".join(criteria)}'


def test_20_startup_reconciler_rearms_missing_native_stops() -> tuple[str, str]:
    criteria = [
        'Startup reconciler re-arms native protection for overlap positions with all native flags off.',
        'Re-arm updates native columns without failing startup report.',
    ]

    class FakeOverlapExchange:
        def fetch_positions(self):
            return [
                {
                    'symbol': 'TEST/USDT:USDT',
                    'contracts': 1.0,
                    'entryPrice': 100.0,
                    'side': 'long',
                    'info': {},
                }
            ]

        def fetch_my_trades(self, symbol=None, limit=200):
            return []

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / 'rearm.db'
        seed_positions_db(db_path, symbol='TEST/USDT:USDT')
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            native_executor = FakeNativeStopExecutor()
            native_executor.ensure_result = {
                'ok': True,
                'warnings': [],
                'native_sl_active': True,
                'native_tp_active': True,
                'native_trail_active': False,
                'native_sl_price': 97.5,
            }

            reconciler = StartupReconciler(
                FakeOverlapExchange(),
                conn,
                LOGGER,
                native_stop_executor=native_executor,
            )
            report = reconciler.reconcile_startup_state()
            row = conn.execute(
                'SELECT native_sl_active, native_tp_active, native_trail_active, native_sl_price FROM positions WHERE symbol = ?',
                ('TEST/USDT:USDT',),
            ).fetchone()
        finally:
            conn.close()

    if not native_executor.ensure_calls:
        return 'FAIL', 'Expected startup reconciler to invoke native protection re-arm.'
    if row is None:
        return 'FAIL', 'Expected position row to remain after reconciliation.'
    if int(row['native_sl_active']) != 1 or int(row['native_tp_active']) != 1 or int(row['native_trail_active']) != 0:
        return 'FAIL', f'Expected native flags to reflect re-arm success, got row={dict(row)}'
    if not any(item.category == 'native_protection_rearmed' for item in report.items):
        return 'FAIL', f'Expected native_protection_rearmed report item, got categories={[item.category for item in report.items]}'

    return 'PASS', f'Startup native re-arm pass succeeded and persisted flags. criteria={"; ".join(criteria)}'


def test_24_branch_b_testnet_native_stop_round_trip() -> tuple[str, str]:
    criteria = [
        'Open a tiny real Bybit testnet position for a configured symbol.',
        'Set native SL via set_trading_stop and verify it appears in fetch_positions payload.',
        'Clear native stop fields via set_trading_stop and verify stop fields are cleared.',
        'Close the position and verify no open position remains for the side.',
    ]

    exchange = init_testnet_exchange()
    if exchange is None:
        return 'FAIL', 'Missing BYBIT_TEST_KEY/BYBIT_TEST_SECRET for Branch B testnet validation.'

    symbol = (os.getenv('BRANCH_B_TEST_SYMBOL') or os.getenv('TESTNET_SYMBOL') or '').strip()
    quantity_raw = (os.getenv('BRANCH_B_TEST_QTY') or os.getenv('TESTNET_ORDER_QTY') or '').strip()
    side = (os.getenv('BRANCH_B_TEST_SIDE') or 'buy').strip().lower()
    trailing_enabled = (os.getenv('BRANCH_B_VALIDATE_TRAILING') or 'true').strip().lower() in {'1', 'true', 'yes', 'on'}

    if not symbol:
        return 'FAIL', 'Missing symbol env. Set BRANCH_B_TEST_SYMBOL (or TESTNET_SYMBOL).'
    if not quantity_raw:
        return 'FAIL', 'Missing quantity env. Set BRANCH_B_TEST_QTY (or TESTNET_ORDER_QTY) to a tiny testnet size.'
    if side not in {'buy', 'sell'}:
        return 'FAIL', f'Invalid BRANCH_B_TEST_SIDE={side}. Expected buy or sell.'

    try:
        quantity = float(quantity_raw)
    except ValueError:
        return 'FAIL', f'Invalid quantity value: {quantity_raw}'
    if quantity <= 0:
        return 'FAIL', f'Quantity must be > 0, got {quantity}'

    open_order_id = ''
    close_order_id = ''
    sl_price: Optional[float] = None
    trailing_status = 'not_requested'

    try:
        open_order = exchange.create_order(symbol=symbol, type='market', side=side, amount=quantity)
        open_order_id = str(open_order.get('id') or '')
        if not open_order_id:
            return 'FAIL', f'Open order returned no id: {open_order}'

        closed_open = poll_closed_order(exchange, symbol, open_order_id, timeout_seconds=35)
        requested_side = 'long' if side == 'buy' else 'short'
        position, _ = _poll_position_snapshot(
            exchange,
            symbol,
            requested_side,
            predicate=lambda _snap: True,
            timeout_seconds=35,
        )

        entry_price = _safe_float(position.get('entryPrice')) or _safe_float(closed_open.get('average'))
        if not entry_price or entry_price <= 0:
            return 'FAIL', f'Could not determine positive entry price from position/order payloads. position={position}, order={closed_open}'

        is_long = side == 'buy'
        sl_price = entry_price * (1.0 - 0.025) if is_long else entry_price * (1.0 + 0.025)
        set_trading_stop_exchange(
            exchange,
            symbol,
            {
                'stopLoss': str(sl_price),
                'slTriggerBy': 'MarkPrice',
                'positionIdx': 0,
            },
        )

        _, sl_snapshot = _poll_position_snapshot(
            exchange,
            symbol,
            requested_side,
            predicate=lambda snap: bool(snap['stop_loss'] and snap['stop_loss'] > 0),
            timeout_seconds=35,
        )

        if not sl_snapshot['observed_any_native_paths']:
            return 'FAIL', (
                'Unable to verify native stop-loss because fetch_positions payload exposed no native stop fields. '
                f'snapshot={sl_snapshot}'
            )

        if trailing_enabled:
            try:
                set_trading_stop_exchange(
                    exchange,
                    symbol,
                    {
                        'trailingStop': '0.015',
                        'positionIdx': 0,
                    },
                )
                _, trail_snapshot = _poll_position_snapshot(
                    exchange,
                    symbol,
                    requested_side,
                    predicate=lambda snap: bool((snap['trailing_stop'] or 0) > 0) or bool((snap['stop_loss'] or 0) <= 0),
                    timeout_seconds=35,
                )
                if (trail_snapshot['trailing_stop'] or 0) > 0:
                    trailing_status = f"verified trailing_stop={trail_snapshot['trailing_stop']}"
                elif trail_snapshot['observed_any_native_paths']:
                    trailing_status = 'attempted; trailing field not exposed but payload changed'
                else:
                    trailing_status = 'attempted; not observable in payload'
            except Exception as exc:
                trailing_status = f'attempted; trailing call failed: {type(exc).__name__}: {exc}'

        set_trading_stop_exchange(
            exchange,
            symbol,
            {
                'stopLoss': '0',
                'takeProfit': '0',
                'trailingStop': '0',
                'positionIdx': 0,
            },
        )

        _, clear_snapshot = _poll_position_snapshot(
            exchange,
            symbol,
            requested_side,
            predicate=lambda snap: (
                snap['observed_any_native_paths']
                and (snap['stop_loss'] is None or snap['stop_loss'] <= 0)
                and (snap['take_profit'] is None or snap['take_profit'] <= 0)
                and (snap['trailing_stop'] is None or snap['trailing_stop'] <= 0)
            ),
            timeout_seconds=35,
        )

        close_side = 'sell' if side == 'buy' else 'buy'
        close_order = exchange.create_order(
            symbol=symbol,
            type='market',
            side=close_side,
            amount=quantity,
            params={'reduceOnly': True},
        )
        close_order_id = str(close_order.get('id') or '')
        if not close_order_id:
            return 'FAIL', f'Close order returned no id: {close_order}'
        poll_closed_order(exchange, symbol, close_order_id, timeout_seconds=35)

        deadline = time.time() + 35
        position_cleared = False
        while time.time() < deadline:
            if _find_open_position(exchange, symbol, requested_side) is None:
                position_cleared = True
                break
            time.sleep(2)
        if not position_cleared:
            return 'FAIL', f'Position remained open after reduce-only close for {symbol} {requested_side}.'

        return 'PASS', (
            f'open_order_id={open_order_id}, close_order_id={close_order_id}, '
            f'sl_price={sl_price:.8f}, sl_paths={sl_snapshot["stop_paths"]}, '
            f'clear_snapshot={clear_snapshot}, trailing={trailing_status}, '
            f'criteria={"; ".join(criteria)}'
        )
    except Exception as exc:
        return 'FAIL', f'{type(exc).__name__}: {exc}'
    finally:
        with contextlib.suppress(Exception):
            set_trading_stop_exchange(
                exchange,
                symbol,
                {
                    'stopLoss': '0',
                    'takeProfit': '0',
                    'trailingStop': '0',
                    'positionIdx': 0,
                },
            )

        with contextlib.suppress(Exception):
            requested_side = 'long' if side == 'buy' else 'short'
            remaining = _find_open_position(exchange, symbol, requested_side)
            if remaining is not None:
                contracts = remaining.get('contracts')
                if contracts is None and isinstance(remaining.get('info'), dict):
                    contracts = remaining['info'].get('size')
                remaining_qty = abs(float(contracts or 0.0))
                if remaining_qty > 0:
                    close_side = 'sell' if side == 'buy' else 'buy'
                    exchange.create_order(
                        symbol=symbol,
                        type='market',
                        side=close_side,
                        amount=remaining_qty,
                        params={'reduceOnly': True},
                    )


def test_25_telegram_transport_get_updates_offset_progression() -> tuple[str, str]:
    criteria = [
        'Telegram transport get_updates returns structured payload with updates list.',
        'next_offset advances to max(update_id)+1 for replay-safe restart behavior.',
    ]

    original_get = alert_dispatcher_module.requests.get

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        @staticmethod
        def json() -> dict[str, Any]:
            return {
                'ok': True,
                'result': [
                    {'update_id': 14, 'message': {'text': '/status'}},
                    {'update_id': 16, 'message': {'text': '/pnl'}},
                    {'update_id': 15, 'message': {'text': '/positions'}},
                ],
            }

    def fake_get(url: str, params: dict[str, Any], timeout: int) -> FakeResponse:
        del url
        del timeout
        if params.get('offset') != 10:
            raise AssertionError(f'Expected offset=10, got params={params}')
        return FakeResponse()

    alert_dispatcher_module.requests.get = fake_get
    try:
        dispatcher = AlertDispatcher(bot_token='token', chat_id='111', logger=LOGGER)
        payload = dispatcher.get_updates(offset=10, timeout_seconds=0, limit=25)
    finally:
        alert_dispatcher_module.requests.get = original_get

    if not payload.get('ok'):
        return 'FAIL', f'Expected ok payload, got {payload}'
    if payload.get('next_offset') != 17:
        return 'FAIL', f'Expected next_offset=17, got payload={payload}'
    if len(payload.get('updates', [])) != 3:
        return 'FAIL', f'Expected 3 updates in payload, got {payload}'

    return 'PASS', f'Transport next_offset advanced correctly to 17. criteria={"; ".join(criteria)}'


def test_26_telegram_poll_non_blocking_and_strict_parser_auth_gate() -> tuple[str, str]:
    criteria = [
        'Polling failures are warning-only and do not raise from poll_telegram_commands_once.',
        'Processed updates persist telegram_last_update_id after each handled/ignored update.',
        'Parser accepts only approved commands and invalid commands return supported-command help text.',
        'Unauthorized chat IDs are rejected with no authorized command side effects.',
    ]

    class ScriptedDispatcher:
        enabled = True

        def __init__(self) -> None:
            self.calls = 0
            self.sent_messages: list[str] = []
            self.offsets: list[int] = []

        def get_updates(self, offset: int | None = None, timeout_seconds: int = 0, limit: int = 25) -> dict[str, Any]:
            del timeout_seconds
            del limit
            self.offsets.append(int(offset or 0))
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError('simulated transport failure')
            return {
                'ok': True,
                'updates': [
                    {'update_id': 1, 'message': {'chat': {'id': '111'}, 'text': '/status'}},
                    {'update_id': 2, 'message': {'chat': {'id': '999'}, 'text': '/pnl'}},
                    {'update_id': 3, 'message': {'chat': {'id': '111'}, 'text': '/notreal'}},
                    {'update_id': 4, 'message': {'chat': {'id': '111'}, 'text': '/trades 2'}},
                ],
            }

        def send_message(self, text: str) -> bool:
            self.sent_messages.append(text)
            return True

    dispatcher = ScriptedDispatcher()
    bot, persisted_state = _build_telegram_test_bot(dispatcher, authorized_chat_id='111')

    try:
        bot.poll_telegram_commands_once(cycle_index=1)
    except Exception as exc:
        return 'FAIL', f'Polling failure should be warning-only, but raised {type(exc).__name__}: {exc}'

    if bot.telegram_last_update_id != 0:
        return 'FAIL', f'Offset should remain 0 after failed poll, got {bot.telegram_last_update_id}'

    bot.poll_telegram_commands_once(cycle_index=2)

    if bot.telegram_last_update_id != 5:
        return 'FAIL', f'Expected offset to advance to 5, got {bot.telegram_last_update_id}'

    state_writes = [entry for entry in persisted_state if entry[0] == 'telegram_last_update_id']
    if [value for _, value in state_writes] != [2, 3, 4, 5]:
        return 'FAIL', f'Expected per-update offset persistence [2,3,4,5], got {state_writes}'

    expected_help = bot.supported_telegram_commands_help_text()
    if expected_help not in dispatcher.sent_messages:
        return 'FAIL', f'Expected invalid-command help response, got messages={dispatcher.sent_messages}'
    if 'Unauthorized chat.' not in dispatcher.sent_messages:
        return 'FAIL', f'Expected unauthorized chat rejection, got messages={dispatcher.sent_messages}'
    if not any(msg.startswith('Status\n') for msg in dispatcher.sent_messages):
        return 'FAIL', f'Expected /status runtime output, got messages={dispatcher.sent_messages}'
    if 'No closed trades found.' not in dispatcher.sent_messages:
        return 'FAIL', f'Expected /trades 2 empty-state output, got messages={dispatcher.sent_messages}'

    valid_cases = [
        '/status',
        '/positions',
        '/pnl',
        '/trades',
        '/trades 3',
        '/pause',
        '/resume',
        '/close all',
        '/close BTC/USDT:USDT',
        '/kill',
        '/config',
    ]
    for raw in valid_cases:
        parsed = bot.parse_telegram_command(raw)
        if not parsed.get('ok'):
            return 'FAIL', f'Expected valid parser result for {raw}, got {parsed}'

    invalid_cases = [
        '/close',
        '/close   ',
        '/close all now',
        '/trades 0',
        '/trades -1',
        '/trades abc',
        '/config now',
        '/status now',
        '/unknown',
    ]
    for raw in invalid_cases:
        parsed = bot.parse_telegram_command(raw)
        if parsed.get('ok'):
            return 'FAIL', f'Expected invalid parser result for {raw}, got {parsed}'

    return 'PASS', f'Telegram poll/parser/auth behavior satisfied task criteria. criteria={"; ".join(criteria)}'


def _insert_closed_trade_row(bot: Aribot, symbol: str, pnl: float, pnl_pct: float, reason: str, close_time_iso: str) -> None:
    bot.db.execute(
        '''
        INSERT INTO closed_trades (
            symbol, side, entry_price, exit_price, quantity,
            pnl, pnl_percentage, reason, open_time, close_time
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            symbol,
            'long',
            100.0,
            101.0,
            1.0,
            pnl,
            pnl_pct,
            reason,
            close_time_iso,
            close_time_iso,
        ),
    )
    bot.db.commit()


def test_27_telegram_status_runtime_snapshot_fields_and_cooldown_state() -> tuple[str, str]:
    criteria = [
        '/status includes mode, regime, session pnl, cycle count, drawdown %, and cooldown state.',
        'Cooldown state toggles based on cooldown_until_utc relative to now.',
    ]

    class SinkDispatcher:
        enabled = True

        def send_message(self, text: str) -> bool:
            del text
            return True

    bot, _ = _build_telegram_test_bot(SinkDispatcher(), authorized_chat_id='111')
    now = datetime.datetime(2026, 3, 30, 12, 0, 0, tzinfo=datetime.timezone.utc)
    bot.bot_mode = 'shadow'
    bot.last_regime_signal = 'BUY'
    bot.current_balance = 9800.0
    bot.session_start_balance = 10000.0
    bot.loop_cycle_count = 42
    bot.cooldown_until_utc = now + datetime.timedelta(minutes=15)

    snapshot = bot.build_runtime_status_snapshot(now_utc=now)
    required_keys = {
        'mode',
        'regime_direction',
        'session_pnl',
        'cycle_count',
        'drawdown_pct',
        'cooldown_active',
        'cooldown_until_utc',
    }
    if set(snapshot.keys()) != required_keys:
        return 'FAIL', f'Unexpected status snapshot keys: {snapshot.keys()}'

    if snapshot['mode'] != 'shadow' or snapshot['regime_direction'] != 'BUY':
        return 'FAIL', f'Unexpected mode/regime in snapshot: {snapshot}'
    if abs(snapshot['session_pnl'] - (-200.0)) > 1e-9:
        return 'FAIL', f'Expected session_pnl=-200.0, got {snapshot["session_pnl"]}'
    if abs(snapshot['drawdown_pct'] - (-2.0)) > 1e-9:
        return 'FAIL', f'Expected drawdown_pct=-2.0, got {snapshot["drawdown_pct"]}'
    if snapshot['cycle_count'] != 42:
        return 'FAIL', f'Expected cycle_count=42, got {snapshot["cycle_count"]}'
    if not snapshot['cooldown_active']:
        return 'FAIL', f'Expected cooldown_active=True, got {snapshot}'

    bot.cooldown_until_utc = now - datetime.timedelta(minutes=1)
    if bot.build_runtime_status_snapshot(now_utc=now)['cooldown_active']:
        return 'FAIL', 'Expected cooldown_active=False when cooldown timestamp is in the past.'

    return 'PASS', f'Status snapshot fields and cooldown toggle validated. criteria={"; ".join(criteria)}'


def test_28_telegram_positions_output_empty_and_multi_position_rows() -> tuple[str, str]:
    criteria = [
        '/positions returns explicit no-open-positions message for empty state.',
        '/positions includes symbol, side, entry, current price, pnl%, and trail active per row.',
    ]

    class SinkDispatcher:
        enabled = True

        def send_message(self, text: str) -> bool:
            del text
            return True

    bot, _ = _build_telegram_test_bot(SinkDispatcher(), authorized_chat_id='111')
    if bot.format_positions_command_text() != 'No open positions.':
        return 'FAIL', f'Unexpected empty /positions output: {bot.format_positions_command_text()}'

    ts = datetime.datetime.now()
    btc = PaperPosition('BTC/USDT:USDT', 'long', 100.0, 1.0, ts)
    btc.update_price(102.0)
    btc.trailing_stop_active = True

    eth = PaperPosition('ETH/USDT:USDT', 'short', 200.0, 1.0, ts)
    eth.update_price(198.0)
    eth.trailing_stop_active = False

    bot.positions = {
        btc.symbol: btc,
        eth.symbol: eth,
    }
    text = bot.format_positions_command_text()
    if 'Positions' not in text:
        return 'FAIL', f'Missing positions header: {text}'
    if 'BTC/USDT:USDT long' not in text or 'trail=yes' not in text:
        return 'FAIL', f'Missing required BTC position fields: {text}'
    if 'ETH/USDT:USDT short' not in text or 'trail=no' not in text:
        return 'FAIL', f'Missing required ETH position fields: {text}'
    if 'e=' not in text or 'px=' not in text or 'pnl=' not in text:
        return 'FAIL', f'Missing entry/current/pnl markers: {text}'

    return 'PASS', f'/positions formatting validated for empty and populated states. criteria={"; ".join(criteria)}'


def test_29_telegram_pnl_uses_today_closed_trades_and_session_metrics() -> tuple[str, str]:
    criteria = [
        '/pnl uses UTC-today realized pnl from closed_trades.',
        '/pnl includes cumulative pnl and win/loss counts from bot session state.',
    ]

    class SinkDispatcher:
        enabled = True

        def send_message(self, text: str) -> bool:
            del text
            return True

    bot, _ = _build_telegram_test_bot(SinkDispatcher(), authorized_chat_id='111')
    now = datetime.datetime(2026, 3, 30, 12, 0, 0, tzinfo=datetime.timezone.utc)
    today_1 = now.replace(hour=1, minute=0, second=0)
    today_2 = now.replace(hour=8, minute=30, second=0)
    yesterday = now - datetime.timedelta(days=1)

    _insert_closed_trade_row(bot, 'BTC/USDT:USDT', pnl=12.0, pnl_pct=1.2, reason='trail', close_time_iso=today_1.isoformat())
    _insert_closed_trade_row(bot, 'ETH/USDT:USDT', pnl=-3.0, pnl_pct=-0.3, reason='stop', close_time_iso=today_2.isoformat())
    _insert_closed_trade_row(bot, 'SOL/USDT:USDT', pnl=100.0, pnl_pct=10.0, reason='time_exit', close_time_iso=yesterday.isoformat())

    bot.total_pnl = 321.5
    bot.winning_trades = 9
    bot.losing_trades = 4
    text = bot.format_pnl_command_text(now_utc=now)

    if 'today_realized=+9.00' not in text:
        return 'FAIL', f'Expected today realized +9.00 from UTC-day filter, got: {text}'
    if 'cumulative=+321.50' not in text:
        return 'FAIL', f'Expected cumulative +321.50 in /pnl output, got: {text}'
    if 'wins=9 losses=4' not in text:
        return 'FAIL', f'Expected wins/losses in /pnl output, got: {text}'

    return 'PASS', f'/pnl output validated with today filter and session counters. criteria={"; ".join(criteria)}'


def test_30_telegram_trades_default_today_and_last_n_modes() -> tuple[str, str]:
    criteria = [
        '/trades with no n returns today-only closed trades (UTC).',
        '/trades n returns the last n closed trades regardless of day.',
        'Each row includes symbol, pnl/pnl%, reason, and close timestamp.',
    ]

    class SinkDispatcher:
        enabled = True

        def send_message(self, text: str) -> bool:
            del text
            return True

    bot, _ = _build_telegram_test_bot(SinkDispatcher(), authorized_chat_id='111')
    now = datetime.datetime(2026, 3, 30, 12, 0, 0, tzinfo=datetime.timezone.utc)
    today_a = now.replace(hour=2, minute=10, second=0)
    today_b = now.replace(hour=11, minute=55, second=0)
    older = now - datetime.timedelta(days=2)

    _insert_closed_trade_row(bot, 'BTC/USDT:USDT', pnl=10.0, pnl_pct=1.0, reason='trail', close_time_iso=today_a.isoformat())
    _insert_closed_trade_row(bot, 'ETH/USDT:USDT', pnl=-5.0, pnl_pct=-0.5, reason='stop', close_time_iso=today_b.isoformat())
    _insert_closed_trade_row(bot, 'SOL/USDT:USDT', pnl=7.0, pnl_pct=0.7, reason='time_exit', close_time_iso=older.isoformat())

    today_text = bot.format_trades_command_text(limit=None, now_utc=now)
    if 'Trades today (UTC)' not in today_text:
        return 'FAIL', f'Missing today-mode header: {today_text}'
    if 'SOL/USDT:USDT' in today_text:
        return 'FAIL', f'Today-mode should exclude non-today row: {today_text}'
    if 'BTC/USDT:USDT' not in today_text or 'ETH/USDT:USDT' not in today_text:
        return 'FAIL', f'Today-mode should include today rows: {today_text}'
    if 'trail' not in today_text or 'stop' not in today_text:
        return 'FAIL', f'Expected reason field in today rows: {today_text}'

    last_two = bot.format_trades_command_text(limit=2, now_utc=now)
    if 'Trades last 2' not in last_two:
        return 'FAIL', f'Missing last-n header: {last_two}'
    if 'SOL/USDT:USDT' in last_two:
        return 'FAIL', f'Expected only most recent 2 rows in last-n mode, got: {last_two}'
    if 'pnl=' not in last_two or '%' not in last_two:
        return 'FAIL', f'Expected pnl and pnl% fields in last-n output: {last_two}'

    return 'PASS', f'/trades behavior validated for default and n modes. criteria={"; ".join(criteria)}'


def test_31_telegram_pause_resume_manual_gate_and_entry_path_behavior() -> tuple[str, str]:
    criteria = [
        '/pause enables manual entry gate while keeping update_positions loop callable.',
        '/resume clears manual pause and reopens entry path when no other gate is active.',
        'Manual override timestamp is recorded and returned in operator response.',
    ]

    class RecordingDispatcher:
        enabled = True

        def __init__(self) -> None:
            self.sent_messages: list[str] = []

        def send_message(self, text: str) -> bool:
            self.sent_messages.append(text)
            return True

    dispatcher = RecordingDispatcher()
    bot, persisted_state = _build_telegram_test_bot(dispatcher, authorized_chat_id='111')
    now = datetime.datetime(2026, 3, 30, 12, 0, 0, tzinfo=datetime.timezone.utc)

    pause_result = bot.route_telegram_command('111', '/pause', update_id=1, now_utc=now)
    if pause_result != 'accepted' or not bot.manual_entry_paused:
        return 'FAIL', f'/pause should activate manual gate, got result={pause_result}, paused={bot.manual_entry_paused}'
    if bot.entry_gate_block_reason() != 'manual_pause':
        return 'FAIL', f'Expected manual_pause gate after /pause, got {bot.entry_gate_block_reason()}'
    if bot.manual_override_timestamp_utc != now:
        return 'FAIL', f'Expected manual override timestamp to match command time, got {bot.manual_override_timestamp_utc}'

    called = {'count': 0}
    pos = PaperPosition('BTC/USDT:USDT', 'long', 100.0, 1.0, datetime.datetime.now())
    bot.positions = {pos.symbol: pos}
    bot.analyze_market = lambda symbol, for_entry=False: called.__setitem__('count', called['count'] + 1) or None
    bot.persist_position = lambda _pos: None
    bot.close_position = lambda symbol, reason: None
    bot.update_positions()
    if called['count'] != 1:
        return 'FAIL', 'update_positions path should continue running while manual pause is active.'

    resume_time = now + datetime.timedelta(minutes=3)
    resume_result = bot.route_telegram_command('111', '/resume', update_id=2, now_utc=resume_time)
    if resume_result != 'accepted' or bot.manual_entry_paused:
        return 'FAIL', f'/resume should clear manual gate, got result={resume_result}, paused={bot.manual_entry_paused}'
    if bot.entry_gate_block_reason() is not None:
        return 'FAIL', f'Expected entry gate open after /resume with no other blockers, got {bot.entry_gate_block_reason()}'
    if bot.manual_override_timestamp_utc != resume_time:
        return 'FAIL', f'Expected override timestamp update on /resume, got {bot.manual_override_timestamp_utc}'

    manual_pause_writes = [entry for entry in persisted_state if entry[0] == 'telegram_manual_pause_active']
    if [value for _, value in manual_pause_writes] != [1, 0]:
        return 'FAIL', f'Expected pause state persistence writes [1,0], got {manual_pause_writes}'
    if not any(key == 'telegram_manual_pause_updated_at' for key, _ in persisted_state):
        return 'FAIL', f'Expected manual override timestamp persistence writes, got {persisted_state}'

    if not any(msg.startswith('Entries paused (new entries only). override_utc=') for msg in dispatcher.sent_messages):
        return 'FAIL', f'Missing /pause operator response with override timestamp: {dispatcher.sent_messages}'
    if not any(msg.startswith('Entries resumed. override_utc=') for msg in dispatcher.sent_messages):
        return 'FAIL', f'Missing /resume operator response with override timestamp: {dispatcher.sent_messages}'

    return 'PASS', f'/pause and /resume gating behavior validated. criteria={"; ".join(criteria)}'


def test_32_telegram_confirmation_workflow_ttl_single_use_cancel_and_replay_protection() -> tuple[str, str]:
    criteria = [
        'Dangerous commands create pending confirmations and do not execute before YES.',
        'Non-YES cancels pending action, and YES only executes latest pending action once.',
        'Expired or canceled pending action cannot execute.',
    ]

    class RecordingDispatcher:
        enabled = True

        def __init__(self) -> None:
            self.sent_messages: list[str] = []

        def send_message(self, text: str) -> bool:
            self.sent_messages.append(text)
            return True

    dispatcher = RecordingDispatcher()
    bot, persisted_state = _build_telegram_test_bot(dispatcher, authorized_chat_id='111')
    bot.telegram_confirmation_ttl_seconds = 5

    now = datetime.datetime(2026, 3, 30, 12, 0, 0, tzinfo=datetime.timezone.utc)
    close_calls: list[tuple[str, str]] = []
    close_all_calls = {'count': 0}
    shutdown_codes: list[int] = []
    bot.close_position = lambda symbol, reason: close_calls.append((symbol, reason))
    bot.close_all_positions_market = lambda: close_all_calls.__setitem__('count', close_all_calls['count'] + 1) or 0
    bot.request_clean_shutdown = lambda exit_code=0: shutdown_codes.append(int(exit_code))

    bot.route_telegram_command('111', '/close BTC/USDT:USDT', update_id=1, now_utc=now)
    if close_calls:
        return 'FAIL', f'Close side effect occurred before YES: close_calls={close_calls}'
    if not any('Confirm /close BTC/USDT:USDT: reply YES within 5s.' in msg for msg in dispatcher.sent_messages):
        return 'FAIL', f'Missing confirmation prompt for /close SYMBOL: {dispatcher.sent_messages}'

    bot.route_telegram_command('111', 'no', update_id=2, now_utc=now)
    if 'Pending action canceled.' not in dispatcher.sent_messages:
        return 'FAIL', f'Expected cancel message after non-YES reply: {dispatcher.sent_messages}'

    pre_yes_close_all = close_all_calls['count']
    bot.route_telegram_command('111', 'YES', update_id=3, now_utc=now)
    if close_all_calls['count'] != pre_yes_close_all:
        return 'FAIL', f'YES after cancel should not execute side effects, close_all_calls={close_all_calls}'
    if 'No pending confirmation.' not in dispatcher.sent_messages:
        return 'FAIL', f'Expected no-pending response on YES replay, got {dispatcher.sent_messages}'

    bot.route_telegram_command('111', '/close all', update_id=4, now_utc=now)
    bot.route_telegram_command('111', '/kill', update_id=5, now_utc=now)
    pending = bot.telegram_pending_confirmations.get('111', {})
    if pending.get('action') != 'kill':
        return 'FAIL', f'Latest pending action should be kill, got {pending}'
    if not str(pending.get('nonce') or '').strip():
        return 'FAIL', f'Expected pending confirmation nonce for replay safety, got {pending}'

    with tempfile.TemporaryDirectory() as temp_dir:
        bot.kill_switch_file = str(Path(temp_dir) / 'kill_switch.flag')
        bot.route_telegram_command('111', 'YES', update_id=6, now_utc=now)
        if not Path(bot.kill_switch_file).exists():
            return 'FAIL', 'Expected /kill YES to write kill switch file.'

    if close_all_calls['count'] != pre_yes_close_all + 1:
        return 'FAIL', f'Expected exactly one latest-action execution on YES, got close_all_calls={close_all_calls}'
    if shutdown_codes != [42]:
        return 'FAIL', f'Expected one shutdown request with exit code 42, got {shutdown_codes}'

    bot.route_telegram_command('111', '/close all', update_id=7, now_utc=now)
    before_expired_yes = close_all_calls['count']
    bot.route_telegram_command('111', 'YES', update_id=8, now_utc=now + datetime.timedelta(seconds=6))
    if close_all_calls['count'] != before_expired_yes:
        return 'FAIL', f'Expired pending action should not execute, close_all_calls={close_all_calls}'
    if 'Pending action expired. Re-issue command.' not in dispatcher.sent_messages:
        return 'FAIL', f'Expected explicit expired confirmation message, got {dispatcher.sent_messages}'
    if not any(key == 'telegram_pending_confirmations_json' for key, _ in persisted_state):
        return 'FAIL', f'Expected pending confirmation persistence writes, got {persisted_state}'

    return 'PASS', f'Confirmation TTL/cancel/single-use/replay protections validated. criteria={"; ".join(criteria)}'


def test_33_telegram_close_symbol_and_close_all_execute_only_after_yes_with_safe_unknown_symbol() -> tuple[str, str]:
    criteria = [
        '/close SYMBOL and /close all execute only after valid YES confirmation.',
        '/close SYMBOL unknown symbol returns safe error with no side effects.',
    ]

    class RecordingDispatcher:
        enabled = True

        def __init__(self) -> None:
            self.sent_messages: list[str] = []

        def send_message(self, text: str) -> bool:
            self.sent_messages.append(text)
            return True

    dispatcher = RecordingDispatcher()
    bot, _ = _build_telegram_test_bot(dispatcher, authorized_chat_id='111')
    bot.telegram_confirmation_ttl_seconds = 10
    now = datetime.datetime(2026, 3, 30, 12, 0, 0, tzinfo=datetime.timezone.utc)

    bot.positions = {
        'BTC/USDT:USDT': object(),
        'ETH/USDT:USDT': object(),
    }
    close_calls: list[tuple[str, str]] = []

    def _close_symbol_stub(symbol: str, reason: str) -> None:
        close_calls.append((symbol, reason))
        bot.positions.pop(symbol, None)

    close_all_calls = {'count': 0}

    def _close_all_stub() -> int:
        close_all_calls['count'] += 1
        count = len(bot.positions)
        bot.positions.clear()
        return count

    bot.close_position = _close_symbol_stub
    bot.close_all_positions_market = _close_all_stub

    bot.route_telegram_command('111', '/close BTC/USDT:USDT', update_id=1, now_utc=now)
    if close_calls:
        return 'FAIL', f'/close SYMBOL executed before YES: close_calls={close_calls}'
    bot.route_telegram_command('111', 'YES', update_id=2, now_utc=now)
    if close_calls != [('BTC/USDT:USDT', 'telegram_manual_close')]:
        return 'FAIL', f'/close SYMBOL YES should call close_position once, got {close_calls}'
    if not any('Closed position BTC/USDT:USDT.' in msg for msg in dispatcher.sent_messages):
        return 'FAIL', f'Missing close success response: {dispatcher.sent_messages}'

    prior_calls = list(close_calls)
    bot.route_telegram_command('111', '/close DOGE/USDT:USDT', update_id=3, now_utc=now)
    bot.route_telegram_command('111', 'YES', update_id=4, now_utc=now)
    if close_calls != prior_calls:
        return 'FAIL', f'Unknown symbol should have no side effects, got close_calls={close_calls}'
    if not any('Cannot close DOGE/USDT:USDT: no open position.' in msg for msg in dispatcher.sent_messages):
        return 'FAIL', f'Missing safe unknown-symbol error response: {dispatcher.sent_messages}'

    bot.positions['ETH/USDT:USDT'] = object()
    bot.route_telegram_command('111', '/close all', update_id=5, now_utc=now)
    if close_all_calls['count'] != 0:
        return 'FAIL', f'/close all executed before YES: close_all_calls={close_all_calls}'
    bot.route_telegram_command('111', 'YES', update_id=6, now_utc=now)
    if close_all_calls['count'] != 1:
        return 'FAIL', f'/close all YES should call close_all flow once, got {close_all_calls}'

    bot.positions['ETH/USDT:USDT'] = object()
    bot.route_telegram_command('111', '/close all', update_id=7, now_utc=now)
    before_expired_yes = close_all_calls['count']
    bot.route_telegram_command('111', 'YES', update_id=8, now_utc=now + datetime.timedelta(seconds=11))
    if close_all_calls['count'] != before_expired_yes:
        return 'FAIL', f'Expired /close all confirmation should not execute, got {close_all_calls}'

    return 'PASS', f'/close SYMBOL and /close all confirmation-gated execution validated. criteria={"; ".join(criteria)}'


def test_34_telegram_kill_executes_only_after_yes_and_requests_exit_42() -> tuple[str, str]:
    criteria = [
        '/kill writes kill_switch file only after YES confirmation.',
        '/kill YES triggers close-all flow and requests shutdown exit code 42.',
    ]

    class RecordingDispatcher:
        enabled = True

        def __init__(self) -> None:
            self.sent_messages: list[str] = []

        def send_message(self, text: str) -> bool:
            self.sent_messages.append(text)
            return True

    dispatcher = RecordingDispatcher()
    bot, _ = _build_telegram_test_bot(dispatcher, authorized_chat_id='111')
    now = datetime.datetime(2026, 3, 30, 12, 0, 0, tzinfo=datetime.timezone.utc)

    close_all_calls = {'count': 0}

    def _close_all_stub() -> int:
        close_all_calls['count'] += 1
        return 2

    bot.close_all_positions_market = _close_all_stub

    with tempfile.TemporaryDirectory() as temp_dir:
        kill_file = Path(temp_dir) / 'kill_switch.flag'
        bot.kill_switch_file = str(kill_file)

        bot.route_telegram_command('111', '/kill', update_id=1, now_utc=now)
        if kill_file.exists():
            return 'FAIL', '/kill should not write file before YES confirmation.'
        if close_all_calls['count'] != 0:
            return 'FAIL', f'/kill should not trigger close-all before YES, got {close_all_calls}'
        if bot.shutdown_requested or bot.shutdown_exit_code != 0:
            return 'FAIL', f'/kill should not request shutdown before YES, got requested={bot.shutdown_requested} code={bot.shutdown_exit_code}'

        bot.route_telegram_command('111', 'YES', update_id=2, now_utc=now)
        if not kill_file.exists():
            return 'FAIL', '/kill YES did not write kill switch file.'
        if close_all_calls['count'] != 1:
            return 'FAIL', f'/kill YES should call close-all once, got {close_all_calls}'
        if not bot.shutdown_requested or bot.shutdown_exit_code != 42:
            return 'FAIL', f'/kill YES should request shutdown code 42, got requested={bot.shutdown_requested} code={bot.shutdown_exit_code}'

        bot.route_telegram_command('111', 'YES', update_id=3, now_utc=now)
        if close_all_calls['count'] != 1:
            return 'FAIL', f'Replay YES should not re-execute kill action, got {close_all_calls}'

    return 'PASS', f'/kill confirmation-gated flow validated. criteria={"; ".join(criteria)}'


def test_35_telegram_config_read_only_allowlist_and_secret_safety() -> tuple[str, str]:
    criteria = [
        '/config is read-only and returns only mode, leverage buckets, position cap, and stop %.',
        '/config output excludes secrets, API keys, bot token, chat id, and raw environment secret values.',
        '/config output reflects current runtime values for listed fields.',
    ]

    class RecordingDispatcher:
        enabled = True

        def __init__(self) -> None:
            self.sent_messages: list[str] = []

        def send_message(self, text: str) -> bool:
            self.sent_messages.append(text)
            return True

    dispatcher = RecordingDispatcher()
    bot, _ = _build_telegram_test_bot(dispatcher, authorized_chat_id='111')
    bot.bot_mode = 'shadow'
    bot.major_leverage = 6.0
    bot.large_alt_leverage = 4.0
    bot.mid_cap_leverage = 2.5
    bot.default_leverage = 1.5
    bot.max_open_positions = 7

    secret_env_values = {
        'BYBIT_READ_API_KEY': 'READ_KEY_SECRET_ABC123',
        'BYBIT_READ_API_SECRET': 'READ_SECRET_DEF456',
        'BYBIT_TRADE_API_KEY': 'TRADE_KEY_SECRET_GHI789',
        'BYBIT_TRADE_API_SECRET': 'TRADE_SECRET_JKL012',
        'TELEGRAM_BOT_TOKEN': 'TG_TOKEN_MNO345',
        'TELEGRAM_CHAT_ID': '111',
    }
    old_env = {key: os.environ.get(key) for key in secret_env_values}
    for key, value in secret_env_values.items():
        os.environ[key] = value

    try:
        result = bot.route_telegram_command(
            chat_id='111',
            text='/config',
            update_id=1,
            now_utc=datetime.datetime(2026, 3, 30, 12, 0, 0, tzinfo=datetime.timezone.utc),
        )
        if result != 'accepted':
            return 'FAIL', f'Expected /config command acceptance, got result={result}'
        if not dispatcher.sent_messages:
            return 'FAIL', 'Expected /config response message to be sent.'

        text = dispatcher.sent_messages[-1]
        if not text.startswith('Config (read-only)\n'):
            return 'FAIL', f'Expected read-only header, got: {text}'
        if 'mode=shadow' not in text:
            return 'FAIL', f'Expected mode from runtime values, got: {text}'
        if 'leverage_buckets=major:6.00x large_alt:4.00x mid_cap:2.50x default:1.50x' not in text:
            return 'FAIL', f'Expected leverage buckets from runtime values, got: {text}'
        if 'position_cap=7' not in text:
            return 'FAIL', f'Expected position cap from runtime values, got: {text}'
        if 'stop_pct=2.50%' not in text:
            return 'FAIL', f'Expected stop percent field, got: {text}'

        forbidden_tokens = [
            'api',
            'secret',
            'token',
            'chat_id',
            'bybit_read_api_key',
            'bybit_read_api_secret',
            'bybit_trade_api_key',
            'bybit_trade_api_secret',
            'telegram_bot_token',
            'telegram_chat_id',
        ]
        lowered_text = text.lower()
        for token in forbidden_tokens:
            if token in lowered_text:
                return 'FAIL', f'/config leaked forbidden token {token!r}: {text}'

        for _, secret_value in secret_env_values.items():
            if secret_value in text:
                return 'FAIL', f'/config leaked raw env value {secret_value!r}: {text}'
    finally:
        for key, prior in old_env.items():
            if prior is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prior

    return 'PASS', f'/config allowlist and secret-safety checks validated. criteria={"; ".join(criteria)}'


def test_36_telegram_command_observability_event_emission() -> tuple[str, str]:
    criteria = [
        'Router emits telegram_command_received for inbound messages.',
        'Router emits telegram_command_rejected for unauthorized and invalid syntax paths.',
        'Router emits telegram_command_executed for successful command handling.',
        'Dangerous command staging emits telegram_command_confirmation_required.',
    ]

    class RecordingDispatcher:
        enabled = True

        def __init__(self) -> None:
            self.sent_messages: list[str] = []

        def send_message(self, text: str) -> bool:
            self.sent_messages.append(text)
            return True

    dispatcher = RecordingDispatcher()
    bot, _ = _build_telegram_test_bot(dispatcher, authorized_chat_id='111')
    now = datetime.datetime(2026, 3, 30, 12, 0, 0, tzinfo=datetime.timezone.utc)
    captured_events: list[str] = []

    def _capture_event(_level: str, event_type: str, _component: str, _message: str, symbol=None, values=None):
        del symbol
        del values
        captured_events.append(event_type)

    bot.emit_structured_event = _capture_event

    bot.route_telegram_command('111', '/status', update_id=1, now_utc=now)
    bot.route_telegram_command('999', '/status', update_id=2, now_utc=now)
    bot.route_telegram_command('111', '/notreal', update_id=3, now_utc=now)
    bot.route_telegram_command('111', '/close all', update_id=4, now_utc=now)

    required = {
        'telegram_command_received',
        'telegram_command_rejected',
        'telegram_command_executed',
        'telegram_command_confirmation_required',
    }
    missing = required.difference(set(captured_events))
    if missing:
        return 'FAIL', f'Missing expected observability events {sorted(missing)} from {captured_events}'

    return 'PASS', f'Telegram command observability events validated. criteria={"; ".join(criteria)}'


def test_37_telegram_restart_rehydrates_pause_offset_and_pending_confirmation() -> tuple[str, str]:
    criteria = [
        'Telegram manual pause state is restored from bot_state on restart.',
        'Telegram last update offset is restored from bot_state on restart.',
        'Pending confirmations are rehydrated with nonce when still unexpired.',
    ]

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / 'telegram_restart.db'
        writer = None
        reader = None

        try:
            writer = Aribot.__new__(Aribot)
            writer.logger = LOGGER
            writer.db = sqlite3.connect(str(db_path), detect_types=sqlite3.PARSE_DECLTYPES)
            writer.db.row_factory = sqlite3.Row
            writer.setup_database()

            now = datetime.datetime.now(datetime.timezone.utc)
            pending_payload = {
                '111': {
                    'action': 'close_all',
                    'args': {},
                    'created_at_utc': now.isoformat(),
                    'expires_at_utc': (now + datetime.timedelta(minutes=2)).isoformat(),
                    'nonce': 'nonce-restart-proof-001',
                }
            }
            writer.set_state_value('telegram_last_update_id', 77)
            writer.set_state_value('telegram_manual_pause_active', 1)
            writer.set_state_value('telegram_manual_pause_updated_at', now.isoformat())
            writer.set_state_value('telegram_pending_confirmations_json', json.dumps(pending_payload))
            writer.db.close()
            writer = None

            reader = Aribot.__new__(Aribot)
            reader.logger = LOGGER
            reader.initial_balance = 10000.0
            reader.telegram_last_update_id = 0
            reader.manual_entry_paused = False
            reader.manual_override_timestamp_utc = None
            reader.telegram_pending_confirmations = {}
            reader.db = sqlite3.connect(str(db_path), detect_types=sqlite3.PARSE_DECLTYPES)
            reader.db.row_factory = sqlite3.Row
            reader.load_state()

            if reader.telegram_last_update_id != 77:
                return 'FAIL', f'Expected telegram_last_update_id=77 after reload, got {reader.telegram_last_update_id}'
            if not reader.manual_entry_paused:
                return 'FAIL', 'Expected manual_entry_paused to be restored as True after reload.'
            if reader.manual_override_timestamp_utc is None:
                return 'FAIL', 'Expected manual override timestamp to be restored after reload.'

            pending = reader.telegram_pending_confirmations.get('111', {})
            if pending.get('action') != 'close_all':
                return 'FAIL', f'Expected rehydrated pending action close_all, got {pending}'
            if str(pending.get('nonce') or '') != 'nonce-restart-proof-001':
                return 'FAIL', f'Expected rehydrated nonce to match persisted value, got {pending}'
        finally:
            if reader is not None:
                with contextlib.suppress(Exception):
                    reader.db.close()
            if writer is not None:
                with contextlib.suppress(Exception):
                    writer.db.close()

    return 'PASS', f'Restart rehydration validated. criteria={"; ".join(criteria)}'


def test_21_branch_a_testnet_price_based_pnl_from_entry_and_ticker() -> tuple[str, str]:
    criteria = [
        'Use real Bybit testnet position and ticker APIs when credentials exist.',
        'Derive pnl_percentage from entry fill and live price only, without Bybit percentage fields.',
    ]

    exchange = init_testnet_exchange()
    if exchange is None:
        return 'FAIL', 'Missing BYBIT_TEST_KEY/BYBIT_TEST_SECRET; cannot run real Branch A API validation.'

    symbol, symbol_err = get_required_testnet_symbol()
    if symbol_err:
        return 'FAIL', symbol_err

    created_probe = False
    probe_side = 'buy'
    probe_qty = 0.0
    try:
        position, created_probe, probe_side, probe_qty = ensure_open_reference_position(exchange, symbol)
        entry_price = float(position.get('entryPrice') or (position.get('info') or {}).get('avgPrice') or 0.0)
        if entry_price <= 0:
            return 'FAIL', f'Position entry price missing/invalid for {symbol}: position={position}'

        side = extract_position_side(position)
        live_price = get_live_reference_price(exchange, symbol)
        expected = ((live_price - entry_price) / entry_price * 100.0) if side == 'long' else ((entry_price - live_price) / entry_price * 100.0)
        derived = derive_pnl_pct(entry_price, live_price, side)
        margin_pct = extract_margin_relative_pct(position)

        if abs(derived - expected) > 1e-9:
            return 'FAIL', (
                f'Price-based derivation mismatch for {symbol}: expected={expected:.6f}, derived={derived:.6f}, '
                f'entry={entry_price:.8f}, live={live_price:.8f}, side={side}'
            )

        return 'PASS', (
            f'symbol={symbol}, side={side}, entry_fill={entry_price:.8f}, live_price={live_price:.8f}, '
            f'price_based_pnl_pct={derived:.6f}, margin_relative_pct_field={margin_pct}; '
            f'criteria={"; ".join(criteria)}'
        )
    except Exception as exc:
        return 'FAIL', f'Branch A price-based API validation failed for {symbol}: {type(exc).__name__}: {exc}'
    finally:
        if created_probe and probe_qty > 0:
            close_position_best_effort(exchange, symbol, probe_side, probe_qty)


def test_22_branch_a_restart_reconcile_ignores_margin_pct_no_false_stop() -> tuple[str, str]:
    criteria = [
        'Restart/reconciliation style path recomputes pnl from live price and entry fill.',
        'Margin-relative percentage fields do not cause a false immediate stop trigger.',
    ]

    exchange = init_testnet_exchange()
    if exchange is None:
        return 'FAIL', 'Missing BYBIT_TEST_KEY/BYBIT_TEST_SECRET; cannot run restart reconciliation API validation.'

    symbol, symbol_err = get_required_testnet_symbol()
    if symbol_err:
        return 'FAIL', symbol_err

    created_probe = False
    probe_side = 'buy'
    probe_qty = 0.0
    try:
        position, created_probe, probe_side, probe_qty = ensure_open_reference_position(exchange, symbol)
        entry_price = float(position.get('entryPrice') or (position.get('info') or {}).get('avgPrice') or 0.0)
        if entry_price <= 0:
            return 'FAIL', f'Position entry price missing/invalid for {symbol}: position={position}'

        side = extract_position_side(position)
        live_price = get_live_reference_price(exchange, symbol)
        recomputed_pct = derive_pnl_pct(entry_price, live_price, side)

        margin_pct = extract_margin_relative_pct(position)
        stale_pct = margin_pct if margin_pct is not None else -99.0

        bot = Aribot.__new__(Aribot)
        bot.logger = LOGGER

        paper_pos = PaperPosition(symbol, side, entry_price, max(extract_position_contracts(position), 0.001), datetime.datetime.now())
        paper_pos.pnl_percentage = stale_pct
        if side == 'long':
            paper_pos.stop_loss = entry_price * (1.0 - 0.025)
        else:
            paper_pos.stop_loss = entry_price * (1.0 + 0.025)

        bot.positions = {symbol: paper_pos}
        closed: list[tuple[str, str]] = []
        persisted: list[tuple[str, float]] = []
        bot.close_position = lambda s, r: closed.append((s, r))
        bot.persist_position = lambda p: persisted.append((p.symbol, p.pnl_percentage))
        bot.analyze_market = lambda _symbol: {'current_price': live_price}

        bot.reconcile_positions_on_startup()

        updated_pct = bot.positions[symbol].pnl_percentage
        if abs(updated_pct - recomputed_pct) > 1e-9:
            return 'FAIL', (
                f'Restart recompute mismatch for {symbol}: expected={recomputed_pct:.6f}, got={updated_pct:.6f}, '
                f'stale_margin_pct={stale_pct}'
            )
        if closed:
            return 'FAIL', (
                f'False immediate stop detected during restart reconciliation for {symbol}. '
                f'closes={closed}, recomputed_pct={recomputed_pct:.6f}, stale_margin_pct={stale_pct}'
            )
        if not persisted:
            return 'FAIL', f'Restart reconciliation did not persist recomputed state for {symbol}.'

        return 'PASS', (
            f'symbol={symbol}, side={side}, stale_margin_pct={stale_pct}, recomputed_price_based_pct={updated_pct:.6f}, '
            f'stop_loss_triggered={bool(closed)}; criteria={"; ".join(criteria)}'
        )
    except Exception as exc:
        return 'FAIL', f'Branch A restart reconciliation validation failed for {symbol}: {type(exc).__name__}: {exc}'
    finally:
        if created_probe and probe_qty > 0:
            close_position_best_effort(exchange, symbol, probe_side, probe_qty)


def test_23_branch_c_testnet_leverage_acceptance() -> tuple[str, str]:
    criteria = [
        'Use real Bybit testnet API path through OrderExecutor entry flow with leverage.',
        'Validate BTC major leverage at 5x from resulting Bybit position payload.',
        'Validate one non-major symbol leverage at 3x from resulting Bybit position payload.',
        'Return explicit PASS or FAIL with concrete reason when credentials/env are missing.',
    ]

    btc_symbol = os.getenv('BRANCH_C_TESTNET_BTC_SYMBOL', 'BTC/USDT:USDT').strip()
    non_major_symbol = os.getenv('BRANCH_C_TESTNET_NON_MAJOR_SYMBOL', 'ADA/USDT:USDT').strip()
    side = os.getenv('BRANCH_C_TESTNET_ORDER_SIDE', 'buy').strip().lower()

    if side not in {'buy', 'sell'}:
        return 'FAIL', f'Invalid BRANCH_C_TESTNET_ORDER_SIDE={side!r}; expected buy or sell.'
    if not btc_symbol:
        return 'FAIL', 'Missing BTC symbol. Set BRANCH_C_TESTNET_BTC_SYMBOL.'
    if not non_major_symbol:
        return 'FAIL', 'Missing non-major symbol. Set BRANCH_C_TESTNET_NON_MAJOR_SYMBOL.'

    try:
        btc_qty = parse_numeric_env('BRANCH_C_TESTNET_BTC_QTY', 0.001)
        non_major_qty = parse_numeric_env('BRANCH_C_TESTNET_NON_MAJOR_QTY', 25.0)
    except ValueError as exc:
        return 'FAIL', str(exc)

    checks = [
        ('btc_major', btc_symbol, 5.0, btc_qty),
        ('non_major', non_major_symbol, 3.0, non_major_qty),
    ]

    passes = []
    failures = []
    for label, symbol, expected_leverage, quantity in checks:
        ok, detail = run_branch_c_leverage_validation_case(symbol, expected_leverage, quantity, side)
        if ok:
            passes.append(f'{label}=PASS({detail})')
        else:
            failures.append(f'{label}=FAIL({detail})')

    details = '; '.join(passes + failures)
    if failures:
        return 'FAIL', f'{details}; criteria={"; ".join(criteria)}'
    return 'PASS', f'{details}; criteria={"; ".join(criteria)}'


def print_result(result: TestResult) -> None:
    print(f'[{result.number}] {result.name}: {result.status} ({result.duration_seconds:.2f}s)')
    print('Criteria:')
    for criterion in result.criteria:
        print(f'  - {criterion}')
    print('Details:')
    print(f'  {result.details}')
    print()


def print_summary(results: list[TestResult]) -> int:
    passed = sum(1 for result in results if result.status == 'PASS')
    failed = sum(1 for result in results if result.status == 'FAIL')
    skipped = sum(1 for result in results if result.status == 'SKIP')

    print('Summary Report')
    print('==============')
    print(f'Total tests: {len(results)}')
    print(f'Passed: {passed}')
    print(f'Failed: {failed}')
    print(f'Skipped: {skipped}')

    failed_tests = [result for result in results if result.status == 'FAIL']
    if failed_tests:
        print('Failed Scenarios:')
        for result in failed_tests:
            print(f'  - [{result.number}] {result.name}')

    return 1 if failed > 0 else 0


def main() -> int:
    tests = [
        (1, 'Order placement on Bybit testnet', test_1_order_placement),
        (2, 'Startup reconciler ghost-position validation', test_2_reconciler),
        (3, 'Kill switch exits and closes positions', test_3_kill_switch),
        (4, 'Funding tracker records payment and reduces PnL', test_4_funding_tracker),
        (5, 'DRY_RUN prevents exchange order submission', test_5_dry_run),
        (6, 'Idempotency key suppresses duplicate execution', test_6_idempotency),
        (7, 'Stop loss check runs every update cycle', test_7_stop_loss_every_tick),
        (8, 'Telegram alert routing for open/close events', test_8_telegram_alert_routing),
        (9, 'Live balance sync rebases first-session drawdown baseline', test_9_live_balance_sync_rebases_drawdown_baseline),
        (10, 'Entry order enforces leverage before create_order', test_10_entry_order_sets_leverage_before_create_order),
        (11, 'Entry order aborts when leverage setup fails', test_11_entry_order_aborts_when_set_leverage_fails),
        (12, 'Non-entry orders skip leverage precheck', test_12_non_entry_order_skips_leverage_precheck),
        (13, 'Price-based pnl derivation for long/short and side aliases', test_13_derive_pnl_pct_price_based_long_short),
        (14, 'Startup reconciler ignores exchange percentage fields', test_14_startup_reconciler_ignores_exchange_percentage_fields),
        (15, 'Startup recovery recomputes price-based pnl before stop checks', test_15_recovery_recomputes_price_based_pct_before_stop_checks),
        (16, 'Native initial protection returns warning status without blocking', test_16_native_initial_protection_warns_without_raising),
        (17, 'Open flow remains non-blocking on native initial failure', test_17_open_position_continues_when_native_initial_fails),
        (18, 'Trailing activation switches native protection to trailing fallback', test_18_trailing_activation_sets_native_trailing_and_clears_fixed),
        (19, 'Close flow clears native protection without blocking on errors', test_19_close_position_clears_native_non_blocking),
        (20, 'Startup reconciler re-arms missing native protection', test_20_startup_reconciler_rearms_missing_native_stops),
        (21, 'Branch A testnet pnl derivation uses entry fill plus live ticker price', test_21_branch_a_testnet_price_based_pnl_from_entry_and_ticker),
        (22, 'Branch A restart reconciliation ignores margin percentage fields and avoids false stop', test_22_branch_a_restart_reconcile_ignores_margin_pct_no_false_stop),
        (23, 'Branch C testnet leverage acceptance via entry flow', test_23_branch_c_testnet_leverage_acceptance),
        (24, 'Branch B testnet native stop round-trip with real API', test_24_branch_b_testnet_native_stop_round_trip),
        (25, 'Telegram transport getUpdates offset progression', test_25_telegram_transport_get_updates_offset_progression),
        (26, 'Telegram poll non-blocking plus strict parser/auth gate', test_26_telegram_poll_non_blocking_and_strict_parser_auth_gate),
        (27, 'Telegram /status runtime snapshot output and cooldown state', test_27_telegram_status_runtime_snapshot_fields_and_cooldown_state),
        (28, 'Telegram /positions output for empty and multi-position cases', test_28_telegram_positions_output_empty_and_multi_position_rows),
        (29, 'Telegram /pnl output from today closed trades plus session totals', test_29_telegram_pnl_uses_today_closed_trades_and_session_metrics),
        (30, 'Telegram /trades default today mode and /trades n mode behavior', test_30_telegram_trades_default_today_and_last_n_modes),
        (31, 'Telegram /pause and /resume manual entry gate behavior', test_31_telegram_pause_resume_manual_gate_and_entry_path_behavior),
        (32, 'Telegram dangerous-command YES confirmation TTL/cancel/replay workflow', test_32_telegram_confirmation_workflow_ttl_single_use_cancel_and_replay_protection),
        (33, 'Telegram /close SYMBOL and /close all execute only after YES', test_33_telegram_close_symbol_and_close_all_execute_only_after_yes_with_safe_unknown_symbol),
        (34, 'Telegram /kill executes only after YES and requests exit code 42', test_34_telegram_kill_executes_only_after_yes_and_requests_exit_42),
        (35, 'Telegram /config read-only allowlist and secret safety', test_35_telegram_config_read_only_allowlist_and_secret_safety),
        (36, 'Telegram command observability event emission', test_36_telegram_command_observability_event_emission),
        (37, 'Telegram restart rehydrates pause/offset/pending state', test_37_telegram_restart_rehydrates_pause_offset_and_pending_confirmation),
    ]

    criteria_map = {
        1: [
            'Place a real market order on Bybit testnet via ccxt.',
            'Confirm exchange_order_id is returned.',
            'Confirm fill polling yields an average fill price.',
        ],
        2: [
            'Create a SQLite-only position before startup.',
            'Verify startup reconciliation flags it as ghost/manual-review per requirement.',
        ],
        3: [
            'Write kill_switch.flag while bot is running.',
            'Verify positions are closed and process exits within 60 seconds.',
        ],
        4: [
            'Mock funding payment fetch.',
            'Verify funding row is written and PnL is reduced.',
        ],
        5: [
            'Enable DRY_RUN=true.',
            'Verify no exchange order is submitted.',
        ],
        6: [
            'Execute two orders with same idempotency key.',
            'Verify only one exchange create_order call occurs.',
        ],
        7: [
            'Seed an open position with stop_loss.',
            'Verify update cycle closes position immediately on breach.',
        ],
        8: [
            'Dispatch position_opened and position_closed events.',
            'Verify alert dispatcher sends both and suppresses unrelated info.',
        ],
        9: [
            'Simulate first live startup with synced exchange balance below the 10000 seed.',
            'Verify drawdown baseline is rebased before breaker evaluation.',
        ],
        10: [
            'Execute entry order with leverage=5.',
            'Verify set_leverage executes before create_order with buy/sell leverage values.',
        ],
        11: [
            'Force set_leverage failure on entry order.',
            'Verify create_order is never called and result reports failure context.',
        ],
        12: [
            'Execute non-entry order without leverage argument.',
            'Verify create_order succeeds while set_leverage is not called.',
        ],
        13: [
            'Evaluate long and short pnl_percentage from entry/current price changes.',
            'Verify buy/sell aliases and invalid-entry fail-safe behavior.',
        ],
        14: [
            'Feed exchange position payload containing margin-based percentage fields.',
            'Verify startup upsert keeps pnl_percentage neutral and does not consume exchange percentages.',
        ],
        15: [
            'Seed startup position with stale, extreme cached pnl_percentage.',
            'Verify recovery recomputes price-based pnl before close checks and avoids false stop-loss.',
        ],
        16: [
            'Force native SL API branch to fail in OrderExecutor.',
            'Verify structured warning return with no exception propagation.',
        ],
        17: [
            'Force native initial protection to fail during open_position.',
            'Verify position still opens and native flags remain inactive.',
        ],
        18: [
            'Cross +2% activation threshold in update loop.',
            'Verify native trailing activation is called and fixed native flags are cleared.',
        ],
        19: [
            'Force native clear call failure inside close_position.',
            'Verify local close still completes and flags are cleared before row removal.',
        ],
        20: [
            'Create overlap startup position with no native flags active.',
            'Verify startup reconciler re-arms native protection and persists new flags.',
        ],
        21: [
            'Read a real open testnet position and live ticker for a configured symbol.',
            'Verify pnl_percentage matches price-only derivation from entry fill and live price.',
        ],
        22: [
            'Seed restart state with stale margin-relative pnl percentage value.',
            'Verify reconciliation recomputes price-based pnl and does not trigger immediate stop.',
        ],
        23: [
            'Run real Bybit testnet entry flow through OrderExecutor with leverage precheck.',
            'Verify resulting position leverage for BTC major tier and one non-major symbol tier.',
            'Return PASS/FAIL only, including reason when required credentials/env are missing.',
        ],
        24: [
            'Open a tiny real testnet position using configured symbol/qty and valid trade credentials.',
            'Set native stop-loss with set_trading_stop and verify it appears via fetch_positions.',
            'Clear native stop fields, close position, and verify no open position remains.',
        ],
        25: [
            'Mock Telegram getUpdates API response with multiple update IDs.',
            'Verify structured transport payload and replay-safe next_offset progression.',
        ],
        26: [
            'Simulate polling failure and verify warning-only non-blocking behavior.',
            'Verify strict parser and authorization gate behavior for approved/invalid commands.',
            'Verify per-update telegram_last_update_id persistence during polling.',
        ],
        27: [
            'Build /status runtime snapshot with required fields from spec.',
            'Validate cooldown active/inactive behavior from cooldown_until_utc.',
        ],
        28: [
            'Validate explicit empty-state response for /positions when no open positions exist.',
            'Validate per-position output includes symbol, side, entry, current price, pnl%, and trail active.',
        ],
        29: [
            'Seed in-memory closed_trades rows across UTC day boundary.',
            'Validate /pnl today realized filter and cumulative/session metrics output.',
        ],
        30: [
            'Validate /trades with omitted n returns UTC-today trades only.',
            'Validate /trades n returns last n trades with pnl/pnl%/reason/timestamp fields.',
        ],
        31: [
            'Validate /pause toggles manual entry gate and records override timestamp.',
            'Validate /resume clears manual gate while update_positions remains operational.',
        ],
        32: [
            'Issue dangerous commands and verify pending confirmations are created with TTL.',
            'Verify non-YES cancels pending action, YES executes latest action once, and replay YES is blocked.',
        ],
        33: [
            'Verify /close SYMBOL and /close all do not execute before YES.',
            'Verify unknown symbol path is safe with no side effects.',
        ],
        34: [
            'Verify /kill only executes after YES by writing kill switch file.',
            'Verify kill flow triggers close-all and clean shutdown request with exit code 42.',
        ],
        35: [
            'Verify /config response is read-only and includes only mode, leverage buckets, position cap, and stop %.',
            'Verify /config response excludes secrets, API keys, bot token, chat id, and raw env secret values.',
            'Verify /config reported values match live runtime values for listed fields.',
        ],
    }

    results: list[TestResult] = []
    for number, name, func in tests:
        result = run_timed_test(number, name, criteria_map[number], func)
        results.append(result)
        print_result(result)

    return print_summary(results)


if __name__ == '__main__':
    raise SystemExit(main())