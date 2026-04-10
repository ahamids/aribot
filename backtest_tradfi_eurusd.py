#!/usr/bin/env python3
"""Standalone EURUSD (synthetic) backtesting pipeline using Bybit spot USDTEUR.

This script intentionally does NOT modify existing crypto backtesting flows.
It provides:
1) validate-source: verify USDTEUR spot availability and leverage support flags.
2) backfill: ingest USDTEUR spot candles into SQLite.
3) run: invert USDTEUR candles into synthetic EURUSD and run deterministic backtest.

Synthetic transform:
- EURUSD = 1 / USDTEUR
- open  = 1 / source_open
- high  = 1 / source_low
- low   = 1 / source_high
- close = 1 / source_close
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import time
from pathlib import Path
from typing import Dict, List, Optional

from backtest_aribot import (
    BYBIT_MAINNET,
    BYBIT_TESTNET,
    BacktestConfig,
    BybitPublicClient,
    Candle,
    Position,
    SQLiteStore,
    calculate_atr,
    calculate_macd_diff_series,
    calculate_ohlc4,
    calculate_stoch_rsi_series,
    calculate_wma_series,
    confirm_signal,
    derive_pnl_pct,
    interval_to_ms,
    net_pnl,
    utc_now,
    write_backtest_artifacts,
)


DEFAULT_INTERVAL = "240"
DEFAULT_SOURCE_SYMBOL = "USDTEUR"
DEFAULT_SOURCE_CATEGORY = "spot"
SYNTH_SYMBOL = "EURUSD_SYNTH"
MS_PER_4H = 4 * 60 * 60 * 1000


@dataclasses.dataclass
class SourceValidationResult:
    source_symbol: str
    category: str
    exists: bool
    trading: bool
    margin_trading: str
    leverage_supported: bool
    sample_kline_rows: int
    notes: List[str]


def invert_usdteur_to_eurusd(source: Candle) -> Optional[Candle]:
    prices = [source.open_price, source.high_price, source.low_price, source.close_price]
    if any(p <= 0 for p in prices):
        return None

    out = Candle(
        open_time_ms=source.open_time_ms,
        open_price=1.0 / source.open_price,
        high_price=1.0 / source.low_price,
        low_price=1.0 / source.high_price,
        close_price=1.0 / source.close_price,
        volume=source.volume,
        turnover=source.turnover,
    )

    if out.high_price < max(out.open_price, out.close_price):
        return None
    if out.low_price > min(out.open_price, out.close_price):
        return None
    if out.high_price < out.low_price:
        return None
    return out


def validate_source(args: argparse.Namespace) -> None:
    base_url = BYBIT_TESTNET if args.testnet else BYBIT_MAINNET
    client = BybitPublicClient(
        base_url=base_url,
        timeout_seconds=args.timeout_seconds,
        max_retries=args.max_retries,
        retry_base_seconds=args.retry_base_seconds,
        retry_max_seconds=args.retry_max_seconds,
    )

    items = client.list_instruments(category=args.category)
    item = next((x for x in items if str(x.get("symbol") or "").upper() == args.source_symbol.upper()), None)

    notes: List[str] = []
    exists = item is not None
    trading = False
    margin_trading = "unknown"
    leverage_supported = False

    if item is not None:
        trading = str(item.get("status") or "") == "Trading"
        margin_trading = str(item.get("marginTrading") or "unknown")
        if margin_trading.lower() not in {"none", "unknown"}:
            leverage_supported = True
        notes.append(f"status={item.get('status')}")
        notes.append(f"marginTrading={margin_trading}")
        notes.append("leverageFilter field absent for spot instruments")
    else:
        notes.append("instrument not found in instruments-info")

    sample_rows = 0
    try:
        rows = client.fetch_kline(
            category=args.category,
            symbol=args.source_symbol.upper(),
            interval=args.interval,
            start_ms=args.start_ms,
            end_ms=args.end_ms,
            limit=min(50, max(1, int(args.limit))),
        )
        sample_rows = len(rows)
    except Exception as exc:  # pragma: no cover - external API
        notes.append(f"kline probe failed: {type(exc).__name__}: {exc}")

    result = SourceValidationResult(
        source_symbol=args.source_symbol.upper(),
        category=args.category,
        exists=exists,
        trading=trading,
        margin_trading=margin_trading,
        leverage_supported=leverage_supported,
        sample_kline_rows=sample_rows,
        notes=notes,
    )

    payload = dataclasses.asdict(result)
    print(json.dumps(payload, indent=2))

    if not exists:
        raise RuntimeError(f"Source symbol {args.source_symbol.upper()} not found in category={args.category}")
    if not trading:
        raise RuntimeError(f"Source symbol {args.source_symbol.upper()} exists but is not Trading")
    if sample_rows <= 0:
        raise RuntimeError(f"Source symbol {args.source_symbol.upper()} returned no klines for probe")


def backfill_source(args: argparse.Namespace) -> None:
    base_url = BYBIT_TESTNET if args.testnet else BYBIT_MAINNET
    client = BybitPublicClient(
        base_url=base_url,
        timeout_seconds=args.timeout_seconds,
        max_retries=args.max_retries,
        retry_base_seconds=args.retry_base_seconds,
        retry_max_seconds=args.retry_max_seconds,
    )
    store = SQLiteStore(Path(args.db))

    limit = max(1, min(1000, int(args.limit)))
    run_id = f"ingest-tradfi-{utc_now().strftime('%Y%m%dT%H%M%SZ')}"
    started_at = utc_now().isoformat()

    store.record_ingestion_run_start(
        run_id,
        started_at,
        base_url,
        args.category,
        args.interval,
        1,
        {
            "source_symbol": args.source_symbol.upper(),
            "pipeline": "tradfi_eurusd",
            "synthetic_symbol": SYNTH_SYMBOL,
        },
    )

    total_requests = 0
    total_candles = 0
    current_end = args.end_ms if args.end_ms is not None else int(time.time() * 1000)

    while True:
        page = client.fetch_kline(
            category=args.category,
            symbol=args.source_symbol.upper(),
            interval=args.interval,
            start_ms=args.start_ms,
            end_ms=current_end,
            limit=limit,
        )
        total_requests += 1

        if not page:
            break

        ingested_at = utc_now().isoformat()
        min_open = None
        for candle in page:
            store.upsert_candle(
                category=args.category,
                symbol=args.source_symbol.upper(),
                interval=args.interval,
                candle=candle,
                run_id=run_id,
                ingested_at_utc=ingested_at,
            )
            total_candles += 1
            if min_open is None or candle.open_time_ms < min_open:
                min_open = candle.open_time_ms

        store.conn.commit()
        store.record_ingestion_run_progress(run_id, total_requests, total_candles)

        if min_open is None:
            break
        if args.start_ms is not None and min_open <= args.start_ms:
            break

        next_end = min_open - 1
        if next_end >= current_end:
            break
        current_end = next_end

        if args.max_pages and total_requests >= args.max_pages:
            break
        if args.sleep_seconds > 0:
            time.sleep(args.sleep_seconds)

    finished_at = utc_now().isoformat()
    store.record_ingestion_run_end(run_id, finished_at)

    manifest = store.create_manifest(
        run_id=run_id,
        category=args.category,
        interval=args.interval,
        start_ms=args.start_ms,
        end_ms=args.end_ms,
        symbols=[args.source_symbol.upper()],
        notes={
            "label": args.manifest_label,
            "source_symbol": args.source_symbol.upper(),
            "synthetic_symbol": SYNTH_SYMBOL,
            "started_at": started_at,
            "finished_at": finished_at,
            "request_count": total_requests,
            "candle_upserts": total_candles,
        },
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{manifest['manifest_id']}.json"
    out_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("Backfill complete")
    print(f"  source_symbol: {args.source_symbol.upper()}")
    print(f"  requests: {total_requests}")
    print(f"  candle_upserts: {total_candles}")
    print(f"  manifest: {out_path}")

    store.close()


class EurUsdSyntheticRunner:
    def __init__(
        self,
        *,
        candles: List[Candle],
        config: BacktestConfig,
        interval: str,
        leverage: float,
    ) -> None:
        self.candles = candles
        self.config = config
        self.interval = interval
        self.leverage = max(0.1, float(leverage))

        self.ohlc4 = calculate_ohlc4(candles)
        self.wma45 = calculate_wma_series(self.ohlc4, period=45, offset=2)
        self.atr14 = [calculate_atr(candles, i, period=14) for i in range(len(candles))]
        self.macd_diff = calculate_macd_diff_series(self.ohlc4, fast_period=2, slow_period=39, signal_period=6)
        self.stoch_k, self.stoch_d = calculate_stoch_rsi_series(self.ohlc4, rsi_period=14, k_period=3, d_period=3)

        self.balance = config.initial_balance
        self.initial_balance = config.initial_balance
        self.total_pnl = 0.0
        self.winning_trades = 0
        self.losing_trades = 0
        self.closed_trades: List[dict] = []
        self.equity_curve: List[dict] = []

        self.position: Optional[Position] = None
        self.current_day = None
        self.session_start_balance = config.initial_balance
        self.daily_drawdown_paused = False
        self.consecutive_losses = 0
        self.cooldown_until_ms: Optional[int] = None

    def _update_daily_session(self, ts_ms: int) -> None:
        day = utc_now().fromtimestamp(ts_ms / 1000, tz=utc_now().tzinfo).date()
        if self.current_day is None or day != self.current_day:
            self.current_day = day
            self.session_start_balance = self.balance
            self.daily_drawdown_paused = False

        if self.session_start_balance > 0:
            drawdown = (self.balance - self.session_start_balance) / self.session_start_balance
            if drawdown <= self.config.daily_drawdown_limit:
                self.daily_drawdown_paused = True

    def _entry_blocked(self, ts_ms: int) -> bool:
        if self.daily_drawdown_paused:
            return True
        if self.cooldown_until_ms is not None and ts_ms < self.cooldown_until_ms:
            return True
        return False

    def _confirm_optional_indicators(self, signal_type: str, idx: int) -> bool:
        prior = idx - 1
        if prior < 0:
            return False

        if self.config.require_macd_confirmation:
            val = self.macd_diff[prior]
            if val is None:
                return False
            if signal_type == "BUY" and val <= 0:
                return False
            if signal_type == "SELL" and val >= 0:
                return False

        if self.config.require_stoch_rsi_confirmation:
            k = self.stoch_k[prior]
            d = self.stoch_d[prior]
            if k is None or d is None:
                return False
            if signal_type == "BUY" and k <= d:
                return False
            if signal_type == "SELL" and k >= d:
                return False
            # Prevent BUY signals when Stoch RSI is in overbought zone (> 80)
            if signal_type == "BUY" and k > 80:
                return False
            # Prevent SELL signals when Stoch RSI is in oversold zone (< 20)
            if signal_type == "SELL" and k < 20:
                return False

        return True

    def _signal(self, idx: int) -> Optional[dict]:
        if idx < 46:
            return None
        w = self.wma45[idx]
        if w is None:
            return None

        current = self.ohlc4[idx]
        atr = self.atr14[idx]
        atr_ratio = (atr / current) if (atr is not None and current > 0) else 0.0
        signal_type = "BUY" if (current - w) > 0 else "SELL"

        confirmed = confirm_signal(self.candles, self.ohlc4, self.wma45, idx, signal_type)
        if not confirmed:
            return None
        if not self._confirm_optional_indicators(signal_type, idx):
            return None

        return {"signal": signal_type, "atr_ratio": atr_ratio, "index": idx}

    def _open_position(self, signal: str, fill_price: float, ts_ms: int, atr_ratio: float) -> bool:
        if self.position is not None:
            return False
        if fill_price <= 0:
            return False

        risk_pct = self.config.entry_risk_pct
        if atr_ratio > self.config.atr_volatility_cutoff:
            risk_pct *= self.config.atr_size_scalar

        gross_notional = self.balance * risk_pct * self.leverage
        net_notional = gross_notional * (1 - self.config.round_trip_fee_rate)
        qty = net_notional / fill_price
        if qty <= 0:
            return False

        self.position = Position(
            symbol=SYNTH_SYMBOL,
            side="long" if signal == "BUY" else "short",
            entry_price=fill_price,
            quantity=qty,
            entry_time_ms=ts_ms,
            leverage=self.leverage,
            leverage_tier="manual",
            round_trip_fee_rate=self.config.round_trip_fee_rate,
        )
        return True

    def _close_position(self, pos: Position, exit_price: float, ts_ms: int, reason: str) -> None:
        pnl = net_pnl(pos.entry_price, exit_price, pos.quantity, pos.side, pos.round_trip_fee_rate)
        pnl_pct = derive_pnl_pct(pos.entry_price, exit_price, pos.side)
        self.balance += pnl
        self.total_pnl += pnl

        if pnl > 0:
            self.winning_trades += 1
            self.consecutive_losses = 0
        else:
            self.losing_trades += 1
            self.consecutive_losses += 1
            if self.consecutive_losses >= self.config.max_consecutive_losses:
                self.cooldown_until_ms = ts_ms + (self.config.cooldown_candles * interval_to_ms(self.interval))

        self.closed_trades.append(
            {
                "symbol": pos.symbol,
                "side": pos.side,
                "entry_time_ms": pos.entry_time_ms,
                "exit_time_ms": ts_ms,
                "entry_price": pos.entry_price,
                "exit_price": exit_price,
                "quantity": pos.quantity,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "reason": reason,
                "leverage": pos.leverage,
                "leverage_tier": pos.leverage_tier,
                "partials": list(pos.partial_exits or []),
            }
        )
        self.position = None

    def _try_partial_exit(self, pos: Position, level_pct: float, size_frac: float, current_price: float, ts_ms: int) -> bool:
        already = [float(x.get("target_pct", 0.0)) for x in (pos.partial_exits or [])]
        if level_pct in already:
            return False

        pnl_pct = derive_pnl_pct(pos.entry_price, current_price, pos.side)
        if pnl_pct < (level_pct * 100.0):
            return False

        close_qty = pos.quantity * size_frac
        if close_qty <= 0:
            return False

        realized = net_pnl(pos.entry_price, current_price, close_qty, pos.side, pos.round_trip_fee_rate)
        self.balance += realized
        self.total_pnl += realized
        pos.quantity -= close_qty
        (pos.partial_exits or []).append(
            {
                "time_ms": ts_ms,
                "target_pct": level_pct,
                "size_frac": size_frac,
                "close_qty": close_qty,
                "close_price": current_price,
                "pnl": realized,
            }
        )
        return True

    def _update_position_intrabar(self, pos: Position, candle: Candle, ts_ms: int) -> None:
        if pos.quantity <= 0:
            self._close_position(pos, candle.close_price, ts_ms, "full_partial_exit")
            return

        if pos.side == "long":
            stop_price = pos.entry_price * (1 - self.config.hard_stop_pct)
            if candle.low_price <= stop_price:
                self._close_position(pos, stop_price, ts_ms, "stop_loss")
                return
            close_px = candle.close_price
        else:
            stop_price = pos.entry_price * (1 + self.config.hard_stop_pct)
            if candle.high_price >= stop_price:
                self._close_position(pos, stop_price, ts_ms, "stop_loss")
                return
            close_px = candle.close_price

        elapsed_minutes = (ts_ms - pos.entry_time_ms) / 60000.0
        pnl_pct = derive_pnl_pct(pos.entry_price, close_px, pos.side)
        pos.peak_pnl_pct = max(pos.peak_pnl_pct, pnl_pct)

        for lvl, frac in zip(self.config.partial_levels, self.config.partial_sizes):
            self._try_partial_exit(pos, lvl, frac, close_px, ts_ms)
            if self.position is None:
                return

        if not pos.trailing_stop_active and pnl_pct >= (self.config.trailing_trigger_pct * 100.0):
            pos.trailing_stop_active = True
            if pos.side == "long":
                pos.trailing_stop_level = close_px * (1 - self.config.trailing_buffer_pct)
            else:
                pos.trailing_stop_level = close_px * (1 + self.config.trailing_buffer_pct)

        if pos.trailing_stop_active:
            if pos.side == "long":
                peak_price = pos.entry_price * (1 + (pos.peak_pnl_pct / 100.0))
                candidate = peak_price * (1 - self.config.trailing_buffer_pct)
                if pos.trailing_stop_level is None or candidate > pos.trailing_stop_level:
                    pos.trailing_stop_level = candidate
            else:
                trough_price = pos.entry_price * (1 - (pos.peak_pnl_pct / 100.0))
                candidate = trough_price * (1 + self.config.trailing_buffer_pct)
                if pos.trailing_stop_level is None or candidate < pos.trailing_stop_level:
                    pos.trailing_stop_level = candidate

            if pos.trailing_stop_level is not None:
                if (pos.side == "long" and close_px <= pos.trailing_stop_level) or (
                    pos.side == "short" and close_px >= pos.trailing_stop_level
                ):
                    self._close_position(pos, pos.trailing_stop_level, ts_ms, "TRAILING_STOP")
                    return

        if elapsed_minutes >= self.config.max_hold_minutes:
            self._close_position(pos, close_px, ts_ms, "time_exit")

    def _record_equity(self, ts_ms: int, close_price: float) -> None:
        unrealized = 0.0
        if self.position is not None:
            if self.position.side == "long":
                unrealized = (close_price - self.position.entry_price) * self.position.quantity
            else:
                unrealized = (self.position.entry_price - close_price) * self.position.quantity
        self.equity_curve.append(
            {
                "time_ms": ts_ms,
                "balance": self.balance,
                "unrealized_pnl": unrealized,
                "equity": self.balance + unrealized,
            }
        )

    def _build_summary(self) -> dict:
        max_equity = -float("inf")
        max_drawdown = 0.0
        for row in self.equity_curve:
            eq = row["equity"]
            if eq > max_equity:
                max_equity = eq
            if max_equity > 0:
                dd = (eq - max_equity) / max_equity
                if dd < max_drawdown:
                    max_drawdown = dd

        total_return = (self.balance - self.initial_balance) / self.initial_balance if self.initial_balance > 0 else 0.0
        win_rate = (self.winning_trades / len(self.closed_trades)) if self.closed_trades else 0.0

        reason_counts: Dict[str, int] = {}
        for t in self.closed_trades:
            r = str(t.get("reason") or "unknown")
            reason_counts[r] = reason_counts.get(r, 0) + 1

        return {
            "initial_balance": self.initial_balance,
            "final_balance": self.balance,
            "total_pnl": self.total_pnl,
            "total_return": total_return,
            "closed_trades": len(self.closed_trades),
            "win_rate": win_rate,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "max_drawdown": max_drawdown,
            "reason_counts": reason_counts,
        }

    def run(self) -> dict:
        if len(self.candles) < 260:
            raise RuntimeError("Insufficient synthetic EURUSD candles for warmup")

        pending_entry: Optional[dict] = None

        for idx, candle in enumerate(self.candles):
            ts_ms = candle.open_time_ms
            self._update_daily_session(ts_ms)

            if pending_entry is not None and pending_entry.get("execute_index") == idx:
                self._open_position(
                    pending_entry["signal"],
                    candle.open_price,
                    ts_ms,
                    pending_entry["atr_ratio"],
                )
                pending_entry = None

            if self.position is not None:
                self._update_position_intrabar(self.position, candle, ts_ms)

            if self.position is None and pending_entry is None and not self._entry_blocked(ts_ms):
                sig = self._signal(idx)
                if sig is not None and (idx + 1) < len(self.candles):
                    pending_entry = {
                        "signal": sig["signal"],
                        "atr_ratio": sig["atr_ratio"],
                        "execute_index": idx + 1,
                    }

            self._record_equity(ts_ms, candle.close_price)

        if self.position is not None:
            last = self.candles[-1]
            self._close_position(self.position, last.close_price, last.open_time_ms, "end_of_test")
            self._record_equity(last.open_time_ms, last.close_price)

        return self._build_summary()


def run_backtest(args: argparse.Namespace) -> None:
    store = SQLiteStore(Path(args.db))

    source_candles = store.fetch_candles(
        category=args.category,
        symbol=args.source_symbol.upper(),
        interval=args.interval,
        start_ms=args.start_ms,
        end_ms=args.end_ms,
    )
    if not source_candles:
        raise RuntimeError("No source candles found in DB. Run backfill first.")

    synthetic_candles: List[Candle] = []
    dropped = 0
    for c in source_candles:
        inv = invert_usdteur_to_eurusd(c)
        if inv is None:
            dropped += 1
            continue
        synthetic_candles.append(inv)

    if not synthetic_candles:
        raise RuntimeError("All source candles were invalid after USDTEUR->EURUSD inversion")

    config = BacktestConfig(
        initial_balance=float(args.initial_balance),
        max_open_positions=1,
        require_macd_confirmation=bool(args.confirm_macd),
        require_stoch_rsi_confirmation=bool(args.confirm_stoch_rsi),
    )

    runner = EurUsdSyntheticRunner(
        candles=synthetic_candles,
        config=config,
        interval=args.interval,
        leverage=float(args.leverage),
    )

    summary = runner.run()

    out_dir = Path(args.out_dir)
    metadata = {
        "db": str(Path(args.db).resolve()),
        "category": args.category,
        "interval": args.interval,
        "source_symbol": args.source_symbol.upper(),
        "synthetic_symbol": SYNTH_SYMBOL,
        "start_ms": args.start_ms,
        "end_ms": args.end_ms,
        "dropped_source_candles": dropped,
        "config": dataclasses.asdict(config),
        "applied_leverage": float(args.leverage),
        "source_margin_trading": "none",
        "source_leverage_supported": False,
        "script": "backtest_tradfi_eurusd.py",
    }

    write_backtest_artifacts(
        out_dir=out_dir,
        summary=summary,
        trades=runner.closed_trades,
        equity_curve=runner.equity_curve,
        metadata=metadata,
    )

    synth_manifest_path = out_dir / "synthetic_series_manifest.json"
    synth_manifest_path.write_text(
        json.dumps(
            {
                "created_at_utc": utc_now().isoformat(),
                "source_symbol": args.source_symbol.upper(),
                "synthetic_symbol": SYNTH_SYMBOL,
                "transform": "inverse_ohlc",
                "source_candles": len(source_candles),
                "synthetic_candles": len(synthetic_candles),
                "dropped_source_candles": dropped,
                "window": {
                    "start_ms": synthetic_candles[0].open_time_ms,
                    "end_ms": synthetic_candles[-1].open_time_ms,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print("Synthetic EURUSD backtest complete")
    print(f"  source_symbol: {args.source_symbol.upper()} ({args.category})")
    print(f"  synthetic_symbol: {SYNTH_SYMBOL}")
    print(f"  source_leverage_supported: False (marginTrading=none on Bybit spot)")
    print(f"  closed_trades: {summary['closed_trades']}")
    print(f"  final_balance: {summary['final_balance']:.4f}")
    print(f"  total_return: {summary['total_return'] * 100:.2f}%")
    print(f"  artifacts: {out_dir.resolve()}")

    store.close()


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TradFi EURUSD synthetic backtesting pipeline (Bybit spot USDTEUR)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate-source", help="Validate source instrument and leverage support flags")
    p_validate.add_argument("--category", default=DEFAULT_SOURCE_CATEGORY, help="Bybit category (default: spot)")
    p_validate.add_argument("--source-symbol", default=DEFAULT_SOURCE_SYMBOL, help="Source symbol to invert into EURUSD")
    p_validate.add_argument("--interval", default=DEFAULT_INTERVAL, help="Kline interval")
    p_validate.add_argument("--start-ms", type=int, default=None, help="Optional probe start timestamp ms")
    p_validate.add_argument("--end-ms", type=int, default=None, help="Optional probe end timestamp ms")
    p_validate.add_argument("--limit", type=int, default=50, help="Probe kline row limit")
    p_validate.add_argument("--timeout-seconds", type=float, default=20.0, help="HTTP timeout")
    p_validate.add_argument("--max-retries", type=int, default=8, help="Retry count for transient errors")
    p_validate.add_argument("--retry-base-seconds", type=float, default=1.0, help="Initial retry backoff seconds")
    p_validate.add_argument("--retry-max-seconds", type=float, default=30.0, help="Maximum retry backoff seconds")
    p_validate.add_argument("--testnet", action="store_true", help="Use Bybit testnet")

    p_backfill = sub.add_parser("backfill", help="Backfill source USDTEUR spot candles into SQLite")
    p_backfill.add_argument("--db", default="aribot_backtest.db", help="SQLite DB path")
    p_backfill.add_argument("--category", default=DEFAULT_SOURCE_CATEGORY, help="Bybit category (default: spot)")
    p_backfill.add_argument("--source-symbol", default=DEFAULT_SOURCE_SYMBOL, help="Source symbol")
    p_backfill.add_argument("--interval", default=DEFAULT_INTERVAL, help="Bybit interval")
    p_backfill.add_argument("--start-ms", type=int, default=None, help="Optional start timestamp ms")
    p_backfill.add_argument("--end-ms", type=int, default=None, help="Optional end timestamp ms")
    p_backfill.add_argument("--limit", type=int, default=1000, help="Rows per request (<=1000)")
    p_backfill.add_argument("--sleep-seconds", type=float, default=0.05, help="Sleep between requests")
    p_backfill.add_argument("--max-pages", type=int, default=0, help="Optional page cap (0=unlimited)")
    p_backfill.add_argument("--timeout-seconds", type=float, default=20.0, help="HTTP timeout")
    p_backfill.add_argument("--max-retries", type=int, default=8, help="Retries on transient errors")
    p_backfill.add_argument("--retry-base-seconds", type=float, default=1.0, help="Initial retry backoff seconds")
    p_backfill.add_argument("--retry-max-seconds", type=float, default=30.0, help="Maximum retry backoff seconds")
    p_backfill.add_argument("--testnet", action="store_true", help="Use Bybit testnet")
    p_backfill.add_argument("--manifest-label", default="", help="Label embedded in manifest")
    p_backfill.add_argument("--out-dir", default="backtest_artifacts/manifests_tradfi", help="Manifest output directory")

    p_run = sub.add_parser("run", help="Run synthetic EURUSD backtest from local source candles")
    p_run.add_argument("--db", default="aribot_backtest.db", help="SQLite DB path")
    p_run.add_argument("--category", default=DEFAULT_SOURCE_CATEGORY, help="Source candle category")
    p_run.add_argument("--source-symbol", default=DEFAULT_SOURCE_SYMBOL, help="Source symbol")
    p_run.add_argument("--interval", default=DEFAULT_INTERVAL, help="Candle interval")
    p_run.add_argument("--start-ms", type=int, default=None, help="Backtest start timestamp ms")
    p_run.add_argument("--end-ms", type=int, default=None, help="Backtest end timestamp ms")
    p_run.add_argument("--initial-balance", type=float, default=1000.0, help="Initial balance")
    p_run.add_argument("--leverage", type=float, default=1.0, help="Applied leverage override (spot default=1.0)")
    p_run.add_argument("--confirm-macd", action="store_true", help="Require MACD(2,39,6) confirmation")
    p_run.add_argument("--confirm-stoch-rsi", action="store_true", help="Require Stoch RSI(14,3,3) confirmation")
    p_run.add_argument("--out-dir", default="backtest_artifacts/latest_tradfi_run", help="Output directory")

    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "validate-source":
            validate_source(args)
        elif args.command == "backfill":
            if args.max_pages <= 0:
                args.max_pages = None
            backfill_source(args)
        elif args.command == "run":
            run_backtest(args)
        else:
            raise RuntimeError(f"Unsupported command: {args.command}")
        return 0
    except KeyboardInterrupt:
        print("Interrupted")
        return 130
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
