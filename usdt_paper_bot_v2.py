#!/usr/bin/env python3
"""
Paper Trading Bot v2 - USDT Swap Markets WMA Analysis
Based on 45-period Weighted Moving Average using (O+H+L+C)/4 as source with offset 2
Runs in a loop, analyzes signals every 5 minutes, manages paper positions with advanced position management.
"""

import ccxt
import argparse
import contextlib
import sqlite3
import time
import datetime
import logging
import json
import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

from alert_dispatcher import AlertDispatcher
from emoji_mode import EmojiLogFilter, SafeStreamHandler, normalize_emoji_mode, parse_emoji_mode_args
from observability import FundingTracker, KillSwitchMonitor, StructuredEventLogger
from order_executor import OrderExecutor
from secret_loader import BotSecrets, SecretLoader, SecretValidationError
from startup_reconciler import StartupReconciler


def normalize_symbol_focus_entries(symbols):
    normalized = set()
    if symbols is None:
        return normalized

    if isinstance(symbols, str):
        symbols = [symbols]

    for symbol in symbols:
        if not isinstance(symbol, str):
            continue
        candidate = symbol.strip().upper()
        if candidate:
            normalized.add(candidate)
    return normalized


def parse_symbol_focus_csv(raw_value):
    if raw_value is None:
        return []

    values = []
    for token in str(raw_value).split(','):
        candidate = token.strip()
        if candidate:
            values.append(candidate)
    return values


def get_base_asset_from_market_symbol(symbol):
    symbol_head = str(symbol or '').split(':')[0]
    if '/' in symbol_head:
        return symbol_head.split('/')[0].upper()
    return symbol_head.upper()


def filter_symbols_by_allowlist(available_symbols, requested_symbols):
    requested = normalize_symbol_focus_entries(requested_symbols)
    if not requested:
        return sorted(available_symbols), set()

    filtered = []
    matched = set()
    for symbol in available_symbols:
        normalized_symbol = str(symbol).strip().upper()
        base_asset = get_base_asset_from_market_symbol(symbol)
        if normalized_symbol in requested or base_asset in requested:
            filtered.append(symbol)
            if normalized_symbol in requested:
                matched.add(normalized_symbol)
            if base_asset in requested:
                matched.add(base_asset)

    return sorted(filtered), requested - matched


def load_symbol_focus_file(file_path):
    path = Path(file_path)
    with path.open('r', encoding='utf-8') as handle:
        payload = json.load(handle)

    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict) and isinstance(payload.get('symbols'), list):
        return payload['symbols']

    raise ValueError('Symbol focus JSON must be either a top-level list or an object containing a symbols list')


def parse_runtime_args(argv=None):
    parser = argparse.ArgumentParser(
        description='Run Aribot with optional symbol focus controls.',
    )
    parser.add_argument(
        '--symbols',
        help='Comma-separated base assets or full market symbols to trade, e.g. BTC,ETH,SOL or BTC/USDT:USDT',
    )
    parser.add_argument(
        '--symbols-file',
        help='Path to a JSON file containing either a symbol list or an object with a symbols list',
    )
    parser.add_argument(
        '--user-id',
        default=os.getenv('ARIBOT_USER_ID'),
        help=(
            'Multi-tenant: Supabase UUID for this bot instance. When set, all '
            'paths (DB, status snapshot, kill switch, log, observability, PID) '
            'route under <ARIBOT_ARTIFACT_DIR>/tenants/<user_id>/. Without it, '
            'the bot writes to legacy CWD-relative names (single-tenant).'
        ),
    )
    return parser.parse_args(list(argv or []))


def resolve_symbol_focus_args(args):
    file_symbols = []
    file_source = None
    if getattr(args, 'symbols_file', None):
        file_symbols = load_symbol_focus_file(args.symbols_file)
        file_source = f"json:{Path(args.symbols_file)}"

    cli_symbols = parse_symbol_focus_csv(getattr(args, 'symbols', None))
    if cli_symbols:
        return cli_symbols, 'cli:--symbols'

    if file_symbols:
        return file_symbols, file_source or 'json'

    return [], 'all_markets'


def derive_pnl_pct(entry_price, current_price, side):
    """Return strategy-facing, price-only PnL percent independent of leverage."""
    try:
        ep = float(entry_price)
        cp = float(current_price)
    except (TypeError, ValueError):
        return 0.0

    if ep <= 0.0:
        return 0.0

    normalized_side = str(side or '').strip().lower()
    if normalized_side in {'long', 'buy'}:
        return ((cp - ep) / ep) * 100.0
    if normalized_side in {'short', 'sell'}:
        return ((ep - cp) / ep) * 100.0

    return 0.0

class PaperPosition:
    """Represents a paper trading position with advanced management"""

    def __init__(self, symbol, side, entry_price, quantity, timestamp):
        self.symbol = symbol
        self.side = side  # 'long' or 'short'
        self.entry_price = entry_price
        self.quantity = quantity
        self.timestamp = timestamp
        self.stop_loss = None
        self.trailing_stop_level = None
        self.current_price = entry_price
        self.gross_pnl = 0.0
        self.fee_cost = 0.0
        self.pnl = 0.0
        self.pnl_percentage = 0.0
        self.round_trip_fee_rate = 0.0011

        # Peak tracking
        self.peak_pnl_percentage = 0.0

        # Revised partial profit settings from improvement report
        self.profit_taking_levels = [0.02, 0.03, 0.05]  # 2%, 3%, 5%
        self.profit_taking_sizes = [0.25, 0.25, 0.25]   # 25%, 25%, 25%
        self.partial_exits = []

        # Revised trailing stop settings from improvement report
        self.trailing_stop_buffer = 0.015  # 1.5% from peak
        self.trailing_stop_active = False
        self.trailing_stop_trigger = 0.02  # activate at 2% profit

        # Branch B native exchange protection state mirrors the SQLite columns.
        self.native_sl_active = False
        self.native_tp_active = False
        self.native_trail_active = False
        self.native_sl_price = None
        self.native_stops_cancelled_at = None

        # Companion limit order placed alongside the market entry.
        self.companion_limit_order_id = None

    def update_price(self, current_price):
        self.current_price = current_price
        if self.side == 'long':
            self.gross_pnl = (current_price - self.entry_price) * self.quantity
        else:
            self.gross_pnl = (self.entry_price - current_price) * self.quantity

        avg_notional = ((self.entry_price + current_price) / 2.0) * self.quantity
        self.fee_cost = avg_notional * self.round_trip_fee_rate
        self.pnl = self.gross_pnl - self.fee_cost
        self.pnl_percentage = derive_pnl_pct(self.entry_price, self.current_price, self.side)

        # Track peak P&L percentage
        if self.pnl_percentage > self.peak_pnl_percentage:
            self.peak_pnl_percentage = self.pnl_percentage

    def should_close_for_loss(self):
        return self.pnl_percentage <= -2.5

    def should_close_for_stop_loss(self):
        if self.stop_loss is None:
            return False

        if self.side == 'long':
            return self.current_price <= self.stop_loss
        else:
            return self.current_price >= self.stop_loss

    def should_activate_trailing_stop(self):
        return self.pnl_percentage >= (self.trailing_stop_trigger * 100) and not self.trailing_stop_active

    def activate_trailing_stop(self):
        self.trailing_stop_active = True
        self.update_trailing_stop()

    def update_trailing_stop(self):
        if not self.trailing_stop_active:
            return False

        if self.side == 'long':
            highest_price = self.entry_price * (1 + self.peak_pnl_percentage / 100)
            level = highest_price * (1 - self.trailing_stop_buffer)
            if self.trailing_stop_level is None or level > self.trailing_stop_level:
                self.trailing_stop_level = level
                return True
        else:
            lowest_price = self.entry_price * (1 - self.peak_pnl_percentage / 100)
            level = lowest_price * (1 + self.trailing_stop_buffer)
            if self.trailing_stop_level is None or level < self.trailing_stop_level:
                self.trailing_stop_level = level
                return True

        return False

    def should_close_for_trailing_stop(self):
        if not self.trailing_stop_active or self.trailing_stop_level is None:
            return False

        if self.side == 'long':
            return self.current_price <= self.trailing_stop_level
        else:
            return self.current_price >= self.trailing_stop_level

    def should_take_partial_profit(self):
        for idx, level in enumerate(self.profit_taking_levels):
            already_taken = any(exit['level'] == level for exit in self.partial_exits)
            if not already_taken and self.pnl_percentage >= (level * 100):
                return idx, level
        return None

    def take_partial_profit(self, idx, level):
        size = self.profit_taking_sizes[idx]
        partial_pnl = self.pnl * size
        self.partial_exits.append({'level': level, 'size': size, 'pnl': partial_pnl, 'time': datetime.datetime.now()})
        self.quantity *= (1 - size)
        return partial_pnl

    def age_minutes(self):
        timestamp = self.timestamp
        if isinstance(timestamp, datetime.datetime) and timestamp.tzinfo is not None:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            ts_utc = timestamp.astimezone(datetime.timezone.utc)
            return (now_utc - ts_utc).total_seconds() / 60.0
        return (datetime.datetime.now() - timestamp).total_seconds() / 60.0

    def should_close_for_time(self, max_minutes=1440):
        return self.age_minutes() >= max_minutes


class Aribot:
    def __init__(
        self,
        startup_secrets=None,
        emoji_mode='noemojis',
        symbol_allowlist=None,
        symbol_allowlist_source='all_markets',
        *,
        tenant_paths=None,
    ):
        # tenant_paths is a tenant_registry.TenantPaths bundle. When None,
        # the bot operates in legacy single-tenant mode (CWD-relative file
        # names). When set, every per-tenant artifact lives under
        # tenant_paths.root and the legacy CWD names are not touched.
        self.tenant_paths = tenant_paths
        self.emoji_mode = normalize_emoji_mode(emoji_mode)
        self.setup_logging(
            emoji_mode=self.emoji_mode,
            log_file_path=str(tenant_paths.log) if tenant_paths is not None else None,
        )
        self.requested_symbol_allowlist = normalize_symbol_focus_entries(symbol_allowlist)
        self.symbol_allowlist_source = str(symbol_allowlist_source or 'all_markets')
        self.bot_mode = str(getattr(startup_secrets, 'bot_mode', os.getenv('BOT_MODE', 'paper'))).strip().lower()
        self.live_execution_enabled = self.bot_mode in {'shadow', 'live'}
        self.telegram_verify_on_start = str(os.getenv('TELEGRAM_VERIFY_ON_START', 'true')).strip().lower() in {'1', 'true', 'yes', 'on'}
        self.bybit_testnet = bool(
            getattr(startup_secrets, 'bybit_testnet', None)
            if startup_secrets is not None
            else str(os.getenv('BYBIT_TESTNET', 'false')).strip().lower() in {'1', 'true', 'yes', 'on'}
        )
        exchange_config = {
            'enableRateLimit': True,
            'options': {
                'defaultType': 'future',
                'adjustForTimeDifference': True,
                'recvWindow': 20000,
            },
        }
        if startup_secrets is not None and self.bot_mode in {'shadow', 'live'}:
            exchange_config['apiKey'] = startup_secrets.read_api_key
            exchange_config['secret'] = startup_secrets.read_api_secret
        self.exchange = ccxt.bybit(exchange_config)
        if self.bybit_testnet:
            self.exchange.set_sandbox_mode(True)
        with contextlib.suppress(Exception):
            self.exchange.load_time_difference()
        # Compute the per-mode DB path here (early) so OrderExecutor and the
        # later sqlite setup share one source of truth. In tenant mode we
        # land under tenant_paths.root; in legacy mode we use the historical
        # CWD-relative `usdt_bot_v2.{mode}.db` filename.
        mode_slug = (self.bot_mode or 'paper').strip().lower() or 'paper'
        if tenant_paths is not None:
            self.db_file = str(tenant_paths.db(mode_slug))
        else:
            self.db_file = f'usdt_bot_v2.{mode_slug}.db'
        self.order_executor = None
        if startup_secrets is not None and self.live_execution_enabled:
            self.order_executor = OrderExecutor(
                startup_secrets.trade_api_key,
                startup_secrets.trade_api_secret,
                idempotency_db_path=self.db_file,
            )
            if self.bybit_testnet:
                self.order_executor.exchange.set_sandbox_mode(True)
            # In shadow mode, submit intents but never send orders to exchange.
            if self.bot_mode == 'shadow':
                self.order_executor.dry_run = True
        self.positions = {}
        self.closed_trades = []
        self.kill_switch_file = (
            str(tenant_paths.kill_switch)
            if tenant_paths is not None
            else os.getenv('KILL_SWITCH_FILE', 'kill_switch.flag')
        )
        self.initial_balance = 400.0
        self.current_balance = self.initial_balance
        self.total_pnl = 0.0
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.max_open_positions = 10
        self.max_tick_age_seconds = 600
        self.min_24h_volume_usdc = 1_000_000
        self.entry_risk_pct = 0.11 # 11% of current balance per trade
        self.atr_volatility_cutoff = 0.05
        self.atr_size_scalar = 0.5
        self.round_trip_fee_rate = 0.0011
        self.major_leverage = 5.0
        self.large_alt_leverage = 3.0
        self.mid_cap_leverage = 2.0
        self.default_leverage = 1.0
        self.leverage_config_file = 'leverage_buckets.json'
        self.major_coins = {'BTC', 'ETH'}
        self.large_alt_coins = {
            'SOL', 'BNB', 'DOT', 'AVAX', 'XRP', 'ADA', 'LINK', 'MATIC', 'LTC', 'ATOM', 'NEAR'
        }
        self.mid_cap_coins = {
            'ENA', 'INJ', 'OP', 'SEI', 'ARB', 'APT', 'SUI', 'TIA', 'WLD', 'JUP'
        }
        self.load_leverage_config()
        self.max_hold_minutes = 40 * 60
        self.daily_drawdown_limit = -0.05
        self.max_consecutive_losses = 3
        self.cooldown_candles = 2
        self.signal_boundary_window_seconds = 60
        self.loop_interval_seconds = 60
        self.allow_missing_ticker_timestamp = True
        self.max_unchanged_tick_cycles = 2

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        self.current_utc_day = now_utc.date()
        self.session_start_balance = self.current_balance
        self.daily_drawdown_paused = False
        self.consecutive_losses = 0
        self.cooldown_until_utc = None
        self.manual_entry_paused = False
        self.manual_override_timestamp_utc = None
        self.loop_cycle_count = 0
        self.last_regime_signal = 'UNKNOWN'
        self.tick_observations = {}
        self.timestamp_fallback_warned = set()
        self.pulse_interval_seconds = 60 * 60
        self.last_pulse_sent_at_utc = None

        self.markets = self.exchange.load_markets()
        self.all_usdt_swaps = sorted(
            [symbol for symbol in self.markets.keys() if self.markets[symbol].get('type') == 'swap' and 'USDT' in symbol]
        )
        self.usdc_swaps, unmatched_symbol_filters = filter_symbols_by_allowlist(
            self.all_usdt_swaps,
            self.requested_symbol_allowlist,
        )
        if self.requested_symbol_allowlist:
            if unmatched_symbol_filters:
                self.logger.warning(
                    '⚠️ Symbol focus entries did not match any Bybit USDT swap market: %s',
                    ', '.join(sorted(unmatched_symbol_filters)),
                )
            if not self.usdc_swaps:
                raise RuntimeError(
                    'Configured symbol focus resolved to zero tradeable Bybit USDT swap markets'
                )

        preview_symbols = ', '.join(self.usdc_swaps[:10])
        suffix = '' if len(self.usdc_swaps) <= 10 else ', ...'
        self.logger.info(
            '🎯 Trade universe loaded: %s active symbols (source=%s, total_available=%s)%s%s',
            len(self.usdc_swaps),
            self.symbol_allowlist_source,
            len(self.all_usdt_swaps),
            ' -> ' if preview_symbols else '',
            f'{preview_symbols}{suffix}' if preview_symbols else '',
        )
        self.btc_regime_symbol = self.resolve_btc_regime_symbol()

        # Mode-specific sqlite. self.db_file was set early in __init__ so
        # OrderExecutor could share the path. In legacy mode (no tenant_paths),
        # auto-migrate the unsuffixed `usdt_bot_v2.db` to the mode-specific
        # name to preserve history across the original single-tenant upgrade.
        # In tenant mode this rename is skipped — each tenant starts with a
        # clean per-mode DB inside their tenant directory.
        if self.tenant_paths is None:
            legacy_db = Path('usdt_bot_v2.db')
            target_db = Path(self.db_file)
            if legacy_db.exists() and not target_db.exists():
                try:
                    legacy_db.rename(target_db)
                    self.logger.info(
                        f"📦 Migrated legacy {legacy_db.name} -> {target_db.name} for mode={mode_slug}"
                    )
                except OSError as exc:
                    self.logger.warning(
                        f"⚠️ Could not rename legacy db: {type(exc).__name__}: {exc}; "
                        f"starting fresh with {target_db.name}"
                    )
        self.db = sqlite3.connect(self.db_file, detect_types=sqlite3.PARSE_DECLTYPES)
        self.db.row_factory = sqlite3.Row
        self.setup_database()
        self.shutdown_requested = False
        self.shutdown_exit_code = 0
        self.run_id = uuid.uuid4().hex[:12]
        self.started_at_utc = datetime.datetime.now(datetime.timezone.utc)
        self.status_snapshot_file = (
            str(tenant_paths.status)
            if tenant_paths is not None
            else os.getenv('STATUS_SNAPSHOT_FILE', 'aribot_status.json')
        )
        self.alert_dispatcher = AlertDispatcher(logger=self.logger)
        self.telegram_chat_id = str(getattr(self.alert_dispatcher, 'chat_id', '') or '').strip()
        self.telegram_last_update_id = 0
        try:
            self.telegram_confirmation_ttl_seconds = max(
                5,
                int(str(os.getenv('TELEGRAM_CONFIRMATION_TTL_SECONDS', '90')).strip()),
            )
        except (TypeError, ValueError):
            self.telegram_confirmation_ttl_seconds = 90
        self.telegram_pending_confirmations = {}
        # Per-tenant structured event log when running multi-tenant; legacy
        # single-stream observability.jsonl in the repo root otherwise.
        observability_path = (
            str(tenant_paths.root / 'observability.jsonl')
            if tenant_paths is not None
            else 'observability.jsonl'
        )
        self.structured_logger = StructuredEventLogger(observability_path, self.run_id)
        self.funding_tracker = FundingTracker(self.exchange, self.db, self.emit_structured_event, self.run_id)
        self.funding_tracker.ensure_schema()
        self.startup_reconciler = StartupReconciler(
            self.exchange,
            self.db,
            self.logger,
            alert_dispatcher=self.dispatch_reconciliation_alert,
            native_stop_executor=self.order_executor if self.live_execution_enabled else None,
        )
        if self.bot_mode in {'shadow', 'live'}:
            self.startup_reconciler.startup_gate()
        self.kill_switch_monitor = KillSwitchMonitor(
            self.kill_switch_file,
            self.logger,
            self.emit_structured_event,
            self.cancel_all_open_orders,
            self.close_all_positions_market,
            self.request_clean_shutdown,
        )
        self.load_state()
        self.last_pulse_sent_at_utc = self._safe_utc_from_iso(self.get_state_value('last_pulse_sent_at'))
        balance_synced = self.sync_account_balance(force=False)
        if balance_synced:
            self.rebase_daily_drawdown_baseline_after_live_sync()
        self.reconcile_positions_on_startup()

    def verify_telegram_readiness(self):
        if not self.telegram_verify_on_start:
            self.logger.info('📨 Telegram verification disabled via TELEGRAM_VERIFY_ON_START=false')
            return

        probe = (
            f"Aribot startup verification: mode={self.bot_mode}, testnet={self.bybit_testnet}, "
            f"run_id={self.run_id}"
        )
        ok = self.alert_dispatcher.verify_delivery(probe)
        if ok:
            self.logger.info('📨 Telegram delivery verification succeeded')
            return

        if self.bot_mode == 'live':
            raise RuntimeError('Telegram end-to-end verification failed in live mode')
        self.logger.warning('📨 Telegram verification failed; continuing because mode is not live')

    def fetch_exchange_usdt_balance(self):
        if not self.live_execution_enabled:
            return None

        try:
            balance = self.exchange.fetch_balance()
        except Exception as exc:
            self.logger.warning(f"⚠️ Failed to fetch exchange balance: {type(exc).__name__}: {exc}")
            return None

        usdt_bucket = balance.get('USDT') if isinstance(balance, dict) else None
        candidate_values = []
        if isinstance(usdt_bucket, dict):
            candidate_values.extend([
                usdt_bucket.get('total'),
                usdt_bucket.get('free'),
            ])
        candidate_values.extend([
            (balance.get('total') or {}).get('USDT') if isinstance(balance.get('total'), dict) else None,
            (balance.get('free') or {}).get('USDT') if isinstance(balance.get('free'), dict) else None,
        ])

        for value in candidate_values:
            try:
                amount = float(value)
            except (TypeError, ValueError):
                continue
            if amount > 0:
                return amount
        return None

    def sync_account_balance(self, force=False):
        if not self.live_execution_enabled:
            return False
        if not force and self.bot_mode == 'shadow':
            # Shadow mode keeps PnL simulation continuity, but still supports manual forced refresh.
            return False

        exchange_balance = self.fetch_exchange_usdt_balance()
        if exchange_balance is None:
            return False

        old_balance = self.current_balance
        self.current_balance = exchange_balance
        if abs(old_balance - self.current_balance) >= 0.01:
            self.logger.info(
                f"💼 Synced exchange USDT balance: {old_balance:.2f} -> {self.current_balance:.2f}"
            )
        self.persist_runtime_state()
        return True

    def rebase_daily_drawdown_baseline_after_live_sync(self):
        if not self.live_execution_enabled:
            return False
        if self.daily_drawdown_paused or self.positions:
            return False
        if self.total_trades != 0 or abs(self.total_pnl) > 1e-9:
            return False
        if abs(self.session_start_balance - self.initial_balance) >= 0.01:
            return False
        if abs(self.current_balance - self.initial_balance) < 0.01:
            return False

        old_baseline = self.session_start_balance
        self.session_start_balance = self.current_balance
        self.logger.info(
            f"🧮 Rebased daily drawdown baseline after live balance sync: {old_baseline:.2f} -> {self.session_start_balance:.2f}"
        )
        return True

    def submit_market_order(self, symbol, side, quantity, reason, idempotency_key, leverage=None):
        if self.order_executor is None:
            return False, None

        result = self.order_executor.execute_order(
            symbol=symbol,
            order_type='market',
            side=side,
            amount=quantity,
            idempotency_key=idempotency_key,
            order_reason=reason,
            leverage=leverage,
        )
        if not result.success:
            self.logger.error(f"❌ Order failed for {symbol} ({reason}): {result.message}")
            self.emit_structured_event(
                'CRITICAL',
                'live_order_rejected',
                'execution',
                'Exchange order failed.',
                symbol=symbol,
                values={
                    'reason': reason,
                    'side': side,
                    'quantity': quantity,
                    'message': result.message,
                    'idempotency_key': result.idempotency_key,
                },
            )
            return False, result.order_data

        return True, result.order_data

    def submit_limit_order(self, symbol, side, quantity, price, reason, idempotency_key, leverage=None):
        if self.order_executor is None:
            return False, None

        result = self.order_executor.execute_order(
            symbol=symbol,
            order_type='limit',
            side=side,
            amount=quantity,
            price=price,
            idempotency_key=idempotency_key,
            order_reason=reason,
            leverage=leverage,
        )
        if not result.success:
            self.logger.error(f"❌ Limit order failed for {symbol} ({reason}): {result.message}")
            self.emit_structured_event(
                'WARNING',
                'live_limit_order_rejected',
                'execution',
                'Exchange limit order failed.',
                symbol=symbol,
                values={
                    'reason': reason,
                    'side': side,
                    'quantity': quantity,
                    'price': price,
                    'message': result.message,
                    'idempotency_key': result.idempotency_key,
                },
            )
            return False, result.order_data

        return True, result.order_data

    @staticmethod
    def compute_companion_limit_price(ohlcv, consec_bars, signal_type):
        if not ohlcv or not consec_bars:
            return None, None
        if signal_type == 'BUY':
            target_idx = max(consec_bars, key=lambda i: ohlcv[i][4])
        elif signal_type == 'SELL':
            target_idx = min(consec_bars, key=lambda i: ohlcv[i][4])
        else:
            return None, None
        bar_high = float(ohlcv[target_idx][2])
        bar_low = float(ohlcv[target_idx][3])
        trigger_price = (bar_high + bar_low) / 2.0
        return trigger_price, target_idx

    @staticmethod
    def extract_order_fill(order_data, fallback_price, fallback_qty):
        data = order_data or {}
        try:
            filled = float(data.get('filled') or fallback_qty)
        except (TypeError, ValueError):
            filled = float(fallback_qty)
        if filled <= 0:
            filled = float(fallback_qty)

        avg_fill_price = data.get('avg_fill_price', data.get('average', data.get('price', fallback_price)))
        try:
            fill_price = float(avg_fill_price)
        except (TypeError, ValueError):
            fill_price = float(fallback_price)
        if fill_price <= 0:
            fill_price = float(fallback_price)

        return fill_price, filled

    def emit_structured_event(self, level, event_type, component, message, symbol=None, values=None):
        self.structured_logger.emit(level, event_type, component, message, symbol=symbol, values=values)
        self.alert_dispatcher.dispatch_event(level, event_type, message, symbol=symbol, values=values)

    def request_clean_shutdown(self, exit_code=0):
        self.shutdown_requested = True
        self.shutdown_exit_code = exit_code

    def dispatch_reconciliation_alert(self, level, message, payload):
        category = str((payload or {}).get('category') or 'startup_reconciliation')
        event_type = f"reconciliation_{category}"
        self.emit_structured_event(
            level,
            event_type,
            'reconciliation',
            message,
            symbol=(payload or {}).get('symbol'),
            values=payload,
        )

    def cancel_all_open_orders(self):
        # The current bot has no live resting-order model yet.
        self.emit_structured_event(
            'INFO',
            'order_cancel_all_noop',
            'kill_switch',
            'No open-order subsystem is active; cancel-all is a no-op.',
            values={'canceled_orders': 0},
        )
        return 0

    def close_all_positions_market(self):
        symbols = list(self.positions.keys())
        for symbol in symbols:
            self.close_position(symbol, 'kill_switch_market_exit')
        return len(symbols)

    def is_signal_window(self, now_utc=None):
        if now_utc is None:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
        return (
            now_utc.hour % 4 == 0
            and now_utc.minute == 0
            and now_utc.second < self.signal_boundary_window_seconds
        )

    def has_fresh_tick(self, symbol):
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            ts_ms, ts_source, is_fallback = self.extract_ticker_timestamp_ms(ticker, now_utc)
            if ts_ms is None:
                return False

            if not is_fallback:
                now_ms = int(now_utc.timestamp() * 1000)
                age_seconds = max(0.0, (now_ms - ts_ms) / 1000.0)
                if age_seconds > self.max_tick_age_seconds:
                    self.logger.warning(
                        f"⚠️ Stale ticker for {symbol}; age={age_seconds:.0f}s > {self.max_tick_age_seconds}s, skipping symbol"
                    )
                    return False

            if is_fallback and symbol not in self.timestamp_fallback_warned:
                self.logger.warning(
                    f"⚠️ Missing exchange timestamp for {symbol}; using {ts_source} fallback"
                )
                self.timestamp_fallback_warned.add(symbol)

            return True
        except Exception:
            return False

    def parse_ticker_datetime_ms(self, dt_str):
        if not isinstance(dt_str, str) or not dt_str.strip():
            return None

        try:
            parsed = datetime.datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=datetime.timezone.utc)
            return int(parsed.timestamp() * 1000)
        except Exception:
            return None

    def extract_ticker_timestamp_ms(self, ticker, now_utc):
        ts_ms = ticker.get('timestamp')
        if ts_ms is not None:
            return int(ts_ms), 'ticker.timestamp', False

        dt_ms = self.parse_ticker_datetime_ms(ticker.get('datetime'))
        if dt_ms is not None:
            return dt_ms, 'ticker.datetime', False

        info = ticker.get('info') or {}
        for key in ['time', 'ts', 'updatedTime', 'updateTime', 'tradeTimeMs']:
            value = info.get(key)
            if value is None:
                continue

            try:
                val_int = int(str(value))
                # Heuristic: treat small values as seconds.
                if val_int < 10_000_000_000:
                    val_int *= 1000
                return val_int, f'ticker.info.{key}', False
            except (TypeError, ValueError):
                continue

        if self.allow_missing_ticker_timestamp:
            return int(now_utc.timestamp() * 1000), 'local_fallback', True

        return None, 'missing', True

    def build_ticker_signature(self, ticker):
        info = ticker.get('info') or {}

        def _norm(value):
            if value is None:
                return None
            try:
                return round(float(value), 12)
            except (TypeError, ValueError):
                return str(value)

        return (
            _norm(ticker.get('last')),
            _norm(ticker.get('bid')),
            _norm(ticker.get('ask')),
            _norm(ticker.get('mark')),
            _norm(ticker.get('index')),
            _norm(info.get('lastPrice')),
            _norm(info.get('markPrice')),
            _norm(info.get('indexPrice')),
        )

    def resolve_btc_regime_symbol(self):
        candidates = [
            symbol for symbol, market in self.markets.items()
            if market.get('type') == 'swap' and market.get('base') == 'BTC' and market.get('quote') == 'USDT'
        ]
        if not candidates:
            return None

        preferred = next((s for s in candidates if s.startswith('BTC/USDT')), candidates[0])
        self.logger.info(f"📊 BTC regime symbol resolved to {preferred}")
        return preferred

    def fetch_btc_regime_signal(self):
        if not self.btc_regime_symbol:
            return None

        for attempt in range(3):
            try:
                ohlcv = self.exchange.fetch_ohlcv(self.btc_regime_symbol, '4h', limit=260)
                if not ohlcv:
                    self.logger.warning(
                        f"⚠️ BTC regime fetch returned empty OHLCV for {self.btc_regime_symbol}"
                    )
                    return None
                if len(ohlcv) < 200:
                    self.logger.warning(
                        f"⚠️ BTC regime OHLCV insufficient: got {len(ohlcv)} candles, need 200 ({self.btc_regime_symbol})"
                    )
                    return None

                ohlc4_values = self.calculate_ohlc4(ohlcv)
                current_ohlc4 = ohlc4_values[-1]
                btc_wma_200 = self.calculate_wma(ohlc4_values, period=90, offset=0)
                if btc_wma_200 is None:
                    self.logger.warning(
                        f"⚠️ BTC regime WMA-200 calculation returned None for {self.btc_regime_symbol}"
                    )
                    return None

                return 'BUY' if current_ohlc4 > btc_wma_200 else 'SELL'
            except Exception as exc:
                if attempt < 2:
                    self.logger.warning(
                        f"⚠️ BTC regime fetch failed (attempt {attempt + 1}/3) for {self.btc_regime_symbol}: {type(exc).__name__}: {exc}. Retrying in 1 second..."
                    )
                    time.sleep(1)
                else:
                    self.logger.error(
                        f"❌ BTC regime fetch failed after 3 attempts for {self.btc_regime_symbol}: {type(exc).__name__}: {exc}"
                    )
                    return None

    def get_ticker_quote_volume(self, ticker):
        quote_volume = ticker.get('quoteVolume')
        if quote_volume is not None:
            return float(quote_volume)

        info = ticker.get('info') or {}
        for key in ['turnover24h', 'quoteVolume', 'volume24h']:
            value = info.get(key)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    continue

        base_volume = ticker.get('baseVolume')
        last_price = ticker.get('last')
        if base_volume is not None and last_price is not None:
            try:
                return float(base_volume) * float(last_price)
            except (TypeError, ValueError):
                return None

        return None

    def passes_volume_filter(self, symbol, ticker):
        quote_volume = self.get_ticker_quote_volume(ticker)
        if quote_volume is None:
            self.logger.warning(f"⚠️ Missing 24h quote volume for {symbol}; skipping symbol")
            return False

        if quote_volume <= self.min_24h_volume_usdc:
            self.logger.info(
                f"⏭️ {symbol} filtered by volume: {quote_volume:.2f} <= {self.min_24h_volume_usdc:.2f}"
            )
            return False

        return True

    def calculate_atr(self, ohlcv_data, period=14):
        if len(ohlcv_data) < period + 1:
            return None

        true_ranges = []
        for i in range(1, len(ohlcv_data)):
            high = ohlcv_data[i][2]
            low = ohlcv_data[i][3]
            prev_close = ohlcv_data[i - 1][4]
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            true_ranges.append(tr)

        if len(true_ranges) < period:
            return None

        return sum(true_ranges[-period:]) / period

    def reset_daily_session_if_needed(self):
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        if now_utc.date() != self.current_utc_day:
            self.current_utc_day = now_utc.date()
            self.session_start_balance = self.current_balance
            self.daily_drawdown_paused = False
            self.logger.info(f"🌅 New UTC day {self.current_utc_day}: reset daily drawdown baseline")
            self.emit_structured_event(
                'INFO',
                'daily_drawdown_reset',
                'risk',
                'Daily drawdown baseline reset.',
                values={'current_utc_day': self.current_utc_day.isoformat(), 'session_start_balance': self.session_start_balance},
            )

    def update_daily_drawdown_pause(self):
        if self.session_start_balance <= 0:
            return

        drawdown = (self.current_balance - self.session_start_balance) / self.session_start_balance
        if drawdown <= self.daily_drawdown_limit and not self.daily_drawdown_paused:
            self.daily_drawdown_paused = True
            self.logger.warning(
                f"🛑 Daily drawdown halt triggered: {drawdown * 100:.2f}% <= {self.daily_drawdown_limit * 100:.2f}%"
            )
            self.emit_structured_event(
                'WARNING',
                'risk_limit_hit',
                'risk',
                'Daily drawdown breaker triggered.',
                values={
                    'rule_name': 'daily_drawdown_limit',
                    'current_value': drawdown,
                    'threshold': self.daily_drawdown_limit,
                    'action_taken': 'pause_new_entries',
                },
            )

    def in_loss_cooldown(self, now_utc=None):
        if self.cooldown_until_utc is None:
            return False
        ref_now = now_utc or datetime.datetime.now(datetime.timezone.utc)
        return ref_now < self.cooldown_until_utc

    def entry_gate_block_reason(self, now_utc=None):
        if self.manual_entry_paused:
            return 'manual_pause'
        if self.daily_drawdown_paused:
            return 'daily_drawdown_pause'
        if self.in_loss_cooldown(now_utc=now_utc):
            return 'loss_cooldown'
        return None

    def _normalize_symbol_set(self, symbols):
        normalized = set()
        if not isinstance(symbols, list):
            return normalized

        for symbol in symbols:
            if isinstance(symbol, str) and symbol.strip():
                normalized.add(symbol.strip().upper())
        return normalized

    def _read_bucket(self, cfg, key, default_leverage, default_symbols):
        bucket = cfg.get(key, {})
        if not isinstance(bucket, dict):
            return default_leverage, default_symbols

        leverage = bucket.get('leverage', default_leverage)
        try:
            leverage = float(leverage)
            if leverage <= 0:
                leverage = default_leverage
        except (TypeError, ValueError):
            leverage = default_leverage

        symbols = self._normalize_symbol_set(bucket.get('symbols', list(default_symbols)))
        if not symbols:
            symbols = set(default_symbols)

        return leverage, symbols

    def load_leverage_config(self):
        config_path = Path(self.leverage_config_file)
        if not config_path.exists():
            self.logger.info(
                f"⚙️ Leverage config file {config_path} not found, using built-in defaults"
            )
            return

        try:
            with config_path.open('r', encoding='utf-8') as f:
                cfg = json.load(f)

            if not isinstance(cfg, dict):
                raise ValueError('Top-level JSON must be an object')

            self.major_leverage, self.major_coins = self._read_bucket(
                cfg, 'major', self.major_leverage, self.major_coins
            )
            self.large_alt_leverage, self.large_alt_coins = self._read_bucket(
                cfg, 'large_alt', self.large_alt_leverage, self.large_alt_coins
            )
            self.mid_cap_leverage, self.mid_cap_coins = self._read_bucket(
                cfg, 'mid_cap', self.mid_cap_leverage, self.mid_cap_coins
            )

            default_leverage = cfg.get('default_leverage', self.default_leverage)
            try:
                default_leverage = float(default_leverage)
                if default_leverage > 0:
                    self.default_leverage = default_leverage
            except (TypeError, ValueError):
                pass

            self.logger.info(
                '⚙️ Loaded leverage config '
                f"(major={self.major_leverage}x/{len(self.major_coins)} syms, "
                f"large_alt={self.large_alt_leverage}x/{len(self.large_alt_coins)} syms, "
                f"mid_cap={self.mid_cap_leverage}x/{len(self.mid_cap_coins)} syms, "
                f"default={self.default_leverage}x)"
            )
        except Exception as exc:
            self.logger.warning(
                f"⚠️ Failed to load leverage config {config_path}: {exc}. Using built-in defaults"
            )

    def get_base_asset(self, symbol):
        market = self.markets.get(symbol, {})
        base = market.get('base')
        if base:
            return base.upper()

        symbol_head = symbol.split(':')[0]
        if '/' in symbol_head:
            return symbol_head.split('/')[0].upper()

        return symbol_head.upper()

    def get_leverage_for_symbol(self, symbol):
        base_asset = self.get_base_asset(symbol)

        if base_asset in self.major_coins:
            return self.major_leverage, 'major'
        if base_asset in self.large_alt_coins:
            return self.large_alt_leverage, 'large_alt'
        if base_asset in self.mid_cap_coins:
            return self.mid_cap_leverage, 'mid_cap'
        return self.default_leverage, 'default'

    def setup_logging(self, emoji_mode='noemojis', log_file_path=None):
        """Configure the 'Aribot' logger with a console handler and a file
        handler.

        log_file_path: when None, write to 'usdt_trading_log.txt' in CWD
        (legacy single-tenant). When set (passed by __init__ in multi-tenant
        mode), write to the per-tenant log path so two tenants don't
        commingle log lines in one file.
        """
        self.logger = logging.getLogger('Aribot')
        self.logger.setLevel(logging.INFO)
        self.logger.handlers.clear()
        self.logger.propagate = False
        formatter = logging.Formatter('%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        emoji_filter = EmojiLogFilter(emoji_mode=emoji_mode)

        console_handler = SafeStreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        console_handler.addFilter(emoji_filter)

        log_path = log_file_path or 'usdt_trading_log.txt'
        # Ensure the parent directory exists when running in tenant mode
        # (TenantRegistry already mkdir's the tenant root, but be explicit
        # for the case where the caller passes some other path).
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, mode='a', encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        file_handler.addFilter(emoji_filter)

        self.logger.addHandler(console_handler)
        self.logger.addHandler(file_handler)

    def setup_database(self):
        cursor = self.db.cursor()
        cursor.execute('''
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
                native_sl_price REAL,
                native_stops_cancelled_at TEXT,
                companion_limit_order_id TEXT
            )
        ''')
        cursor.execute('''
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
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS partial_realizations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                level REAL,
                size REAL,
                pnl REAL,
                event_time TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bot_state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')

        # Lightweight migration for existing DBs created before partial_exits_json existed.
        existing_columns = {
            row['name'] for row in cursor.execute("PRAGMA table_info(positions)").fetchall()
        }
        if 'partial_exits_json' not in existing_columns:
            cursor.execute("ALTER TABLE positions ADD COLUMN partial_exits_json TEXT DEFAULT '[]'")
        if 'native_sl_active' not in existing_columns:
            cursor.execute("ALTER TABLE positions ADD COLUMN native_sl_active INTEGER DEFAULT 0")
        if 'native_tp_active' not in existing_columns:
            cursor.execute("ALTER TABLE positions ADD COLUMN native_tp_active INTEGER DEFAULT 0")
        if 'native_trail_active' not in existing_columns:
            cursor.execute("ALTER TABLE positions ADD COLUMN native_trail_active INTEGER DEFAULT 0")
        if 'native_sl_price' not in existing_columns:
            cursor.execute("ALTER TABLE positions ADD COLUMN native_sl_price REAL")
        if 'native_stops_cancelled_at' not in existing_columns:
            cursor.execute("ALTER TABLE positions ADD COLUMN native_stops_cancelled_at TEXT")
        if 'companion_limit_order_id' not in existing_columns:
            cursor.execute("ALTER TABLE positions ADD COLUMN companion_limit_order_id TEXT")

        self.db.commit()

    def set_state_value(self, key, value):
        cursor = self.db.cursor()
        cursor.execute(
            'INSERT OR REPLACE INTO bot_state (key, value) VALUES (?, ?)',
            (key, str(value))
        )
        self.db.commit()

    def get_state_value(self, key):
        cursor = self.db.cursor()
        row = cursor.execute('SELECT value FROM bot_state WHERE key = ?', (key,)).fetchone()
        return row['value'] if row else None

    def get_state_float(self, key):
        value = self.get_state_value(key)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def get_state_int(self, key):
        value = self.get_state_value(key)
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def supported_telegram_commands_help_text():
        return (
            'Invalid command format. Use one of: '
            '/status, /positions, /pnl, /trades [n], /pause, /resume, '
            '/close SYMBOL, /close all, /kill, /config'
        )

    def is_authorized_chat(self, chat_id):
        expected = str(self.telegram_chat_id or '').strip()
        candidate = str(chat_id or '').strip()
        return bool(expected and candidate and expected == candidate)

    def parse_telegram_command(self, text):
        if not isinstance(text, str):
            return {'ok': False, 'error': 'invalid_command'}

        raw = text.strip()
        if not raw:
            return {'ok': False, 'error': 'invalid_command'}

        lowered = raw.lower()
        if lowered in {'/status', '/positions', '/pnl', '/pause', '/resume', '/kill', '/config'}:
            return {'ok': True, 'command': lowered, 'args': {}}

        if lowered == '/trades':
            return {'ok': True, 'command': '/trades', 'args': {'limit': None}}
        if lowered.startswith('/trades '):
            tokens = raw.split()
            if len(tokens) != 2:
                return {'ok': False, 'error': 'invalid_command'}
            try:
                limit = int(tokens[1])
            except (TypeError, ValueError):
                return {'ok': False, 'error': 'invalid_command'}
            if limit <= 0:
                return {'ok': False, 'error': 'invalid_command'}
            return {'ok': True, 'command': '/trades', 'args': {'limit': limit}}

        if lowered == '/close all':
            return {'ok': True, 'command': '/close_all', 'args': {}}

        if lowered.startswith('/close '):
            tokens = raw.split()
            if len(tokens) != 2:
                return {'ok': False, 'error': 'invalid_command'}
            symbol = tokens[1].strip()
            if not symbol or symbol.lower() == 'all':
                return {'ok': False, 'error': 'invalid_command'}
            return {'ok': True, 'command': '/close_symbol', 'args': {'symbol': symbol}}

        return {'ok': False, 'error': 'invalid_command'}

    @staticmethod
    def _safe_utc_from_iso(raw_value):
        if not isinstance(raw_value, str) or not raw_value.strip():
            return None
        try:
            parsed = datetime.datetime.fromisoformat(raw_value)
        except Exception:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        return parsed.astimezone(datetime.timezone.utc)

    def _ensure_pending_confirmation_store(self):
        store = getattr(self, 'telegram_pending_confirmations', None)
        if not isinstance(store, dict):
            store = {}
            self.telegram_pending_confirmations = store
        return store

    def _pending_confirmation_ttl_seconds(self):
        raw = getattr(self, 'telegram_confirmation_ttl_seconds', 90)
        try:
            ttl = int(raw)
        except (TypeError, ValueError):
            ttl = 90
        return max(5, ttl)

    def _persist_pending_confirmations(self):
        payload = {}
        for chat_id, pending in self._ensure_pending_confirmation_store().items():
            if not isinstance(pending, dict):
                continue

            action = str(pending.get('action') or '').strip()
            expires_at = str(pending.get('expires_at_utc') or '').strip()
            if not action or not expires_at:
                continue

            payload[str(chat_id)] = {
                'action': action,
                'args': pending.get('args') if isinstance(pending.get('args'), dict) else {},
                'created_at_utc': str(pending.get('created_at_utc') or '').strip(),
                'expires_at_utc': expires_at,
                'nonce': str(pending.get('nonce') or '').strip(),
            }

        self.set_state_value('telegram_pending_confirmations_json', json.dumps(payload, separators=(',', ':')))

    def _build_pending_confirmation(self, chat_id, action, args, now_utc=None):
        now = now_utc or datetime.datetime.now(datetime.timezone.utc)
        expires_at = now + datetime.timedelta(seconds=self._pending_confirmation_ttl_seconds())
        pending = {
            'chat_id': str(chat_id or '').strip(),
            'action': str(action or '').strip(),
            'args': dict(args or {}),
            'created_at_utc': now.isoformat(),
            'expires_at_utc': expires_at.isoformat(),
            'nonce': uuid.uuid4().hex,
        }
        store = self._ensure_pending_confirmation_store()
        store[pending['chat_id']] = pending
        self._persist_pending_confirmations()
        return pending

    def _clear_pending_confirmation(self, chat_id):
        chat_key = str(chat_id or '').strip()
        store = self._ensure_pending_confirmation_store()
        removed = chat_key in store
        if removed:
            store.pop(chat_key, None)
            self._persist_pending_confirmations()
        return removed

    def _get_pending_confirmation(self, chat_id, now_utc=None):
        chat_key = str(chat_id or '').strip()
        pending = self._ensure_pending_confirmation_store().get(chat_key)
        if not isinstance(pending, dict):
            return None

        expires_at = self._safe_utc_from_iso(pending.get('expires_at_utc'))
        now = now_utc or datetime.datetime.now(datetime.timezone.utc)
        if expires_at is None or now >= expires_at:
            self._clear_pending_confirmation(chat_key)
            return None
        return pending

    def _build_confirmation_prompt(self, pending):
        action = str((pending or {}).get('action') or '').strip()
        args = (pending or {}).get('args') if isinstance((pending or {}).get('args'), dict) else {}
        ttl = self._pending_confirmation_ttl_seconds()

        if action == 'close_symbol':
            symbol = str(args.get('symbol') or '').strip()
            return f'Confirm /close {symbol}: reply YES within {ttl}s.'
        if action == 'close_all':
            return f'Confirm /close all: reply YES within {ttl}s.'
        if action == 'kill':
            return f'Confirm /kill: reply YES within {ttl}s.'
        return f'Confirm action: reply YES within {ttl}s.'

    def _execute_confirmed_telegram_action(self, pending):
        action = str((pending or {}).get('action') or '').strip()
        args = (pending or {}).get('args') if isinstance((pending or {}).get('args'), dict) else {}

        if action == 'close_symbol':
            symbol = str(args.get('symbol') or '').strip()
            if not symbol or symbol not in self.positions:
                self.alert_dispatcher.send_message(f'Cannot close {symbol or "<unknown>"}: no open position.')
                return 'safe_error'

            self.close_position(symbol, 'telegram_manual_close')
            if symbol in self.positions:
                self.alert_dispatcher.send_message(f'Close request for {symbol} did not complete.')
                self._emit_telegram_command_event(
                    'WARNING',
                    'telegram_command_executed',
                    'Confirmed close-symbol command did not complete.',
                    values={'command': '/close SYMBOL', 'symbol': symbol, 'result': 'failed'},
                )
                return 'failed'

            self.alert_dispatcher.send_message(f'Closed position {symbol}.')
            self._emit_telegram_command_event(
                'INFO',
                'telegram_command_executed',
                'Confirmed close-symbol command executed.',
                values={'command': '/close SYMBOL', 'symbol': symbol, 'result': 'accepted'},
            )
            return 'accepted'

        if action == 'close_all':
            requested = self.close_all_positions_market()
            remaining = len(self.positions)
            self.alert_dispatcher.send_message(
                f'Close-all completed. requested={requested} remaining={remaining}.'
            )
            self._emit_telegram_command_event(
                'INFO',
                'telegram_command_executed',
                'Confirmed close-all command executed.',
                values={'command': '/close all', 'requested': requested, 'remaining': remaining},
            )
            return 'accepted'

        if action == 'kill':
            kill_path = Path(self.kill_switch_file)
            if kill_path.parent and str(kill_path.parent) not in {'', '.'}:
                kill_path.parent.mkdir(parents=True, exist_ok=True)
            kill_path.write_text('telegram_kill\n', encoding='utf-8')
            requested = self.close_all_positions_market()
            self.request_clean_shutdown(exit_code=42)
            self.alert_dispatcher.send_message(
                f'Kill confirmed. flag={kill_path} close_all_requested={requested} shutdown_exit_code=42.'
            )
            self._emit_telegram_command_event(
                'CRITICAL',
                'telegram_command_executed',
                'Confirmed kill command executed.',
                values={'command': '/kill', 'flag': str(kill_path), 'close_all_requested': requested, 'exit_code': 42},
            )
            return 'accepted'

        self.alert_dispatcher.send_message('No executable pending action found.')
        return 'safe_error'

    def _emit_telegram_command_event(self, level, event_type, message, symbol=None, values=None):
        emitter = getattr(self, 'emit_structured_event', None)
        if callable(emitter):
            emitter(level, event_type, 'telegram', message, symbol=symbol, values=values or {})

    def _handle_confirmation_gate(self, chat_id, text, now_utc=None):
        now = now_utc or datetime.datetime.now(datetime.timezone.utc)
        normalized = str(text or '').strip()
        normalized_upper = normalized.upper()
        chat_key = str(chat_id or '').strip()

        pending = self._ensure_pending_confirmation_store().get(chat_key)
        if isinstance(pending, dict):
            expires_at = self._safe_utc_from_iso(pending.get('expires_at_utc'))
            if expires_at is None or now >= expires_at:
                self._clear_pending_confirmation(chat_key)
                if normalized_upper == 'YES':
                    self.alert_dispatcher.send_message('Pending action expired. Re-issue command.')
                    self._emit_telegram_command_event(
                        'WARNING',
                        'telegram_command_confirmation_expired',
                        'Pending confirmation expired before YES reply.',
                        values={'chat_id': chat_key},
                    )
                    return 'handled'
                pending = None
        else:
            pending = None

        if pending is None:
            if normalized_upper == 'YES':
                self.alert_dispatcher.send_message('No pending confirmation.')
                self._emit_telegram_command_event(
                    'INFO',
                    'telegram_command_confirmation_missing',
                    'YES received with no pending confirmation.',
                    values={'chat_id': chat_key},
                )
                return 'handled'
            return 'pass'

        # Allow command messages to route normally so a new dangerous command
        # can replace the current pending action.
        if normalized.startswith('/'):
            return 'pass'

        if normalized_upper != 'YES':
            self._clear_pending_confirmation(chat_id)
            self.alert_dispatcher.send_message('Pending action canceled.')
            self._emit_telegram_command_event(
                'INFO',
                'telegram_command_confirmation_canceled',
                'Pending confirmation canceled by non-YES reply.',
                values={'chat_id': chat_key},
            )
            return 'handled'

        self._clear_pending_confirmation(chat_id)
        self._emit_telegram_command_event(
            'INFO',
            'telegram_command_confirmation_accepted',
            'Pending confirmation accepted with YES.',
            values={'chat_id': chat_key, 'action': str(pending.get('action') or '')},
        )
        self._execute_confirmed_telegram_action(pending)
        return 'handled'

    def _compute_session_drawdown_pct(self):
        if self.session_start_balance <= 0:
            return 0.0
        return ((self.current_balance - self.session_start_balance) / self.session_start_balance) * 100.0

    def build_runtime_status_snapshot(self, now_utc=None):
        ref_now = now_utc or datetime.datetime.now(datetime.timezone.utc)
        cooldown_active = bool(self.cooldown_until_utc and ref_now < self.cooldown_until_utc)
        cooldown_until = None
        if self.cooldown_until_utc is not None:
            cooldown_until = self.cooldown_until_utc.isoformat()

        return {
            'mode': str(self.bot_mode or 'unknown'),
            'regime_direction': str(self.last_regime_signal or 'UNKNOWN'),
            'session_pnl': float(self.current_balance - self.session_start_balance),
            'current_balance': float(self.current_balance),
            'wins': int(self.winning_trades),
            'losses': int(self.losing_trades),
            'cycle_count': int(self.loop_cycle_count),
            'drawdown_pct': float(self._compute_session_drawdown_pct()),
            'cooldown_active': bool(cooldown_active),
            'cooldown_until_utc': cooldown_until,
            'trade_universe_size': int(len(self.usdc_swaps)),
        }

    def format_status_command_text(self, now_utc=None):
        snap = self.build_runtime_status_snapshot(now_utc=now_utc)
        if snap['cooldown_active'] and snap['cooldown_until_utc']:
            cooldown_text = f"active until {snap['cooldown_until_utc']}"
        else:
            cooldown_text = 'inactive'

        return (
            'Status\n'
            f"Mode: {snap['mode']} | Regime: {snap['regime_direction']} | Cycle: {snap['cycle_count']}\n"
            f"Session PnL: {snap['session_pnl']:+.2f}\n"
            f"Balance: ${snap['current_balance']:.2f}\n"
            f"Wins: {snap['wins']}  Losses: {snap['losses']}\n"
            f"Drawdown: {snap['drawdown_pct']:+.2f}%\n"
            f"Cooldown: {cooldown_text}"
        )

    def format_positions_command_text(self):
        if not self.positions:
            return 'Positions (0) — none open'

        lines = [f'Positions ({len(self.positions)})']
        for symbol in sorted(self.positions.keys()):
            pos = self.positions[symbol]
            trail_active = 'yes' if pos.trailing_stop_active else 'no'
            lines.append(
                f"{symbol} {pos.side} e={pos.entry_price:.4f} px={pos.current_price:.4f} "
                f"pnl={pos.pnl_percentage:+.2f}% trail={trail_active}"
            )
        return '\n'.join(lines)

    def _build_pulse_snapshot(self, now_utc=None):
        ref_now = now_utc or datetime.datetime.now(datetime.timezone.utc)
        gate_reason = self.entry_gate_block_reason(now_utc=ref_now)
        entries_state = 'active' if gate_reason is None else 'paused'
        return {
            'time_utc': ref_now,
            'mode': str(self.bot_mode or 'unknown'),
            'positions': int(len(self.positions)),
            'balance': float(self.current_balance),
            'session_pnl': float(self.current_balance - self.session_start_balance),
            'entries_state': entries_state,
            'pause_reason': gate_reason,
        }

    def _should_send_pulse(self, now_utc):
        last_sent = self.last_pulse_sent_at_utc
        if last_sent is None:
            return True
        elapsed_seconds = (now_utc - last_sent).total_seconds()
        return elapsed_seconds >= self.pulse_interval_seconds

    def maybe_send_scheduled_pulse(self, *, trigger, now_utc=None):
        ref_now = now_utc or datetime.datetime.now(datetime.timezone.utc)
        if not self._should_send_pulse(ref_now):
            return False

        pulse_data = self._build_pulse_snapshot(now_utc=ref_now)
        send_pulse = getattr(self.alert_dispatcher, 'send_pulse', None)
        if callable(send_pulse):
            pulse_ok = send_pulse(pulse_data)
        else:
            pulse_ok = bool(self.alert_dispatcher.send_message('Pulse unavailable: dispatcher missing send_pulse implementation.'))
        if not pulse_ok:
            self.logger.warning('⚠️ Scheduled pulse send failed (trigger=%s).', trigger)
            self.emit_structured_event(
                'WARNING',
                'telegram_pulse_send_failed',
                'telegram',
                'Scheduled pulse send failed.',
                values={'trigger': trigger},
            )
            return False

        self.last_pulse_sent_at_utc = ref_now
        self.set_state_value('last_pulse_sent_at', ref_now.isoformat())
        self.emit_structured_event(
            'INFO',
            'telegram_pulse_sent',
            'telegram',
            'Scheduled pulse sent.',
            values={'trigger': trigger, 'sent_at_utc': ref_now.isoformat()},
        )
        return True

    @staticmethod
    def _utc_today_iso(now_utc=None):
        ts = now_utc or datetime.datetime.now(datetime.timezone.utc)
        return ts.date().isoformat()

    def fetch_closed_trades_rows(self, limit=None, today_only=False, now_utc=None):
        cursor = self.db.cursor()
        query = (
            'SELECT symbol, pnl, pnl_percentage, reason, close_time '
            'FROM closed_trades'
        )
        params = []
        if today_only:
            query += ' WHERE substr(close_time, 1, 10) = ?'
            params.append(self._utc_today_iso(now_utc=now_utc))
        query += ' ORDER BY close_time DESC'
        if limit is not None:
            query += ' LIMIT ?'
            params.append(int(limit))

        return cursor.execute(query, tuple(params)).fetchall()

    def get_today_realized_pnl(self, now_utc=None):
        cursor = self.db.cursor()
        row = cursor.execute(
            'SELECT COALESCE(SUM(pnl), 0.0) AS today_realized FROM closed_trades WHERE substr(close_time, 1, 10) = ?',
            (self._utc_today_iso(now_utc=now_utc),),
        ).fetchone()
        if not row:
            return 0.0
        return float(row['today_realized'] or 0.0)

    def format_pnl_command_text(self, now_utc=None):
        today_realized = self.get_today_realized_pnl(now_utc=now_utc)
        return (
            'PnL\n'
            f'today_realized={today_realized:+.2f} cumulative={self.total_pnl:+.2f}\n'
            f'wins={self.winning_trades} losses={self.losing_trades}'
        )

    def format_trades_command_text(self, limit=None, now_utc=None):
        today_only = limit is None
        rows = self.fetch_closed_trades_rows(limit=limit, today_only=today_only, now_utc=now_utc)
        if not rows:
            if today_only:
                return 'No closed trades today (UTC).'
            return 'No closed trades found.'

        if today_only:
            lines = ['Trades today (UTC)']
        else:
            lines = [f'Trades last {int(limit)}']

        for row in rows:
            close_time = str(row['close_time'] or '')
            ts = close_time.replace('T', ' ')[:19] if close_time else 'n/a'
            lines.append(
                f"{ts} {row['symbol']} pnl={float(row['pnl'] or 0.0):+.2f} "
                f"({float(row['pnl_percentage'] or 0.0):+.2f}%) {row['reason']}"
            )

        return '\n'.join(lines)

    @staticmethod
    def _operator_stop_pct_config_value():
        # Keep /config output aligned to the strategy-level hard stop threshold.
        return 2.5

    def build_safe_config_snapshot(self):
        return {
            'mode': str(self.bot_mode or 'unknown'),
            'leverage_buckets': {
                'major': float(self.major_leverage),
                'large_alt': float(self.large_alt_leverage),
                'mid_cap': float(self.mid_cap_leverage),
                'default': float(self.default_leverage),
            },
            'position_cap': int(self.max_open_positions),
            'stop_pct': float(self._operator_stop_pct_config_value()),
            'symbol_focus_source': str(self.symbol_allowlist_source or 'all_markets'),
            'trade_universe_size': int(len(self.usdc_swaps)),
        }

    def format_config_command_text(self):
        snap = self.build_safe_config_snapshot()
        buckets = snap['leverage_buckets']
        return (
            'Config (read-only)\n'
            f"mode={snap['mode']}\n"
            f"leverage_buckets=major:{buckets['major']:.2f}x "
            f"large_alt:{buckets['large_alt']:.2f}x "
            f"mid_cap:{buckets['mid_cap']:.2f}x "
            f"default:{buckets['default']:.2f}x\n"
            f"position_cap={snap['position_cap']} stop_pct={snap['stop_pct']:.2f}%\n"
            f"symbol_focus={snap['symbol_focus_source']} active_symbols={snap['trade_universe_size']}"
        )

    def set_manual_entry_pause(self, pause_enabled, now_utc=None):
        now = now_utc or datetime.datetime.now(datetime.timezone.utc)
        self.manual_entry_paused = bool(pause_enabled)
        self.manual_override_timestamp_utc = now
        self.set_state_value('telegram_manual_pause_active', 1 if self.manual_entry_paused else 0)
        self.set_state_value('telegram_manual_pause_updated_at', now.isoformat())
        action = 'pause' if self.manual_entry_paused else 'resume'
        self.logger.warning(
            '⚙️ Manual entry override: action=%s timestamp_utc=%s',
            action,
            now.isoformat(),
        )
        return now.isoformat()

    def route_telegram_command(self, chat_id, text, update_id, now_utc):
        self._emit_telegram_command_event(
            'INFO',
            'telegram_command_received',
            'Telegram command received.',
            values={'chat_id': str(chat_id or ''), 'text': str(text or ''), 'update_id': update_id},
        )

        if not self.is_authorized_chat(chat_id):
            self.alert_dispatcher.send_message('Unauthorized chat.')
            self._emit_telegram_command_event(
                'WARNING',
                'telegram_command_rejected',
                'Telegram command rejected due to unauthorized chat.',
                values={'chat_id': str(chat_id or ''), 'update_id': update_id},
            )
            return 'unauthorized'

        gate_result = self._handle_confirmation_gate(chat_id=chat_id, text=text, now_utc=now_utc)
        if gate_result == 'handled':
            return 'accepted'

        parsed = self.parse_telegram_command(text)
        if not parsed.get('ok'):
            self.alert_dispatcher.send_message(self.supported_telegram_commands_help_text())
            self._emit_telegram_command_event(
                'INFO',
                'telegram_command_rejected',
                'Telegram command rejected due to invalid syntax.',
                values={'chat_id': str(chat_id or ''), 'text': str(text or ''), 'update_id': update_id},
            )
            return 'invalid'

        command = parsed['command']
        args = parsed.get('args', {})
        if command == '/status':
            self.alert_dispatcher.send_message(self.format_status_command_text(now_utc=now_utc))
            self._emit_telegram_command_event('INFO', 'telegram_command_executed', 'Status command executed.', values={'command': '/status', 'update_id': update_id})
            return 'accepted'
        if command == '/positions':
            self.alert_dispatcher.send_message(self.format_positions_command_text())
            self._emit_telegram_command_event('INFO', 'telegram_command_executed', 'Positions command executed.', values={'command': '/positions', 'update_id': update_id})
            return 'accepted'
        if command == '/pnl':
            self.alert_dispatcher.send_message(self.format_pnl_command_text(now_utc=now_utc))
            self._emit_telegram_command_event('INFO', 'telegram_command_executed', 'PnL command executed.', values={'command': '/pnl', 'update_id': update_id})
            return 'accepted'
        if command == '/trades':
            limit = args.get('limit')
            self.alert_dispatcher.send_message(self.format_trades_command_text(limit=limit, now_utc=now_utc))
            self._emit_telegram_command_event('INFO', 'telegram_command_executed', 'Trades command executed.', values={'command': '/trades', 'limit': limit, 'update_id': update_id})
            return 'accepted'
        if command == '/config':
            self.alert_dispatcher.send_message(self.format_config_command_text())
            self._emit_telegram_command_event('INFO', 'telegram_command_executed', 'Config command executed.', values={'command': '/config', 'update_id': update_id})
            return 'accepted'
        if command == '/pause':
            override_ts = self.set_manual_entry_pause(True, now_utc=now_utc)
            self.alert_dispatcher.send_message(
                f'Entries paused (new entries only). override_utc={override_ts}'
            )
            self._emit_telegram_command_event('INFO', 'telegram_command_executed', 'Pause command executed.', values={'command': '/pause', 'override_utc': override_ts, 'update_id': update_id})
            return 'accepted'
        if command == '/resume':
            override_ts = self.set_manual_entry_pause(False, now_utc=now_utc)
            self.alert_dispatcher.send_message(f'Entries resumed. override_utc={override_ts}')
            self._emit_telegram_command_event('INFO', 'telegram_command_executed', 'Resume command executed.', values={'command': '/resume', 'override_utc': override_ts, 'update_id': update_id})
            return 'accepted'
        if command == '/close_symbol':
            symbol = args.get('symbol', '')
            pending = self._build_pending_confirmation(
                chat_id=chat_id,
                action='close_symbol',
                args={'symbol': str(symbol)},
                now_utc=now_utc,
            )
            self.alert_dispatcher.send_message(self._build_confirmation_prompt(pending))
            self._emit_telegram_command_event('WARNING', 'telegram_command_confirmation_required', 'Close-symbol confirmation required.', values={'command': '/close SYMBOL', 'symbol': str(symbol), 'nonce': str(pending.get('nonce') or ''), 'update_id': update_id})
            return 'accepted'
        if command == '/close_all':
            pending = self._build_pending_confirmation(
                chat_id=chat_id,
                action='close_all',
                args={},
                now_utc=now_utc,
            )
            self.alert_dispatcher.send_message(self._build_confirmation_prompt(pending))
            self._emit_telegram_command_event('WARNING', 'telegram_command_confirmation_required', 'Close-all confirmation required.', values={'command': '/close all', 'nonce': str(pending.get('nonce') or ''), 'update_id': update_id})
            return 'accepted'
        if command == '/kill':
            pending = self._build_pending_confirmation(
                chat_id=chat_id,
                action='kill',
                args={},
                now_utc=now_utc,
            )
            self.alert_dispatcher.send_message(self._build_confirmation_prompt(pending))
            self._emit_telegram_command_event('CRITICAL', 'telegram_command_confirmation_required', 'Kill confirmation required.', values={'command': '/kill', 'nonce': str(pending.get('nonce') or ''), 'update_id': update_id})
            return 'accepted'

        self.alert_dispatcher.send_message(f'Command accepted: {command}')
        return 'accepted'

    def persist_telegram_update_offset(self, next_offset):
        try:
            normalized = max(0, int(next_offset))
        except (TypeError, ValueError):
            return
        self.telegram_last_update_id = normalized
        self.set_state_value('telegram_last_update_id', normalized)

    def poll_telegram_commands_once(self, cycle_index):
        if not self.alert_dispatcher.enabled:
            return

        try:
            payload = self.alert_dispatcher.get_updates(
                offset=self.telegram_last_update_id,
                timeout_seconds=0,
                limit=25,
            )
        except Exception as exc:
            self.logger.warning('⚠️ Telegram command poll failed on cycle %s: %s', cycle_index, exc)
            return

        if not isinstance(payload, dict) or not payload.get('ok'):
            self.logger.warning('⚠️ Telegram command poll warning on cycle %s: %s', cycle_index, payload)
            return

        updates = payload.get('updates')
        if not isinstance(updates, list):
            self.logger.warning('⚠️ Telegram command poll returned invalid updates payload on cycle %s', cycle_index)
            return

        sortable_updates = []
        for raw_update in updates:
            if not isinstance(raw_update, dict):
                continue
            try:
                sortable_updates.append((int(raw_update.get('update_id')), raw_update))
            except (TypeError, ValueError):
                self.logger.warning('⚠️ Telegram update missing valid update_id: %s', raw_update)

        sortable_updates.sort(key=lambda item: item[0])
        for update_id, raw_update in sortable_updates:
            try:
                message = raw_update.get('message') or raw_update.get('edited_message')
                if not isinstance(message, dict):
                    continue

                chat = message.get('chat')
                text = message.get('text')
                if not isinstance(chat, dict) or not isinstance(text, str):
                    continue

                chat_id = str(chat.get('id', '')).strip()
                normalized_text = text.strip()
                if normalized_text:
                    self.route_telegram_command(
                        chat_id=chat_id,
                        text=normalized_text,
                        update_id=update_id,
                        now_utc=datetime.datetime.now(datetime.timezone.utc),
                    )
            except Exception as exc:
                self.logger.warning('⚠️ Telegram update handling warning update_id=%s: %s', update_id, exc)
            finally:
                self.persist_telegram_update_offset(update_id + 1)

    def persist_runtime_state(self):
        self.set_state_value('current_balance', self.current_balance)
        self.set_state_value('total_pnl', self.total_pnl)
        self.set_state_value('total_trades', self.total_trades)
        self.set_state_value('winning_trades', self.winning_trades)
        self.set_state_value('losing_trades', self.losing_trades)

    def write_status_snapshot(self):
        # Atomically write a small JSON snapshot for the status HTTP sidecar.
        # The sidecar derives running/stopped/error/killed from file freshness
        # + pid liveness + kill_switch presence — this writer only records
        # facts the bot knows about itself.
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        session_pnl = float(self.current_balance) - float(self.session_start_balance)
        snapshot = {
            'schema': 1,
            'pid': os.getpid(),
            'run_id': self.run_id,
            'wrote_at': now_utc.isoformat(),
            'started_at': self.started_at_utc.isoformat(),
            'last_cycle_iso': now_utc.isoformat(),
            'cycle_count': int(self.loop_cycle_count),
            'loop_interval_seconds': int(self.loop_interval_seconds),
            'mode': str(self.bot_mode or 'unknown').upper(),
            'testnet': bool(self.bybit_testnet),
            'db_file': str(self.db_file),
            'kill_switch_file': str(self.kill_switch_file),
            'open_positions': int(len(self.positions)),
            'current_balance': float(self.current_balance),
            'total_pnl': float(self.total_pnl),
            'session_pnl': float(session_pnl),
            'session_start_balance': float(self.session_start_balance),
            'daily_drawdown_paused': bool(self.daily_drawdown_paused),
            'manual_entry_paused': bool(self.manual_entry_paused),
        }
        try:
            target = Path(self.status_snapshot_file)
            tmp = target.with_suffix(target.suffix + '.tmp')
            tmp.write_text(json.dumps(snapshot, separators=(',', ':')), encoding='utf-8')
            os.replace(tmp, target)
        except Exception as exc:
            # Never let snapshot I/O crash the trading loop.
            self.logger.debug(f"status snapshot write failed: {type(exc).__name__}: {exc}")

    def serialize_partial_exits(self, partial_exits):
        payload = []
        for item in partial_exits or []:
            time_obj = item.get('time')
            if isinstance(time_obj, datetime.datetime):
                time_value = time_obj.isoformat()
            else:
                time_value = str(time_obj) if time_obj is not None else None

            payload.append({
                'level': float(item.get('level', 0.0)),
                'size': float(item.get('size', 0.0)),
                'pnl': float(item.get('pnl', 0.0)),
                'time': time_value,
            })

        return json.dumps(payload)

    def deserialize_partial_exits(self, raw_json):
        if not raw_json:
            return []

        try:
            items = json.loads(raw_json)
            if not isinstance(items, list):
                return []

            parsed = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                time_value = item.get('time')
                if isinstance(time_value, str):
                    try:
                        time_value = datetime.datetime.fromisoformat(time_value)
                    except Exception:
                        pass
                parsed.append({
                    'level': float(item.get('level', 0.0)),
                    'size': float(item.get('size', 0.0)),
                    'pnl': float(item.get('pnl', 0.0)),
                    'time': time_value,
                })

            return parsed
        except Exception:
            return []

    def load_state(self):
        cursor = self.db.cursor()
        self.positions = {}
        for row in cursor.execute('SELECT * FROM positions').fetchall():
            pos = PaperPosition(
                row['symbol'],
                row['side'],
                row['entry_price'],
                row['quantity'],
                datetime.datetime.fromisoformat(row['timestamp'])
            )
            pos.stop_loss = row['stop_loss']
            pos.trailing_stop_level = row['trailing_stop_level']
            pos.trailing_stop_active = bool(row['trailing_stop_active'])
            pos.peak_pnl_percentage = row['peak_pnl_percentage']
            pos.current_price = row['current_price']
            pos.pnl = row['pnl']
            pos.pnl_percentage = row['pnl_percentage']
            pos.partial_exits = self.deserialize_partial_exits(row['partial_exits_json'])
            pos.native_sl_active = bool(row['native_sl_active'])
            pos.native_tp_active = bool(row['native_tp_active'])
            pos.native_trail_active = bool(row['native_trail_active'])
            pos.native_sl_price = row['native_sl_price']
            pos.native_stops_cancelled_at = row['native_stops_cancelled_at'] if 'native_stops_cancelled_at' in row.keys() else None
            pos.companion_limit_order_id = row['companion_limit_order_id'] if 'companion_limit_order_id' in row.keys() else None
            self.positions[pos.symbol] = pos

        self.closed_trades = []
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.total_pnl = 0.0
        self.current_balance = self.initial_balance

        for row in cursor.execute('SELECT symbol, pnl, pnl_percentage, reason, close_time FROM closed_trades').fetchall():
            self.closed_trades.append({
                'symbol': row['symbol'],
                'pnl': row['pnl'],
                'pnl_pct': row['pnl_percentage'],
                'reason': row['reason'],
                'time': datetime.datetime.fromisoformat(row['close_time'])
            })

        stats = cursor.execute('''
            SELECT
                COUNT(*) AS total_trades,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS winning_trades,
                SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) AS losing_trades,
                COALESCE(SUM(pnl), 0.0) AS total_realized_pnl
            FROM closed_trades
        ''').fetchone()

        partial_stats = cursor.execute('''
            SELECT COALESCE(SUM(pnl), 0.0) AS partial_realized_pnl
            FROM partial_realizations
        ''').fetchone()

        self.total_trades = stats['total_trades'] or 0
        self.winning_trades = stats['winning_trades'] or 0
        self.losing_trades = stats['losing_trades'] or 0
        closed_realized = stats['total_realized_pnl'] or 0.0
        partial_realized = partial_stats['partial_realized_pnl'] or 0.0
        self.total_pnl = closed_realized + partial_realized
        self.current_balance = self.initial_balance + self.total_pnl

        # Prefer persisted runtime state for exact stop/restart continuity.
        state_balance = self.get_state_float('current_balance')
        state_total_pnl = self.get_state_float('total_pnl')
        state_total_trades = self.get_state_int('total_trades')
        state_winning_trades = self.get_state_int('winning_trades')
        state_losing_trades = self.get_state_int('losing_trades')
        state_telegram_last_update_id = self.get_state_int('telegram_last_update_id')
        state_telegram_manual_pause_active = self.get_state_int('telegram_manual_pause_active')
        state_telegram_manual_pause_updated_at = self.get_state_value('telegram_manual_pause_updated_at')
        state_pending_confirmations_json = self.get_state_value('telegram_pending_confirmations_json')
        if state_balance is not None and state_total_pnl is not None:
            self.current_balance = state_balance
            self.total_pnl = state_total_pnl
        if state_total_trades is not None:
            self.total_trades = state_total_trades
        if state_winning_trades is not None:
            self.winning_trades = state_winning_trades
        if state_losing_trades is not None:
            self.losing_trades = state_losing_trades
        if state_telegram_last_update_id is not None:
            self.telegram_last_update_id = max(0, state_telegram_last_update_id)
        if state_telegram_manual_pause_active is not None:
            self.manual_entry_paused = bool(state_telegram_manual_pause_active)
        parsed_manual_override = self._safe_utc_from_iso(state_telegram_manual_pause_updated_at)
        if parsed_manual_override is not None:
            self.manual_override_timestamp_utc = parsed_manual_override

        self.telegram_pending_confirmations = {}
        if isinstance(state_pending_confirmations_json, str) and state_pending_confirmations_json.strip():
            try:
                decoded = json.loads(state_pending_confirmations_json)
            except Exception:
                decoded = {}

            now_utc = datetime.datetime.now(datetime.timezone.utc)
            if isinstance(decoded, dict):
                for chat_id, pending in decoded.items():
                    if not isinstance(pending, dict):
                        continue
                    chat_key = str(chat_id or '').strip()
                    action = str(pending.get('action') or '').strip()
                    expires_at = self._safe_utc_from_iso(pending.get('expires_at_utc'))
                    if not chat_key or not action or expires_at is None or now_utc >= expires_at:
                        continue
                    self.telegram_pending_confirmations[chat_key] = {
                        'chat_id': chat_key,
                        'action': action,
                        'args': pending.get('args') if isinstance(pending.get('args'), dict) else {},
                        'created_at_utc': str(pending.get('created_at_utc') or '').strip(),
                        'expires_at_utc': expires_at.isoformat(),
                        'nonce': str(pending.get('nonce') or uuid.uuid4().hex),
                    }

        self._persist_pending_confirmations()

    def reconcile_positions_on_startup(self):
        if not self.positions:
            return

        self.logger.info('🛠️ Reconciling persisted positions on startup...')
        for symbol, pos in list(self.positions.items()):
            analysis = self.analyze_market(symbol)
            if not analysis:
                self.logger.warning(f'⚠️ Failed to get current price for {symbol} during recovery.')
                continue

            pos.update_price(analysis['current_price'])
            self.persist_position(pos)

            if pos.should_close_for_loss() or pos.should_close_for_trailing_stop() or pos.should_close_for_stop_loss():
                self.logger.info(f'🔄 Recovery closing {symbol} immediately after restart. pnl%={pos.pnl_percentage:.2f}')
                self.close_position(symbol, 'RECOVERY')
            elif pos.should_activate_trailing_stop():
                pos.activate_trailing_stop()
                self.logger.info(f'🎯 Recovery activated trailing stop for {symbol} at {pos.trailing_stop_level:.8f}')
                self.persist_position(pos)

    def calculate_wma(self, source_prices, period=45, offset=2):
        if len(source_prices) < period + offset:
            return None
        prices_for_wma = source_prices[:-(offset) if offset > 0 else None]
        if len(prices_for_wma) < period:
            return None
        weights = list(range(1, period + 1))
        return sum(p * w for p, w in zip(prices_for_wma[-period:], weights)) / sum(weights)

    def calculate_ohlc4(self, ohlcv_data):
        return [(c[1] + c[2] + c[3] + c[4]) / 4 for c in ohlcv_data]

    def confirm_signal(self, ohlcv_data, ohlc4_values, wma_values, current_index, signal_type):
        if signal_type not in ['BUY', 'SELL']:
            return False, []
        prior = current_index - 1
        if prior < 0:
            return False, []

        consec = []
        for i in range(prior, -1, -1):
            diff = ohlc4_values[i] - wma_values[i]
            positive = diff > 0
            if signal_type == 'BUY' and positive:
                consec.append(i)
            elif signal_type == 'SELL' and not positive:
                consec.append(i)
            else:
                break

        if len(consec) < 1:
            return False, []

        if signal_type == 'BUY':
            hh = max(consec, key=lambda i: ohlcv_data[i][2])
            confirmed = ohlcv_data[prior][4] > ohlcv_data[hh][4]
        else:
            ll = min(consec, key=lambda i: ohlcv_data[i][3])
            confirmed = ohlcv_data[prior][4] < ohlcv_data[ll][4]

        return confirmed, consec

    def analyze_market(self, symbol, for_entry=False):
        try:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            ticker = self.exchange.fetch_ticker(symbol)
            ts_ms, ts_source, is_fallback = self.extract_ticker_timestamp_ms(ticker, now_utc)
            if ts_ms is None:
                self.logger.warning(f"⚠️ Missing ticker timestamp for {symbol}; skipping symbol")
                return None

            if is_fallback and symbol not in self.timestamp_fallback_warned:
                self.logger.warning(
                    f"⚠️ Missing exchange timestamp for {symbol}; using {ts_source} fallback"
                )
                self.timestamp_fallback_warned.add(symbol)

            now_ms = int(now_utc.timestamp() * 1000)
            if not is_fallback:
                age_seconds = max(0.0, (now_ms - ts_ms) / 1000.0)
                if age_seconds > self.max_tick_age_seconds:
                    self.logger.warning(
                        f"⚠️ Stale ticker for {symbol}; age={age_seconds:.0f}s > {self.max_tick_age_seconds}s, skipping symbol"
                    )
                    return None

            signature = self.build_ticker_signature(ticker)
            prev_obs = self.tick_observations.get(symbol)
            unchanged_cycles = 0
            if prev_obs and prev_obs.get('ts_ms') == ts_ms and prev_obs.get('signature') == signature:
                unchanged_cycles = prev_obs.get('unchanged_cycles', 0) + 1
                if unchanged_cycles >= self.max_unchanged_tick_cycles:
                    unchanged_seconds = (now_utc - prev_obs['seen_at']).total_seconds()
                    self.logger.warning(
                        f"⚠️ Frozen ticker for {symbol}; timestamp unchanged for {unchanged_seconds:.0f}s, skipping symbol"
                    )
                    self.tick_observations[symbol] = {
                        'ts_ms': ts_ms,
                        'signature': signature,
                        'seen_at': now_utc,
                        'unchanged_cycles': unchanged_cycles,
                    }
                    return None

            self.tick_observations[symbol] = {
                'ts_ms': ts_ms,
                'signature': signature,
                'seen_at': now_utc,
                'unchanged_cycles': unchanged_cycles,
            }

            if for_entry and not self.passes_volume_filter(symbol, ticker):
                return None

            ohlcv = self.exchange.fetch_ohlcv(symbol, '4h', limit=100)
            if not ohlcv or len(ohlcv) < 47:
                return None
            ohlc4_values = self.calculate_ohlc4(ohlcv)
            wma_values = [self.calculate_wma(ohlc4_values[:i+1]) for i in range(len(ohlc4_values))]
            wma = wma_values[-1]
            if wma is None:
                return None
            current_ohlc4 = ohlc4_values[-1]
            atr = self.calculate_atr(ohlcv, period=14)
            atr_ratio = (atr / current_ohlc4) if atr is not None and current_ohlc4 > 0 else 0.0
            diff = current_ohlc4 - wma
            signal_type = 'BUY' if diff > 0 else 'SELL'
            confirmed, consec_bars = self.confirm_signal(ohlcv, ohlc4_values, wma_values, len(ohlcv)-1, signal_type)
            return {
                'symbol': symbol,
                'current_price': current_ohlc4,
                'signal': signal_type,
                'confirmed': confirmed,
                'atr_ratio': atr_ratio,
                'ohlcv': ohlcv,
                'consec_bars': consec_bars,
            }
        except Exception:
            return None

    def open_position(self, analysis):
        symbol = analysis['symbol']
        if symbol in self.positions:
            return False
        if len(self.positions) >= self.max_open_positions:
            self.logger.info(f"⛔ Position cap reached ({self.max_open_positions}); skipping {symbol}")
            return False
        price = analysis['current_price']
        risk_pct = self.entry_risk_pct
        if analysis.get('atr_ratio', 0.0) > self.atr_volatility_cutoff:
            risk_pct *= self.atr_size_scalar

        leverage, leverage_tier = self.get_leverage_for_symbol(symbol)

        gross_notional = self.current_balance * risk_pct * leverage
        net_notional = gross_notional * (1 - self.round_trip_fee_rate)
        gross_qty = gross_notional / price
        qty = net_notional / price
        side = 'long' if analysis['signal'] == 'BUY' else 'short'
        exchange_entry_price = None
        exchange_fill_source = None

        if self.live_execution_enabled:
            order_side = 'buy' if side == 'long' else 'sell'
            order_key = f"entry:{symbol}:{order_side}:{int(time.time() // 60)}"
            ok, order_data = self.submit_market_order(
                symbol=symbol,
                side=order_side,
                quantity=qty,
                reason='entry',
                idempotency_key=order_key,
                leverage=leverage,
            )
            if not ok:
                return False

            if not isinstance(order_data, dict) or not bool(order_data.get('fill_confirmed', False)):
                self.logger.error(
                    f"❌ Entry fill not confirmed for {symbol}; refusing local position open to avoid incorrect SL/TP"
                )
                self.emit_structured_event(
                    'CRITICAL',
                    'entry_fill_not_confirmed',
                    'execution',
                    'Entry fill not confirmed from exchange; local open skipped.',
                    symbol=symbol,
                    values={
                        'side': order_side,
                        'requested_qty': qty,
                        'order_data': order_data,
                    },
                )
                return False

            try:
                confirmed_price = float(order_data.get('avg_fill_price'))
                confirmed_qty = float(order_data.get('filled'))
            except (TypeError, ValueError):
                self.logger.error(
                    f"❌ Invalid confirmed fill payload for {symbol}; order_data={order_data}"
                )
                return False

            if confirmed_price <= 0 or confirmed_qty <= 0:
                self.logger.error(
                    f"❌ Non-positive confirmed fill for {symbol}; price={confirmed_price}, qty={confirmed_qty}"
                )
                return False

            exchange_entry_price = confirmed_price
            exchange_fill_source = str(order_data.get('fill_source') or 'unknown')
            price, qty = confirmed_price, confirmed_qty

        pos = PaperPosition(symbol, side, price, qty, datetime.datetime.now())
        pos.round_trip_fee_rate = self.round_trip_fee_rate
        self.positions[symbol] = pos
        self.persist_position(pos)

        self._place_companion_limit_order(
            pos=pos,
            analysis=analysis,
            leverage=leverage,
        )

        stored_entry_price = float(pos.entry_price)
        entry_diff_bps = None
        if exchange_entry_price is not None and exchange_entry_price > 0:
            entry_diff_bps = ((stored_entry_price - exchange_entry_price) / exchange_entry_price) * 10000.0

        if entry_diff_bps is None:
            self.logger.info(
                f"📏 ENTRY CHECK {symbol}: exchange_entry=n/a, stored_entry={stored_entry_price:.8f}, "
                f"diff_bps=n/a"
            )
        else:
            self.logger.info(
                f"📏 ENTRY CHECK {symbol}: exchange_entry={exchange_entry_price:.8f}, "
                f"stored_entry={stored_entry_price:.8f}, diff_bps={entry_diff_bps:+.2f}, "
                f"fill_source={exchange_fill_source}"
            )

        # Copilot prompt: Keep native-stop failures non-blocking; only persist flags confirmed by exchange.
        self._apply_native_initial_protection(pos)

        self.total_trades += 1
        self.persist_runtime_state()
        self.logger.info(
            f"🆕 OPENED {side.upper()} {symbol} @ {price:.8f}, gross_qty={gross_qty:.6f}, net_qty={qty:.6f}, "
            f"atr_ratio={analysis.get('atr_ratio', 0.0):.4f}, leverage={leverage:.1f}x ({leverage_tier})"
        )
        self.emit_structured_event(
            'INFO',
            'position_opened',
            'execution',
            'Position opened.',
            symbol=symbol,
            values={
                'side': side,
                'entry_price': price,
                'gross_qty': gross_qty,
                'net_qty': qty,
                'atr_ratio': analysis.get('atr_ratio', 0.0),
                'leverage': leverage,
                'leverage_tier': leverage_tier,
            },
        )
        return True

    def _place_companion_limit_order(self, pos, analysis, leverage):
        signal_type = analysis.get('signal')
        ohlcv = analysis.get('ohlcv') or []
        consec_bars = analysis.get('consec_bars') or []

        trigger_price, target_idx = self.compute_companion_limit_price(ohlcv, consec_bars, signal_type)
        if trigger_price is None or trigger_price <= 0:
            self.emit_structured_event(
                'WARNING',
                'companion_limit_skipped',
                'execution',
                'Could not compute companion limit price; skipping companion limit.',
                symbol=pos.symbol,
                values={
                    'signal': signal_type,
                    'consec_bar_count': len(consec_bars),
                },
            )
            return

        target_bar = ohlcv[target_idx] if 0 <= target_idx < len(ohlcv) else None
        bar_high = float(target_bar[2]) if target_bar else None
        bar_low = float(target_bar[3]) if target_bar else None
        bar_close = float(target_bar[4]) if target_bar else None

        order_side = 'buy' if pos.side == 'long' else 'sell'
        qty = float(pos.quantity)

        if not self.live_execution_enabled:
            self.logger.info(
                f"🪜 COMPANION LIMIT (paper) {order_side.upper()} {pos.symbol} "
                f"qty={qty:.6f} @ {trigger_price:.8f} "
                f"(consec_bars={len(consec_bars)}, target_idx={target_idx})"
            )
            self.emit_structured_event(
                'INFO',
                'companion_limit_logged',
                'execution',
                'Companion limit order logged in paper mode (no exchange placement).',
                symbol=pos.symbol,
                values={
                    'side': order_side,
                    'quantity': qty,
                    'trigger_price': trigger_price,
                    'signal': signal_type,
                    'consec_bar_count': len(consec_bars),
                    'target_bar_index': target_idx,
                    'target_bar_high': bar_high,
                    'target_bar_low': bar_low,
                    'target_bar_close': bar_close,
                },
            )
            return

        order_key = f"entry_limit:{pos.symbol}:{order_side}:{int(time.time() // 60)}"
        ok, order_data = self.submit_limit_order(
            symbol=pos.symbol,
            side=order_side,
            quantity=qty,
            price=trigger_price,
            reason='entry',
            idempotency_key=order_key,
            leverage=leverage,
        )
        if not ok:
            self.emit_structured_event(
                'WARNING',
                'companion_limit_skipped',
                'execution',
                'Companion limit order placement failed; market position retained.',
                symbol=pos.symbol,
                values={
                    'side': order_side,
                    'quantity': qty,
                    'trigger_price': trigger_price,
                    'signal': signal_type,
                },
            )
            return

        order_id = None
        if isinstance(order_data, dict):
            order_id = order_data.get('id') or order_data.get('order_id')
        if order_id is None:
            order_id = ''
        pos.companion_limit_order_id = str(order_id) if order_id else None
        self.persist_position(pos)

        self.logger.info(
            f"🪜 COMPANION LIMIT {order_side.upper()} {pos.symbol} "
            f"qty={qty:.6f} @ {trigger_price:.8f} order_id={pos.companion_limit_order_id} "
            f"(consec_bars={len(consec_bars)}, target_idx={target_idx})"
        )
        self.emit_structured_event(
            'INFO',
            'companion_limit_placed',
            'execution',
            'Companion limit order placed alongside market entry.',
            symbol=pos.symbol,
            values={
                'side': order_side,
                'quantity': qty,
                'trigger_price': trigger_price,
                'signal': signal_type,
                'consec_bar_count': len(consec_bars),
                'target_bar_index': target_idx,
                'target_bar_high': bar_high,
                'target_bar_low': bar_low,
                'target_bar_close': bar_close,
                'order_id': pos.companion_limit_order_id,
            },
        )

    def persist_position(self, pos):
        cursor = self.db.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO positions (
                symbol, side, entry_price, quantity, timestamp,
                stop_loss, trailing_stop_level, trailing_stop_active,
                peak_pnl_percentage, current_price, pnl, pnl_percentage,
                partial_exits_json, native_sl_active, native_tp_active,
                native_trail_active, native_sl_price, native_stops_cancelled_at,
                companion_limit_order_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ''', (
            pos.symbol,
            pos.side,
            pos.entry_price,
            pos.quantity,
            pos.timestamp.isoformat(),
            pos.stop_loss,
            pos.trailing_stop_level,
            int(pos.trailing_stop_active),
            pos.peak_pnl_percentage,
            pos.current_price,
            pos.pnl,
            pos.pnl_percentage,
            self.serialize_partial_exits(pos.partial_exits),
            int(bool(getattr(pos, 'native_sl_active', False))),
            int(bool(getattr(pos, 'native_tp_active', False))),
            int(bool(getattr(pos, 'native_trail_active', False))),
            getattr(pos, 'native_sl_price', None),
            getattr(pos, 'native_stops_cancelled_at', None),
            getattr(pos, 'companion_limit_order_id', None),
        ))
        self.db.commit()

    def _apply_native_initial_protection(self, pos):
        if not self.live_execution_enabled or self.order_executor is None:
            return

        result = self.order_executor.set_native_initial_protection(
            symbol=pos.symbol,
            side=pos.side,
            entry_price=pos.entry_price,
            quantity=pos.quantity,
        )
        pos.native_sl_active = bool(result.get('native_sl_active', False))
        pos.native_tp_active = bool(result.get('native_tp_active', False))
        pos.native_trail_active = bool(result.get('native_trail_active', False))
        pos.native_sl_price = result.get('native_sl_price')
        self.persist_position(pos)

        if not result.get('ok', False):
            self.logger.warning(
                '⚠️ Native initial protection warning for %s: warnings=%s',
                pos.symbol,
                result.get('warnings', []),
            )

    def _apply_native_trailing_protection(self, pos):
        if not self.live_execution_enabled or self.order_executor is None:
            return

        result = self.order_executor.set_native_trailing(pos.symbol)
        if result.get('ok', False):
            pos.native_sl_active = False
            pos.native_tp_active = False
            pos.native_trail_active = True
            pos.native_sl_price = None
            self.persist_position(pos)
            return

        self.logger.warning(
            '⚠️ Native trailing protection warning for %s: warnings=%s',
            pos.symbol,
            result.get('warnings', []),
        )

    def _clear_native_protection_on_close(self, pos):
        # Copilot prompt: Close flow must not block on exchange-stop cleanup; clear local flags regardless of API outcome.
        cancelled_at = None
        if self.live_execution_enabled and self.order_executor is not None:
            cancel_method = getattr(self.order_executor, 'cancel_all_native_stops', None)
            if not callable(cancel_method):
                cancel_method = getattr(self.order_executor, 'clear_native_protection', None)

            if callable(cancel_method):
                result = cancel_method(pos.symbol)
            else:
                result = {
                    'ok': False,
                    'warnings': [{'operation': 'cancel_all_native_stops', 'error_type': 'missing_method', 'error': 'No native stop cancel method available'}],
                }
            if result.get('ok', False):
                cancelled_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
            if not result.get('ok', False):
                self.logger.warning(
                    '⚠️ Native protection clear warning for %s: warnings=%s',
                    pos.symbol,
                    result.get('warnings', []),
                )

        self._cancel_companion_limit_order(pos)

        pos.native_sl_active = False
        pos.native_tp_active = False
        pos.native_trail_active = False
        pos.native_sl_price = None
        pos.native_stops_cancelled_at = cancelled_at
        self.persist_position(pos)

    def _cancel_companion_limit_order(self, pos):
        order_id = getattr(pos, 'companion_limit_order_id', None)
        if not order_id:
            return

        if self.live_execution_enabled and self.order_executor is not None:
            cancel_method = getattr(self.order_executor, 'cancel_order_by_id', None)
            if callable(cancel_method):
                result = cancel_method(pos.symbol, order_id)
            else:
                result = {
                    'ok': False,
                    'warnings': [{'operation': 'cancel_order_by_id', 'error_type': 'missing_method', 'error': 'No cancel-by-id method available'}],
                }
            if not result.get('ok', False):
                self.logger.warning(
                    '⚠️ Companion limit cancel warning for %s order_id=%s: warnings=%s',
                    pos.symbol,
                    order_id,
                    result.get('warnings', []),
                )
                self.emit_structured_event(
                    'WARNING',
                    'companion_limit_cancel_failed',
                    'execution',
                    'Companion limit cancel failed; order may still be live on exchange.',
                    symbol=pos.symbol,
                    values={'order_id': order_id, 'warnings': result.get('warnings', [])},
                )
            else:
                self.emit_structured_event(
                    'INFO',
                    'companion_limit_cancelled',
                    'execution',
                    'Companion limit order cancelled on position close.',
                    symbol=pos.symbol,
                    values={'order_id': order_id},
                )

        pos.companion_limit_order_id = None

    def remove_persisted_position(self, symbol):
        cursor = self.db.cursor()
        cursor.execute('DELETE FROM positions WHERE symbol = ?', (symbol,))
        self.db.commit()

    def record_closed_trade(self, pos, reason):
        cursor = self.db.cursor()
        cursor.execute('''
            INSERT INTO closed_trades (
                symbol, side, entry_price, exit_price, quantity,
                pnl, pnl_percentage, reason, open_time, close_time
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
        ''', (
            pos.symbol,
            pos.side,
            pos.entry_price,
            pos.current_price,
            pos.quantity,
            pos.pnl,
            pos.pnl_percentage,
            reason,
            pos.timestamp.isoformat(),
            datetime.datetime.now().isoformat()
        ))
        self.db.commit()

    def record_partial_realization(self, symbol, level, size, pnl):
        cursor = self.db.cursor()
        cursor.execute('''
            INSERT INTO partial_realizations (
                symbol, level, size, pnl, event_time
            ) VALUES (?,?,?,?,?)
        ''', (
            symbol,
            level,
            size,
            pnl,
            datetime.datetime.now().isoformat()
        ))
        self.db.commit()

    def close_position(self, symbol, reason, exchange_already_closed=False):
        pos = self.positions.pop(symbol, None)
        if not pos:
            return

        if self.live_execution_enabled and pos.quantity > 0 and not exchange_already_closed:
            exit_side = 'sell' if pos.side == 'long' else 'buy'
            order_key = f"exit:{symbol}:{exit_side}:{int(time.time() // 60)}:{reason}"
            ok, order_data = self.submit_market_order(
                symbol=symbol,
                side=exit_side,
                quantity=pos.quantity,
                reason=reason,
                idempotency_key=order_key,
            )
            if not ok:
                # The close order was rejected. This most commonly happens because
                # the native SL already fired (position is flat) and our reduceOnly
                # order was correctly rejected. Check the live position size before
                # deciding whether to retry.
                live_size = None
                if self.order_executor is not None:
                    live_size = self.order_executor.fetch_live_position_size(symbol)

                if live_size is not None and live_size <= 0.0:
                    # Exchange confirms no open position — native SL already closed it.
                    # Fall through to local accounting so the bot's state stays clean.
                    self.logger.warning(
                        f"⚠️ Close order rejected for {symbol} but exchange shows no open "
                        f"position — native SL likely fired first. Cleaning up locally as "
                        f"'native_sl_closed'. Local PnL may differ slightly from exchange; "
                        f"next balance sync will reconcile."
                    )
                    reason = 'native_sl_closed'
                    # Use current tracked price as best-effort exit price.
                else:
                    # Genuine failure or API error (live_size is None) — re-queue for
                    # retry next cycle. Do NOT fall through to accounting.
                    self.positions[symbol] = pos
                    return

            fill_price, filled_qty = self.extract_order_fill(
                order_data,
                fallback_price=pos.current_price,
                fallback_qty=pos.quantity,
            )
            if filled_qty <= 0:
                self.logger.warning(f"⚠️ Exit order returned zero fill for {symbol}; deferring close")
                self.positions[symbol] = pos
                return
            pos.quantity = min(pos.quantity, filled_qty)
            pos.update_price(fill_price)

        self._clear_native_protection_on_close(pos)

        self.current_balance += pos.pnl
        self.total_pnl += pos.pnl
        if pos.pnl > 0:
            self.winning_trades += 1
            self.consecutive_losses = 0
        else:
            self.losing_trades += 1
            self.consecutive_losses += 1
            if self.consecutive_losses >= self.max_consecutive_losses:
                cooldown_hours = self.cooldown_candles * 4
                now_utc = datetime.datetime.now(datetime.timezone.utc)
                self.cooldown_until_utc = now_utc + datetime.timedelta(hours=cooldown_hours)
                self.logger.warning(
                    f"⏸️ Consecutive-loss cooldown active until {self.cooldown_until_utc.isoformat()}"
                )
                self.emit_structured_event(
                    'WARNING',
                    'circuit_breaker_triggered',
                    'risk',
                    'Consecutive-loss cooldown activated.',
                    values={
                        'breaker_name': 'consecutive_losses',
                        'reason': 'max_consecutive_losses_reached',
                        'cooldown_seconds': cooldown_hours * 3600,
                    },
                )
        self.closed_trades.append({'symbol': symbol, 'pnl': pos.pnl, 'pnl_pct': pos.pnl_percentage, 'reason': reason, 'time': datetime.datetime.now()})
        self.record_closed_trade(pos, reason)
        self.remove_persisted_position(symbol)
        self.persist_runtime_state()
        self.logger.info(
            f"🔒 CLOSED {symbol} ({reason}) gross_pnl={pos.gross_pnl:.2f}, fees={pos.fee_cost:.2f}, "
            f"net_pnl={pos.pnl:.2f}, pnl%={pos.pnl_percentage:.2f}"
        )
        self.emit_structured_event(
            'INFO',
            'position_closed',
            'execution',
            'Position closed.',
            symbol=symbol,
            values={
                'reason': reason,
                'gross_pnl': pos.gross_pnl,
                'fees': pos.fee_cost,
                'net_pnl': pos.pnl,
                'pnl_percentage': pos.pnl_percentage,
                'exchange_already_closed': bool(exchange_already_closed),
            },
        )

    def reconcile_runtime_positions_with_exchange(self):
        if not self.live_execution_enabled:
            return

        if not self.positions:
            return

        try:
            exchange_positions = self.startup_reconciler.fetch_open_exchange_positions()
        except Exception as exc:
            self.logger.warning(f"⚠️ Runtime reconciliation skipped: failed to fetch exchange positions ({type(exc).__name__}: {exc})")
            return

        local_symbols = list(self.positions.keys())
        exchange_symbols = set(exchange_positions.keys())

        for symbol in local_symbols:
            pos = self.positions.get(symbol)
            if pos is None:
                continue

            ex_pos = exchange_positions.get(symbol)
            if ex_pos is None:
                reconstructed_close = self.startup_reconciler.reconstruct_close_from_trades(
                    symbol=symbol,
                    side=pos.side,
                    open_quantity=pos.quantity,
                )
                if reconstructed_close is not None and reconstructed_close > 0:
                    pos.update_price(reconstructed_close)
                    self.persist_position(pos)

                self.logger.warning(
                    f"⚠️ Runtime reconciliation detected local-only open position for {symbol}; "
                    f"closing locally (exchange already flat)."
                )
                self.emit_structured_event(
                    'WARNING',
                    'runtime_local_missing_on_exchange',
                    'reconciliation',
                    'Runtime reconciliation found local open position missing on exchange; local state was closed.',
                    symbol=symbol,
                    values={
                        'reconstructed_close_price': reconstructed_close,
                    },
                )
                self.close_position(symbol, 'runtime_exchange_flat_reconciled', exchange_already_closed=True)
                continue

            try:
                exchange_qty = abs(float(ex_pos.get('quantity') or 0.0))
            except (TypeError, ValueError):
                exchange_qty = 0.0

            if exchange_qty <= 0.0:
                continue

            local_qty = abs(float(pos.quantity or 0.0))
            qty_diff_pct = abs(local_qty - exchange_qty) / max(local_qty, exchange_qty, 1e-12) * 100.0

            exchange_entry_raw = ex_pos.get('entry_price')
            try:
                exchange_entry = float(exchange_entry_raw or 0.0)
            except (TypeError, ValueError):
                exchange_entry = 0.0

            exchange_side = str(ex_pos.get('side') or '').strip().lower()
            if exchange_side == 'buy':
                exchange_side = 'long'
            elif exchange_side == 'sell':
                exchange_side = 'short'

            if qty_diff_pct > 1.0:
                self.logger.warning(
                    f"⚠️ Runtime reconciliation quantity mismatch for {symbol}: "
                    f"local={local_qty:.8f}, exchange={exchange_qty:.8f}. Updating local state to exchange truth."
                )
                pos.quantity = exchange_qty
                if exchange_entry > 0.0:
                    pos.entry_price = exchange_entry
                if exchange_side in {'long', 'short'}:
                    pos.side = exchange_side
                self.persist_position(pos)
                self.emit_structured_event(
                    'WARNING',
                    'runtime_position_mismatch_exchange_truth',
                    'reconciliation',
                    'Runtime reconciliation updated local position values to exchange truth.',
                    symbol=symbol,
                    values={
                        'local_quantity_before': local_qty,
                        'exchange_quantity': exchange_qty,
                        'qty_diff_pct': qty_diff_pct,
                        'exchange_entry_price': exchange_entry if exchange_entry > 0.0 else None,
                        'exchange_side': exchange_side,
                    },
                )

        # Exchange-only positions are still handled as critical during startup gate.
        # Runtime handling intentionally avoids auto-creating local records to prevent silent state invention.

    def update_positions(self):
        to_close = []
        for symbol, pos in list(self.positions.items()):
            analysis = self.analyze_market(symbol, for_entry=False)
            if not analysis:
                continue
            pos.update_price(analysis['current_price'])
            self.persist_position(pos)

            # Hard stop is checked immediately after every price refresh.
            if pos.should_close_for_loss():
                to_close.append((symbol, 'stop_loss'))
                continue

            # Partial profit usecases
            partial = pos.should_take_partial_profit()
            if partial:
                idx, level = partial
                if self.live_execution_enabled:
                    partial_qty = pos.quantity * pos.profit_taking_sizes[idx]
                    if partial_qty > 0:
                        partial_side = 'sell' if pos.side == 'long' else 'buy'
                        order_key = f"partial:{symbol}:{partial_side}:{int(time.time() // 60)}:{idx}"
                        ok, order_data = self.submit_market_order(
                            symbol=symbol,
                            side=partial_side,
                            quantity=partial_qty,
                            reason='partial_profit',
                            idempotency_key=order_key,
                        )
                        if not ok:
                            continue
                        fill_price, filled_qty = self.extract_order_fill(
                            order_data,
                            fallback_price=pos.current_price,
                            fallback_qty=partial_qty,
                        )
                        if filled_qty <= 0:
                            continue
                        pos.update_price(fill_price)
                        original_qty = pos.quantity
                        realized_ratio = min(1.0, filled_qty / original_qty) if original_qty > 0 else 0.0
                        partial_pnl = pos.pnl * realized_ratio
                        pos.partial_exits.append({'level': level, 'size': realized_ratio, 'pnl': partial_pnl, 'time': datetime.datetime.now()})
                        pos.quantity = max(0.0, original_qty - filled_qty)
                        self.current_balance += partial_pnl
                        self.total_pnl += partial_pnl
                        self.record_partial_realization(symbol, level, realized_ratio, partial_pnl)
                        self.persist_runtime_state()
                        self.logger.info(f"💰 LIVE PARTIAL EXIT {symbol} at {level*100:.1f}% -> {partial_pnl:.2f}")
                        self.emit_structured_event(
                            'INFO',
                            'partial_exit',
                            'execution',
                            'Partial profit realized from exchange fill.',
                            symbol=symbol,
                            values={
                                'level': level,
                                'size': realized_ratio,
                                'pnl': partial_pnl,
                                'filled_qty': filled_qty,
                                'fill_price': fill_price,
                            },
                        )
                        self.persist_position(pos)
                        if pos.quantity <= 0:
                            to_close.append((symbol, 'partial_exit_complete'))
                            continue

                partial_pnl = pos.take_partial_profit(idx, level)
                self.current_balance += partial_pnl
                self.total_pnl += partial_pnl
                self.record_partial_realization(symbol, level, pos.profit_taking_sizes[idx], partial_pnl)
                self.persist_runtime_state()
                self.logger.info(f"💰 PARTIAL EXIT {symbol} at {level*100:.1f}% -> {partial_pnl:.2f}")
                self.emit_structured_event(
                    'INFO',
                    'partial_exit',
                    'execution',
                    'Partial profit realized.',
                    symbol=symbol,
                    values={
                        'level': level,
                        'size': pos.profit_taking_sizes[idx],
                        'pnl': partial_pnl,
                    },
                )
                self.persist_position(pos)
                if pos.quantity <= 0:
                    to_close.append((symbol, 'partial_exit_complete'))
                    continue

            if pos.should_activate_trailing_stop():
                pos.activate_trailing_stop()
                self.logger.info(f"🎯 TRAILING ACTIVATED {symbol} level={pos.trailing_stop_level:.8f}")
                # Copilot prompt: When trailing activates, switch exchange protection from fixed SL/TP to trailing fallback.
                self._apply_native_trailing_protection(pos)
                self.persist_position(pos)

            if pos.trailing_stop_active and pos.update_trailing_stop():
                self.logger.info(f"📈 TRAIL UPDATED {symbol} level={pos.trailing_stop_level:.8f}")
                self.persist_position(pos)

            if pos.should_close_for_trailing_stop():
                to_close.append((symbol, 'TRAILING_STOP'))
                continue

            # Static SL from old rule is redundant - trailing stop takes over
            # if pos.should_set_stop_loss() and pos.stop_loss is None:
            #     pos.set_static_stop_loss()
            #     self.logger.info(f"📌 STATIC SL SET {symbol} stop_loss={pos.stop_loss:.8f}")

            if pos.should_close_for_stop_loss():
                to_close.append((symbol, 'SL_HIT'))
                continue

            if pos.should_close_for_time(self.max_hold_minutes):
                to_close.append((symbol, 'time_exit'))
                continue

        for symbol, reason in to_close:
            self.close_position(symbol, reason)

    def display_status(self):
        self.logger.info('--- BOT STATUS ---')
        self.logger.info(f"Balance: {self.current_balance:.2f}, PnL: {self.total_pnl:.2f}, trades: {self.total_trades}, wins: {self.winning_trades}, losses: {self.losing_trades}")
        self.logger.info(f"Open positions: {len(self.positions)}")
        if self.positions:
            self.logger.info(
                f"{'Symbol':<20} {'Side':<6} {'Entry Price':<14} {'Current Price':<14} {'P&L':<10} {'P&L %':<8} {'Peak %':<8} {'Trail':<14} {'TS Active':<9}"
            )
            self.logger.info('-' * 120)
            for symbol, pos in self.positions.items():
                trail_str = f"{pos.trailing_stop_level:.8f}" if pos.trailing_stop_level is not None else 'None'
                ts_active_str = 'Yes' if pos.trailing_stop_active else 'No'
                self.logger.info(
                    f"{symbol:<20} {pos.side:<6} {pos.entry_price:<14.8f} {pos.current_price:<14.8f} "
                    f"{pos.pnl:<10.2f} {pos.pnl_percentage:<8.2f}% {pos.peak_pnl_percentage:<8.2f}% {trail_str:<14} {ts_active_str:<9}"
                )
        else:
            self.logger.info('No open positions')

    def run(self):
        self.logger.info('🚀 Starting paper_bot_v2...')
        # In multi-tenant mode, advertise our PID under the tenant directory
        # so the sidecar's startup reconciler can find us after a restart
        # without sweeping /proc. Best-effort: a write failure is logged but
        # doesn't stop the bot from running.
        if self.tenant_paths is not None:
            try:
                self.tenant_paths.pid.parent.mkdir(parents=True, exist_ok=True)
                self.tenant_paths.pid.write_text(str(os.getpid()), encoding='utf-8')
            except OSError as exc:
                self.logger.warning(
                    f"⚠️ Could not write PID file at {self.tenant_paths.pid}: "
                    f"{type(exc).__name__}: {exc}"
                )
        self.logger.info(
            f"🧭 Environment: mode={self.bot_mode}, testnet={self.bybit_testnet}, kill_switch_file={self.kill_switch_file}"
        )
        self.logger.info(
            '🎯 Entry universe: %s active symbols from %s',
            len(self.usdc_swaps),
            self.symbol_allowlist_source,
        )

        if Path(self.kill_switch_file).exists():
            self.logger.critical(f"🛑 Kill switch detected at startup: {self.kill_switch_file}")
            self.persist_runtime_state()
            self.write_status_snapshot()
            return

        self.write_status_snapshot()
        self.maybe_send_scheduled_pulse(trigger='startup')

        cycle = 0
        while True:
            loop_started_at = time.perf_counter()
            if self.kill_switch_monitor.check(cycle + 1):
                self.persist_runtime_state()
                self.display_status()
                break

            if self.shutdown_requested:
                self.persist_runtime_state()
                break

            cycle += 1
            self.loop_cycle_count = cycle
            self.logger.info(f"\n🔄 Cycle {cycle} @ {datetime.datetime.now()}")
            self.maybe_send_scheduled_pulse(trigger='loop')
            self.poll_telegram_commands_once(cycle)
            self.sync_account_balance(force=False)
            self.reset_daily_session_if_needed()
            self.update_daily_drawdown_pause()
            self.reconcile_runtime_positions_with_exchange()
            self.update_positions()

            signals = 0
            should_scan_entries = (cycle == 1) or self.is_signal_window()
            if should_scan_entries:
                if cycle == 1 and not self.is_signal_window():
                    self.logger.info('🚦 Cycle 1 bootstrap: evaluating new entry signals outside 4H window')
                else:
                    self.logger.info('🕓 4H close window active: evaluating new entry signals')
                regime_signal = self.fetch_btc_regime_signal()
                self.last_regime_signal = regime_signal or 'UNAVAILABLE'
                if regime_signal is None:
                    self.logger.warning('⚠️ BTC regime unavailable; skipping new entries this window')
                else:
                    self.logger.info(f'📈 BTC regime gate active: {regime_signal}-only entries')
                for symbol in self.usdc_swaps:
                    gate_reason = self.entry_gate_block_reason()
                    if gate_reason == 'manual_pause':
                        self.logger.info('⏸️ Manual pause active: skipping new entries')
                        break
                    if gate_reason == 'daily_drawdown_pause':
                        self.logger.info('🛑 Daily drawdown pause active: skipping new entries')
                        break
                    if gate_reason == 'loss_cooldown':
                        self.logger.info(f"⏸️ Loss cooldown active until {self.cooldown_until_utc.isoformat()}: skipping new entries")
                        break
                    if regime_signal is None:
                        break
                    if len(self.positions) >= self.max_open_positions:
                        self.logger.info(f"⛔ Position cap reached ({self.max_open_positions}); stopping signal scan")
                        break
                    anal = self.analyze_market(symbol, for_entry=True)
                    if anal and anal['confirmed']:
                        if anal['signal'] != regime_signal:
                            continue
                        if self.open_position(anal):
                            signals += 1
                    time.sleep(0.05)
            else:
                self.logger.info('⏭️ Outside 4H close window: skipping new entry scan this cycle')

            self.logger.info(f"Signals confirmed this cycle: {signals}")
            if cycle % 6 == 0 or signals > 0 or len(self.positions) > 0:
                self.display_status()

            funding_delta = self.funding_tracker.track_open_positions(self.positions.values(), time.time())
            if funding_delta != 0.0:
                self.current_balance += funding_delta
                self.total_pnl += funding_delta
                self.persist_runtime_state()
                self.emit_structured_event(
                    'INFO',
                    'funding_pnl_applied',
                    'funding',
                    'Funding payment applied to reported PnL.',
                    values={'funding_delta': funding_delta, 'current_balance': self.current_balance, 'total_pnl': self.total_pnl},
                )

            self.persist_runtime_state()
            self.write_status_snapshot()

            cycle_time_ms = (time.perf_counter() - loop_started_at) * 1000.0
            self.emit_structured_event(
                'INFO',
                'loop_cycle_completed',
                'main_loop',
                'Loop cycle completed.',
                values={
                    'cycle_index': cycle,
                    'cycle_time_ms': cycle_time_ms,
                    'open_positions': len(self.positions),
                    'signals_confirmed': signals,
                },
            )

            time.sleep(self.loop_interval_seconds)

        return self.shutdown_exit_code



# Backward compatibility for scripts still importing the legacy class name.
PaperTradingBotV2 = Aribot


if __name__ == '__main__':
    load_dotenv(override=True)
    emoji_mode, remaining_argv = parse_emoji_mode_args(sys.argv[1:])
    runtime_args = parse_runtime_args(remaining_argv)
    symbol_allowlist, symbol_allowlist_source = resolve_symbol_focus_args(runtime_args)

    # Multi-tenant: when --user-id is present (or ARIBOT_USER_ID is set in
    # the spawn env by the sidecar), resolve all paths under
    # <ARIBOT_ARTIFACT_DIR>/tenants/<user_id>/ via TenantRegistry. Without
    # --user-id, the bot stays in legacy single-tenant mode.
    bot_tenant_paths = None
    if runtime_args.user_id:
        from tenant_registry import TenantRegistry
        artifact_dir = Path(os.getenv('ARIBOT_ARTIFACT_DIR', '.aribot')).resolve()
        bot_tenant_paths = TenantRegistry(artifact_dir).paths_for(runtime_args.user_id)
        # Override kill_switch_env so the secret loader's pre-Aribot
        # kill-switch precondition check uses the per-tenant path.
        os.environ['KILL_SWITCH_FILE'] = str(bot_tenant_paths.kill_switch)

    # Credential resolution priority (locked-in plan):
    #   1. ARIBOT_CRED_PIPE set (sidecar handoff)  → load from pipe
    #   2. mode == 'live' AND no pipe              → REFUSE; LIVE requires
    #                                                 iOS-pushed keys
    #   3. otherwise                               → SecretLoader/.env path
    #                                                 (PAPER works keyless,
    #                                                 SHADOW requires .env)
    try:
        bot_mode_env = os.getenv('BOT_MODE', 'paper').strip().lower()
        bybit_testnet_env = SecretLoader._parse_bool(os.getenv('BYBIT_TESTNET'), default=True)
        kill_switch_env = os.getenv('KILL_SWITCH_FILE', 'kill_switch.flag').strip() or 'kill_switch.flag'

        pipe_creds = None
        if os.environ.get('ARIBOT_CRED_PIPE') and os.environ.get('ARIBOT_CRED_TOKEN'):
            try:
                from credential_pipe import read_from_env as _read_pipe_creds
                pipe_creds = _read_pipe_creds()
            except Exception as pipe_exc:
                print(f"Startup validation failed: credential pipe handoff failed: {pipe_exc}")
                raise SystemExit(2)

        if pipe_creds is not None:
            # Sidecar already validated against Bybit at push time, so we skip
            # the redundant /v5/user/query-api roundtrip and just enforce the
            # kill-switch precondition.
            SecretLoader._assert_kill_switch_not_triggered(kill_switch_env)
            startup_secrets = BotSecrets(
                bot_mode=bot_mode_env if bot_mode_env in {'paper', 'shadow', 'live'} else 'paper',
                bybit_testnet=bybit_testnet_env,
                kill_switch_file=kill_switch_env,
                read_api_key=pipe_creds.read_api_key,
                read_api_secret=pipe_creds.read_api_secret,
                trade_api_key=pipe_creds.trade_api_key,
                trade_api_secret=pipe_creds.trade_api_secret,
            )
            startup_secret_loader = SecretLoader()
            print(
                "Startup secret validation passed via iOS vault "
                f"(mode={startup_secrets.bot_mode}, testnet={startup_secrets.bybit_testnet}, "
                f"fingerprint={pipe_creds.fingerprint}, "
                f"config_fingerprint={startup_secret_loader.config_fingerprint(startup_secrets)[:12]}...)"
            )
        else:
            if bot_mode_env == 'live':
                print(
                    "Startup validation failed: LIVE mode requires iOS-pushed credentials. "
                    "Start the bot via the iOS app (POST /start) after submitting Bybit keys. "
                    "Direct CLI launch is disabled in LIVE mode."
                )
                raise SystemExit(2)
            startup_secret_loader = SecretLoader()
            startup_secrets = startup_secret_loader.load()
            startup_secret_loader.validate_startup(startup_secrets)
            print(
                "Startup secret validation passed "
                f"(mode={startup_secrets.bot_mode}, testnet={startup_secrets.bybit_testnet}, "
                f"config_fingerprint={startup_secret_loader.config_fingerprint(startup_secrets)[:12]}...)"
            )
    except SecretValidationError as exc:
        print(f"Startup validation failed: {exc}")
        raise SystemExit(2)

    try:
        bot = Aribot(
            startup_secrets=startup_secrets,
            emoji_mode=emoji_mode,
            symbol_allowlist=symbol_allowlist,
            symbol_allowlist_source=symbol_allowlist_source,
            tenant_paths=bot_tenant_paths,
        )
        bot.verify_telegram_readiness()
    except RuntimeError as exc:
        print(f"Startup readiness failed: {exc}")
        raise SystemExit(3)

    try:
        exit_code = bot.run()
    except KeyboardInterrupt:
        bot.logger.info('🛑 Stopped by user')
        bot.persist_runtime_state()
        bot.display_status()
        exit_code = 0
    sys.exit(exit_code or 0)
