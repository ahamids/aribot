#!/usr/bin/env python3
"""
Lightweight verification harness for Aribot.

This script runs deterministic checks for core control logic and can also assert
that expected runtime log markers exist in a log file.
"""

import argparse
import datetime
import sys
import json
import tempfile
import importlib
from pathlib import Path

PaperPosition = None
AribotClass = None
QUOTE_CCY = None


def configure_market_context(market):
    global PaperPosition, AribotClass, QUOTE_CCY

    market_lc = market.lower()
    if market_lc == "usdt":
        module_name = "usdt_paper_bot_v2"
        QUOTE_CCY = "USDT"
    elif market_lc == "usdc":
        module_name = "usdc_paper_bot_v2"
        QUOTE_CCY = "USDC"
    else:
        raise ValueError(f"Unsupported market: {market}")

    module = importlib.import_module(module_name)
    PaperPosition = getattr(module, "PaperPosition")
    AribotClass = getattr(module, "Aribot", getattr(module, "PaperTradingBotV2"))


def contract_symbol(base):
    return f"{base}/{QUOTE_CCY}:{QUOTE_CCY}"


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def approx_equal(a, b, tolerance=1e-9):
    return abs(a - b) <= tolerance


def build_bot_stub():
    bot = AribotClass.__new__(AribotClass)

    class _NoopLogger:
        def info(self, *_args, **_kwargs):
            return None

        def warning(self, *_args, **_kwargs):
            return None

    class _NoopStructuredLogger:
        def emit(self, *_args, **_kwargs):
            return None

    class _NoopAlertDispatcher:
        def dispatch_event(self, *_args, **_kwargs):
            return None

    bot.logger = _NoopLogger()
    bot.structured_logger = _NoopStructuredLogger()
    bot.alert_dispatcher = _NoopAlertDispatcher()
    bot.signal_boundary_window_seconds = 60
    bot.max_tick_age_seconds = 600
    bot.allow_missing_ticker_timestamp = True
    bot.max_unchanged_tick_cycles = 2
    bot.daily_drawdown_limit = -0.05
    bot.cooldown_until_utc = None
    bot.current_utc_day = datetime.datetime.now(datetime.timezone.utc).date()
    bot.session_start_balance = 10_000.0
    bot.current_balance = 10_000.0
    bot.daily_drawdown_paused = False
    bot.major_leverage = 5.0
    bot.large_alt_leverage = 3.0
    bot.mid_cap_leverage = 2.0
    bot.default_leverage = 1.0
    bot.major_coins = {'BTC', 'ETH'}
    bot.large_alt_coins = {
        'SOL', 'BNB', 'DOT', 'AVAX', 'XRP', 'ADA', 'LINK', 'MATIC', 'LTC', 'ATOM', 'NEAR'
    }
    bot.mid_cap_coins = {
        'ENA', 'INJ', 'OP', 'SEI', 'ARB', 'APT', 'SUI', 'TIA', 'WLD', 'JUP'
    }
    bot.markets = {}
    return bot


def test_signal_window():
    bot = build_bot_stub()
    t1 = datetime.datetime(2026, 1, 1, 0, 0, 30, tzinfo=datetime.timezone.utc)
    t2 = datetime.datetime(2026, 1, 1, 0, 1, 0, tzinfo=datetime.timezone.utc)
    t3 = datetime.datetime(2026, 1, 1, 1, 0, 30, tzinfo=datetime.timezone.utc)

    assert_true(bot.is_signal_window(t1), "Signal window should be active at 4H boundary")
    assert_true(not bot.is_signal_window(t2), "Signal window should be inactive after first minute")
    assert_true(not bot.is_signal_window(t3), "Signal window should be inactive on non-4H hour")


def test_atr_calculation():
    bot = build_bot_stub()
    # Build simple OHLCV where TR remains 10 for each candle after the first.
    ohlcv = []
    base_ts = 1_700_000_000_000
    for i in range(20):
        ts = base_ts + i * 14_400_000
        open_p = 100 + i
        high = open_p + 5
        low = open_p - 5
        close = open_p
        volume = 1000
        ohlcv.append([ts, open_p, high, low, close, volume])

    atr = bot.calculate_atr(ohlcv, period=14)
    assert_true(atr is not None, "ATR should not be None for valid OHLCV input")
    assert_true(approx_equal(atr, 10.0), f"Expected ATR 10.0, got {atr}")


def test_fee_adjusted_pnl():
    pos = PaperPosition(contract_symbol("TEST"), "long", 100.0, 1.0, datetime.datetime.now())
    pos.round_trip_fee_rate = 0.0011
    pos.update_price(110.0)

    expected_gross = 10.0
    expected_fees = ((100.0 + 110.0) / 2.0) * 1.0 * 0.0011
    expected_net = expected_gross - expected_fees

    assert_true(approx_equal(pos.gross_pnl, expected_gross), "Gross PnL mismatch")
    assert_true(approx_equal(pos.fee_cost, expected_fees), "Fee model mismatch")
    assert_true(approx_equal(pos.pnl, expected_net), "Net PnL mismatch")


def test_time_exit_threshold():
    old_ts = datetime.datetime.now() - datetime.timedelta(hours=41)
    pos = PaperPosition(contract_symbol("TEST"), "long", 100.0, 1.0, old_ts)
    assert_true(pos.should_close_for_time(40 * 60), "Position older than 40h should time-exit")


def test_daily_drawdown_breaker():
    bot = build_bot_stub()
    bot.current_balance = 9_499.0  # -5.01%
    bot.update_daily_drawdown_pause()
    assert_true(bot.daily_drawdown_paused, "Daily drawdown breaker should trigger below -5%")


def test_loss_cooldown_gate():
    bot = build_bot_stub()
    bot.cooldown_until_utc = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
    assert_true(bot.in_loss_cooldown(), "Cooldown should be active before expiry")


def test_leverage_tiers():
    bot = build_bot_stub()
    bot.markets = {
        contract_symbol('BTC'): {'base': 'BTC'},
        contract_symbol('SOL'): {'base': 'SOL'},
        contract_symbol('OP'): {'base': 'OP'},
        contract_symbol('RANDOM'): {'base': 'RANDOM'},
    }

    lev_btc, tier_btc = bot.get_leverage_for_symbol(contract_symbol('BTC'))
    lev_sol, tier_sol = bot.get_leverage_for_symbol(contract_symbol('SOL'))
    lev_op, tier_op = bot.get_leverage_for_symbol(contract_symbol('OP'))
    lev_other, tier_other = bot.get_leverage_for_symbol(contract_symbol('RANDOM'))

    assert_true(lev_btc == 5.0 and tier_btc == 'major', 'BTC should map to 5x major tier')
    assert_true(lev_sol == 3.0 and tier_sol == 'large_alt', 'SOL should map to 3x large-alt tier')
    assert_true(lev_op == 2.0 and tier_op == 'mid_cap', 'OP should map to 2x mid-cap tier')
    assert_true(lev_other == 1.0 and tier_other == 'default', 'Unknown symbol should map to 1x default tier')


def test_leverage_config_loading():
    bot = build_bot_stub()
    with tempfile.TemporaryDirectory() as temp_dir:
        cfg_path = Path(temp_dir) / 'leverage_buckets.json'
        cfg_path.write_text(
            json.dumps(
                {
                    'major': {'leverage': 7, 'symbols': ['BTC']},
                    'large_alt': {'leverage': 4, 'symbols': ['SOL']},
                    'mid_cap': {'leverage': 2.5, 'symbols': ['OP']},
                    'default_leverage': 1.2,
                }
            ),
            encoding='utf-8',
        )

        bot.leverage_config_file = str(cfg_path)
        bot.load_leverage_config()
        bot.markets = {
            contract_symbol('BTC'): {'base': 'BTC'},
            contract_symbol('SOL'): {'base': 'SOL'},
            contract_symbol('OP'): {'base': 'OP'},
            contract_symbol('DOGE'): {'base': 'DOGE'},
        }

        lev_btc, _ = bot.get_leverage_for_symbol(contract_symbol('BTC'))
        lev_sol, _ = bot.get_leverage_for_symbol(contract_symbol('SOL'))
        lev_op, _ = bot.get_leverage_for_symbol(contract_symbol('OP'))
        lev_doge, _ = bot.get_leverage_for_symbol(contract_symbol('DOGE'))

        assert_true(lev_btc == 7.0, 'Config major leverage should be loaded')
        assert_true(lev_sol == 4.0, 'Config large-alt leverage should be loaded')
        assert_true(lev_op == 2.5, 'Config mid-cap leverage should be loaded')
        assert_true(lev_doge == 1.2, 'Config default leverage should be loaded')


def test_ticker_timestamp_extraction_fallbacks():
    bot = build_bot_stub()
    now_utc = datetime.datetime(2026, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)

    ts1, src1, fb1 = bot.extract_ticker_timestamp_ms({'timestamp': 1704067200000}, now_utc)
    assert_true(ts1 == 1704067200000 and src1 == 'ticker.timestamp' and not fb1, 'timestamp should be primary source')

    ts2, src2, fb2 = bot.extract_ticker_timestamp_ms({'timestamp': None, 'datetime': '2026-01-01T00:00:00Z'}, now_utc)
    assert_true(src2 == 'ticker.datetime' and not fb2, 'datetime should be secondary source')

    ts3, src3, fb3 = bot.extract_ticker_timestamp_ms({'timestamp': None, 'datetime': None, 'info': {'updatedTime': '1704067200000'}}, now_utc)
    assert_true(src3 == 'ticker.info.updatedTime' and not fb3, 'info field should be tertiary source')

    ts4, src4, fb4 = bot.extract_ticker_timestamp_ms({'timestamp': None, 'datetime': None, 'info': {}}, now_utc)
    assert_true(src4 == 'local_fallback' and fb4 and ts4 == int(now_utc.timestamp() * 1000), 'local fallback should be used when exchange time is missing')


REQUIRED_LOG_PATTERNS = [
    "Starting paper_bot_v2",
    "Cycle",
]

RECOMMENDED_LOG_PATTERNS = [
    "4H close window active",
    "BTC regime gate active",
    "Daily drawdown pause active",
    "Loss cooldown active",
    "time_exit",
    "Consecutive-loss cooldown active",
    "Position cap reached",
    "filtered by volume",
]


def assert_log_patterns(log_path, strict=False):
    if not log_path.exists():
        return {
            "found_required": [],
            "missing_required": REQUIRED_LOG_PATTERNS[:],
            "found_recommended": [],
            "missing_recommended": RECOMMENDED_LOG_PATTERNS[:],
            "skipped": True,
        }

    content = log_path.read_text(encoding="utf-8", errors="replace")
    lower = content.lower()

    found_required = [p for p in REQUIRED_LOG_PATTERNS if p.lower() in lower]
    missing_required = [p for p in REQUIRED_LOG_PATTERNS if p.lower() not in lower]

    found_recommended = [p for p in RECOMMENDED_LOG_PATTERNS if p.lower() in lower]
    missing_recommended = [p for p in RECOMMENDED_LOG_PATTERNS if p.lower() not in lower]

    if strict and missing_required:
        raise AssertionError(
            "Strict log assertion failed. Missing required patterns: "
            + ", ".join(missing_required)
        )

    return {
        "found_required": found_required,
        "missing_required": missing_required,
        "found_recommended": found_recommended,
        "missing_recommended": missing_recommended,
        "skipped": False,
    }


def run_logic_tests():
    tests = [
        test_signal_window,
        test_atr_calculation,
        test_fee_adjusted_pnl,
        test_time_exit_threshold,
        test_daily_drawdown_breaker,
        test_loss_cooldown_gate,
        test_leverage_tiers,
        test_leverage_config_loading,
        test_ticker_timestamp_extraction_fallbacks,
    ]

    passed = 0
    for test in tests:
        test()
        passed += 1

    return passed, len(tests)


def main():
    parser = argparse.ArgumentParser(description="Verify Aribot core logic and log markers")
    parser.add_argument(
        "--market",
        choices=["usdt", "usdc"],
        default="usdt",
        help="Target market bot module to verify",
    )
    parser.add_argument("--log", default=None, help="Path to log file")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail if required log patterns are missing",
    )
    args = parser.parse_args()

    configure_market_context(args.market)
    log_path = args.log or f"{args.market}_paper_trading_log.txt"

    try:
        passed, total = run_logic_tests()
        print(f"Logic tests: {passed}/{total} passed")

        log_report = assert_log_patterns(Path(log_path), strict=args.strict)
        if log_report["skipped"]:
            print(f"Log assertions: skipped (log file not found: {log_path})")
        else:
            print(
                "Log assertions: required found="
                f"{len(log_report['found_required'])}/{len(REQUIRED_LOG_PATTERNS)}, "
                "recommended found="
                f"{len(log_report['found_recommended'])}/{len(RECOMMENDED_LOG_PATTERNS)}"
            )
            if log_report["missing_required"]:
                print("Missing required patterns: " + ", ".join(log_report["missing_required"]))
            if log_report["missing_recommended"]:
                print("Missing recommended patterns: " + ", ".join(log_report["missing_recommended"]))

        print("Verification completed successfully")
        return 0
    except AssertionError as exc:
        print(f"Verification failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
