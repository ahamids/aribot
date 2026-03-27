#!/usr/bin/env python3
"""
Paper Trading Bot v2 - USDC Swap Markets WMA Analysis
Based on 45-period Weighted Moving Average using (O+H+L+C)/4 as source with offset 2
Runs in a loop, analyzes signals every 5 minutes, manages paper positions with advanced position management.
"""

import ccxt
import sqlite3
import time
import datetime
import logging
import json
from pathlib import Path

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
        self.profit_taking_sizes = [0.30, 0.30, 0.40]   # 30%, 30%, 40%
        self.partial_exits = []

        # Revised trailing stop settings from improvement report
        self.trailing_stop_buffer = 0.015  # 1.5% from peak
        self.trailing_stop_active = False
        self.trailing_stop_trigger = 0.02  # activate at 2% profit

    def update_price(self, current_price):
        self.current_price = current_price
        if self.side == 'long':
            self.gross_pnl = (current_price - self.entry_price) * self.quantity
        else:
            self.gross_pnl = (self.entry_price - current_price) * self.quantity

        avg_notional = ((self.entry_price + current_price) / 2.0) * self.quantity
        self.fee_cost = avg_notional * self.round_trip_fee_rate
        self.pnl = self.gross_pnl - self.fee_cost
        entry_notional = self.entry_price * self.quantity
        if entry_notional > 0:
            self.pnl_percentage = (self.pnl / entry_notional) * 100
        else:
            self.pnl_percentage = 0.0

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
        return (datetime.datetime.now() - self.timestamp).total_seconds() / 60.0

    def should_close_for_time(self, max_minutes=1440):
        return self.age_minutes() >= max_minutes


class PaperTradingBotV2:
    def __init__(self):
        self.setup_logging()
        self.exchange = ccxt.bybit()
        self.positions = {}
        self.closed_trades = []
        self.initial_balance = 10000.0
        self.current_balance = self.initial_balance
        self.total_pnl = 0.0
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.max_open_positions = 6
        self.max_tick_age_seconds = 600
        self.min_24h_volume_usdc = 100_000
        self.entry_risk_pct = 0.015
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
        self.tick_observations = {}
        self.timestamp_fallback_warned = set()

        self.markets = self.exchange.load_markets()
        self.usdc_swaps = [symbol for symbol in self.markets.keys() if self.markets[symbol].get('type') == 'swap' and 'USDC' in symbol]
        self.btc_regime_symbol = self.resolve_btc_regime_symbol()

        self.db_file = 'paper_bot_v2.db'
        self.db = sqlite3.connect(self.db_file, detect_types=sqlite3.PARSE_DECLTYPES)
        self.db.row_factory = sqlite3.Row
        self.setup_database()
        self.load_state()
        self.reconcile_positions_on_startup()

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
            if market.get('type') == 'swap' and market.get('base') == 'BTC' and market.get('quote') == 'USDC'
        ]
        if not candidates:
            return None

        preferred = next((s for s in candidates if s.startswith('BTC/USDC')), candidates[0])
        self.logger.info(f"📊 BTC regime symbol resolved to {preferred}")
        return preferred

    def fetch_btc_regime_signal(self):
        if not self.btc_regime_symbol:
            return None

        try:
            ohlcv = self.exchange.fetch_ohlcv(self.btc_regime_symbol, '4h', limit=260)
            if not ohlcv or len(ohlcv) < 200:
                return None

            ohlc4_values = self.calculate_ohlc4(ohlcv)
            current_ohlc4 = ohlc4_values[-1]
            btc_wma_200 = self.calculate_wma(ohlc4_values, period=200, offset=0)
            if btc_wma_200 is None:
                return None

            return 'BUY' if current_ohlc4 > btc_wma_200 else 'SELL'
        except Exception:
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

    def update_daily_drawdown_pause(self):
        if self.session_start_balance <= 0:
            return

        drawdown = (self.current_balance - self.session_start_balance) / self.session_start_balance
        if drawdown <= self.daily_drawdown_limit and not self.daily_drawdown_paused:
            self.daily_drawdown_paused = True
            self.logger.warning(
                f"🛑 Daily drawdown halt triggered: {drawdown * 100:.2f}% <= {self.daily_drawdown_limit * 100:.2f}%"
            )

    def in_loss_cooldown(self):
        if self.cooldown_until_utc is None:
            return False
        return datetime.datetime.now(datetime.timezone.utc) < self.cooldown_until_utc

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

    def setup_logging(self):
        self.logger = logging.getLogger('PaperTradingBotV2')
        self.logger.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)

        file_handler = logging.FileHandler('usdc_paper_trading_log.txt', mode='a')
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)

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
                pnl_percentage REAL
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
        self.db.commit()

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

        self.total_trades = stats['total_trades'] or 0
        self.winning_trades = stats['winning_trades'] or 0
        self.losing_trades = stats['losing_trades'] or 0
        self.total_pnl = stats['total_realized_pnl'] or 0.0
        self.current_balance = self.initial_balance + self.total_pnl

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
            return False
        prior = current_index - 1
        if prior < 0:
            return False

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
            return False

        if signal_type == 'BUY':
            hh = max(consec, key=lambda i: ohlcv_data[i][2])
            return ohlcv_data[prior][4] > ohlcv_data[hh][4]
        else:
            ll = min(consec, key=lambda i: ohlcv_data[i][3])
            return ohlcv_data[prior][4] < ohlcv_data[ll][4]

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
            confirmed = self.confirm_signal(ohlcv, ohlc4_values, wma_values, len(ohlcv)-1, signal_type)
            return {
                'symbol': symbol,
                'current_price': current_ohlc4,
                'signal': signal_type,
                'confirmed': confirmed,
                'atr_ratio': atr_ratio,
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
        pos = PaperPosition(symbol, side, price, qty, datetime.datetime.now())
        pos.round_trip_fee_rate = self.round_trip_fee_rate
        self.positions[symbol] = pos
        self.persist_position(pos)
        self.total_trades += 1
        self.logger.info(
            f"🆕 OPENED {side.upper()} {symbol} @ {price:.8f}, gross_qty={gross_qty:.6f}, net_qty={qty:.6f}, "
            f"atr_ratio={analysis.get('atr_ratio', 0.0):.4f}, leverage={leverage:.1f}x ({leverage_tier})"
        )
        return True

    def persist_position(self, pos):
        cursor = self.db.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO positions (
                symbol, side, entry_price, quantity, timestamp,
                stop_loss, trailing_stop_level, trailing_stop_active,
                peak_pnl_percentage, current_price, pnl, pnl_percentage
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
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
            pos.pnl_percentage
        ))
        self.db.commit()

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

    def close_position(self, symbol, reason):
        pos = self.positions.pop(symbol, None)
        if not pos:
            return
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
        self.closed_trades.append({'symbol': symbol, 'pnl': pos.pnl, 'pnl_pct': pos.pnl_percentage, 'reason': reason, 'time': datetime.datetime.now()})
        self.record_closed_trade(pos, reason)
        self.remove_persisted_position(symbol)
        self.logger.info(
            f"🔒 CLOSED {symbol} ({reason}) gross_pnl={pos.gross_pnl:.2f}, fees={pos.fee_cost:.2f}, "
            f"net_pnl={pos.pnl:.2f}, pnl%={pos.pnl_percentage:.2f}"
        )

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
                partial_pnl = pos.take_partial_profit(idx, level)
                self.current_balance += partial_pnl
                self.total_pnl += partial_pnl
                self.logger.info(f"💰 PARTIAL EXIT {symbol} at {level*100:.1f}% -> {partial_pnl:.2f}")
                self.persist_position(pos)

            if pos.should_activate_trailing_stop():
                pos.activate_trailing_stop()
                self.logger.info(f"🎯 TRAILING ACTIVATED {symbol} level={pos.trailing_stop_level:.8f}")

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
        cycle = 0
        while True:
            cycle += 1
            self.logger.info(f"\n🔄 Cycle {cycle} @ {datetime.datetime.now()}")
            self.reset_daily_session_if_needed()
            self.update_daily_drawdown_pause()
            self.update_positions()

            signals = 0
            should_scan_entries = (cycle == 1) or self.is_signal_window()
            if should_scan_entries:
                if cycle == 1 and not self.is_signal_window():
                    self.logger.info('🚦 Cycle 1 bootstrap: evaluating new entry signals outside 4H window')
                else:
                    self.logger.info('🕓 4H close window active: evaluating new entry signals')
                regime_signal = self.fetch_btc_regime_signal()
                if regime_signal is None:
                    self.logger.warning('⚠️ BTC regime unavailable; skipping new entries this window')
                else:
                    self.logger.info(f'📈 BTC regime gate active: {regime_signal}-only entries')
                for symbol in self.usdc_swaps:
                    if self.daily_drawdown_paused:
                        self.logger.info('🛑 Daily drawdown pause active: skipping new entries')
                        break
                    if self.in_loss_cooldown():
                        self.logger.info(
                            f"⏸️ Loss cooldown active until {self.cooldown_until_utc.isoformat()}: skipping new entries"
                        )
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

            time.sleep(self.loop_interval_seconds)


if __name__ == '__main__':
    bot = PaperTradingBotV2()
    try:
        bot.run()
    except KeyboardInterrupt:
        bot.logger.info('🛑 Stopped by user')
        bot.display_status()
