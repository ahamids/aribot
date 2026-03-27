#!/usr/bin/env python3
"""Validation suite for the live bot testnet workflow."""

from __future__ import annotations

import contextlib
import dataclasses
import datetime
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

from alert_dispatcher import AlertDispatcher
from observability import FundingTracker
from order_executor import OrderExecutor
from startup_reconciler import StartupReconciler
from usdt_paper_bot_v2 import PaperPosition, PaperTradingBotV2


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


def init_testnet_exchange() -> Optional[ccxt.bybit]:
    api_key = os.getenv('BYBIT_TRADE_API_KEY', '').strip()
    api_secret = os.getenv('BYBIT_TRADE_API_SECRET', '').strip()
    if not api_key or not api_secret:
        return None

    exchange = ccxt.bybit({
        'apiKey': api_key,
        'secret': api_secret,
        'enableRateLimit': True,
        'options': {'defaultType': 'future'},
    })
    exchange.set_sandbox_mode(True)
    return exchange


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
        last_order = exchange.fetch_order(order_id, symbol)
        status = str(last_order.get('status', '')).lower()
        if status == 'closed':
            return last_order
        time.sleep(2)
    raise TimeoutError(f'Order {order_id} did not close within {timeout_seconds}s; last_order={last_order}')


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
                partial_exits_json TEXT DEFAULT '[]'
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
                partial_exits_json
            ) VALUES (?, ?, ?, ?, ?, NULL, NULL, 0, 0, ?, 0, 0, '[]')
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


def test_1_order_placement() -> tuple[str, str]:
    criteria = [
        'A real market order is placed on Bybit testnet via ccxt.',
        'An exchange_order_id is returned.',
        'Fill polling reaches closed state and average fill price is computed from trades.',
    ]

    exchange = init_testnet_exchange()
    if exchange is None:
        return 'SKIP', 'Missing BYBIT_TRADE_API_KEY/BYBIT_TRADE_API_SECRET for testnet order placement.'

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
        db_path = workdir / 'usdt_paper_bot_v2.db'
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

        log_path = workdir / 'usdt_paper_trading_log.txt'
        deadline = time.time() + 45
        while time.time() < deadline:
            if log_path.exists() and 'Cycle 1' in log_path.read_text(encoding='utf-8', errors='replace'):
                break
            if process.poll() is not None:
                return 'FAIL', f'Bot exited before kill-switch trigger. exit_code={process.returncode}'
            time.sleep(1)
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

    bot = PaperTradingBotV2.__new__(PaperTradingBotV2)
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
    }

    results: list[TestResult] = []
    for number, name, func in tests:
        result = run_timed_test(number, name, criteria_map[number], func)
        results.append(result)
        print_result(result)

    return print_summary(results)


if __name__ == '__main__':
    raise SystemExit(main())