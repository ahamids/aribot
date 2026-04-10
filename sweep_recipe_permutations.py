#!/usr/bin/env python3
"""Run a full-factorial backtest sweep across recipe parameter ranges.

This script is intended for fast A/B sweeps and writes:
- results.csv (one row per permutation)
- report.md (summary + top configurations)
- meta.json (run metadata and selected ranges)
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import itertools
import json
import multiprocessing as mp
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from backtest_aribot import (
    BacktestConfig,
    BacktestRunner,
    SQLiteStore,
    bucket_base_assets,
    load_leverage_buckets,
    parse_bucket_selection,
    validate_backtest_config,
)


_WORKER_STATE: Dict[str, object] = {}


def normalize_percent_to_ratio(value: float) -> float:
    return value / 100.0 if abs(value) > 1.0 else value


def clone_leverage_buckets(buckets: dict) -> dict:
    return {
        "major": {
            "leverage": float(buckets["major"]["leverage"]),
            "symbols": set(buckets["major"]["symbols"]),
        },
        "large_alt": {
            "leverage": float(buckets["large_alt"]["leverage"]),
            "symbols": set(buckets["large_alt"]["symbols"]),
        },
        "mid_cap": {
            "leverage": float(buckets["mid_cap"]["leverage"]),
            "symbols": set(buckets["mid_cap"]["symbols"]),
        },
        "default_leverage": float(buckets["default_leverage"]),
    }


def leverage_profile_from_base(base_buckets: dict, combo: dict) -> dict:
    # Keep symbol sets shared (read-only in runner) and only vary leverage scalars.
    return {
        "major": {
            "leverage": float(combo["major_leverage"]),
            "symbols": base_buckets["major"]["symbols"],
        },
        "large_alt": {
            "leverage": float(combo["large_alt_leverage"]),
            "symbols": base_buckets["large_alt"]["symbols"],
        },
        "mid_cap": {
            "leverage": float(combo["mid_cap_leverage"]),
            "symbols": base_buckets["mid_cap"]["symbols"],
        },
        "default_leverage": float(combo["default_leverage"]),
    }


def discrete_ranges() -> Dict[str, List[dict]]:
    # Compact yet meaningful ranges to keep full-factorial runtime tractable.
    return {
        "signal_setup": [
            {"name": "sig_baseline", "signal_source": "ohlc4", "signal_wma_period": 45, "signal_wma_offset": 2},
            {"name": "sig_smoother", "signal_source": "hlc3", "signal_wma_period": 50, "signal_wma_offset": 2},
        ],
        "btc_regime_setup": [
            {"name": "reg_baseline", "btc_regime_source": "ohlc4", "btc_regime_wma_period": 90, "btc_regime_wma_offset": 0},
            {"name": "reg_faster", "btc_regime_source": "hlc3", "btc_regime_wma_period": 72, "btc_regime_wma_offset": 0},
        ],
        "hard_stop": [
            {"name": "stop_2p0", "hard_stop_pct": 2.0},
            {"name": "stop_2p5", "hard_stop_pct": 2.5},
        ],
        "partial_exits": [
            {"name": "px_baseline", "partial_levels": (2.0, 3.0, 5.0), "partial_sizes": (25.0, 25.0, 25.0)},
            {"name": "px_tighter", "partial_levels": (1.5, 2.5, 4.0), "partial_sizes": (30.0, 25.0, 25.0)},
        ],
        "trailing": [
            {"name": "trail_baseline", "trailing_activation_pct": 2.0, "trailing_callback_pct": 1.5},
            {"name": "trail_tight", "trailing_activation_pct": 1.5, "trailing_callback_pct": 1.0},
        ],
        "time_exit": [
            {"name": "time_32h", "time_exit_hours": 32.0},
            {"name": "time_40h", "time_exit_hours": 40.0},
        ],
        "atr_and_leverage": [
            {
                "name": "risk_baseline",
                "atr_period": 14,
                "atr_volatility_cutoff_pct": 5.0,
                "atr_size_scalar": 0.50,
                "major_leverage": 5.0,
                "large_alt_leverage": 3.0,
                "mid_cap_leverage": 2.0,
                "default_leverage": 1.0,
            },
            {
                "name": "risk_conservative",
                "atr_period": 14,
                "atr_volatility_cutoff_pct": 4.0,
                "atr_size_scalar": 0.40,
                "major_leverage": 4.0,
                "large_alt_leverage": 2.5,
                "mid_cap_leverage": 1.8,
                "default_leverage": 1.0,
            },
        ],
        "macd": [
            {"name": "macd_2_39_6", "macd_fast": 2, "macd_slow": 39, "macd_signal": 6},
            {"name": "macd_3_34_5", "macd_fast": 3, "macd_slow": 34, "macd_signal": 5},
        ],
        "stoch_rsi": [
            {"name": "srsi_14_3_3", "stoch_rsi_period": 14, "stoch_rsi_k": 3, "stoch_rsi_d": 3},
            {"name": "srsi_10_3_3", "stoch_rsi_period": 10, "stoch_rsi_k": 3, "stoch_rsi_d": 3},
        ],
    }


def merge_blocks(blocks: Iterable[dict]) -> dict:
    out: dict = {}
    for block in blocks:
        out.update(block)
    return out


def apply_leverage_profile(buckets: dict, combo: dict) -> None:
    buckets["major"]["leverage"] = float(combo["major_leverage"])
    buckets["large_alt"]["leverage"] = float(combo["large_alt_leverage"])
    buckets["mid_cap"]["leverage"] = float(combo["mid_cap_leverage"])
    buckets["default_leverage"] = float(combo["default_leverage"])


def build_backtest_config(combo: dict, initial_balance: float) -> BacktestConfig:
    cfg = BacktestConfig(
        initial_balance=initial_balance,
        signal_source=str(combo["signal_source"]),
        signal_wma_period=int(combo["signal_wma_period"]),
        signal_wma_offset=int(combo["signal_wma_offset"]),
        btc_regime_source=str(combo["btc_regime_source"]),
        btc_regime_wma_period=int(combo["btc_regime_wma_period"]),
        btc_regime_wma_offset=int(combo["btc_regime_wma_offset"]),
        atr_period=int(combo["atr_period"]),
        atr_volatility_cutoff=normalize_percent_to_ratio(float(combo["atr_volatility_cutoff_pct"])),
        atr_size_scalar=float(combo["atr_size_scalar"]),
        hard_stop_pct=abs(normalize_percent_to_ratio(float(combo["hard_stop_pct"]))),
        trailing_trigger_pct=normalize_percent_to_ratio(float(combo["trailing_activation_pct"])),
        trailing_buffer_pct=normalize_percent_to_ratio(float(combo["trailing_callback_pct"])),
        partial_levels=tuple(normalize_percent_to_ratio(float(x)) for x in combo["partial_levels"]),
        partial_sizes=tuple(normalize_percent_to_ratio(float(x)) for x in combo["partial_sizes"]),
        max_hold_minutes=max(1, int(float(combo["time_exit_hours"]) * 60.0)),
        macd_fast_period=int(combo["macd_fast"]),
        macd_slow_period=int(combo["macd_slow"]),
        macd_signal_period=int(combo["macd_signal"]),
        stoch_rsi_period=int(combo["stoch_rsi_period"]),
        stoch_rsi_k_period=int(combo["stoch_rsi_k"]),
        stoch_rsi_d_period=int(combo["stoch_rsi_d"]),
        # Enable both confirmations so MACD/SRSI parameter sweeps affect decisions.
        require_macd_confirmation=True,
        require_stoch_rsi_confirmation=True,
    )
    validate_backtest_config(cfg)
    return cfg


def build_symbols(
    *,
    store: SQLiteStore,
    category: str,
    interval: str,
    leverage_buckets: dict,
    buckets_csv: str,
    max_symbols: int,
) -> List[str]:
    available_symbols = store.list_symbols_with_candles(category, interval)
    selected_buckets = parse_bucket_selection(buckets_csv)
    desired_bases = bucket_base_assets(leverage_buckets, selected_buckets)
    symbols = [
        s
        for s in available_symbols
        if s.endswith("USDT") and s.replace("/", "").split("USDT")[0].upper() in desired_bases
    ]
    symbols = sorted(set(symbols))
    if max_symbols > 0:
        symbols = symbols[:max_symbols]
    return symbols


def write_results_csv(path: Path, rows: List[dict]) -> None:
    fieldnames = [
        "run_id",
        "combo_name",
        "initial_balance",
        "final_balance",
        "total_pnl",
        "total_return_pct",
        "max_drawdown_pct",
        "closed_trades",
        "win_rate_pct",
        "winning_trades",
        "losing_trades",
        "param_json",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_symbol_results_csv(path: Path, rows: List[dict]) -> None:
    fieldnames = [
        "run_id",
        "combo_name",
        "symbol",
        "symbol_pnl",
        "symbol_pnl_pct_initial",
        "symbol_trades",
        "symbol_wins",
        "symbol_losses",
        "symbol_win_rate_pct",
        "global_total_return_pct",
        "global_max_drawdown_pct",
        "param_json",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_best_symbol_report(path: Path, best_by_symbol: Dict[str, dict], meta: dict) -> None:
    rows = [best_by_symbol[s] for s in sorted(best_by_symbol.keys())]
    rows_sorted = sorted(rows, key=lambda x: x["symbol_pnl"], reverse=True)

    lines: List[str] = []
    lines.append("# Best Recipe Per Symbol")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- Symbols analyzed: {len(rows_sorted)}")
    lines.append(f"- Permutations per symbol: {meta['total_permutations']}")
    lines.append(f"- Source DB: {meta['db']}")
    lines.append("")
    lines.append("## Best Recipe Table")
    lines.append("| symbol | best_run_id | combo | symbol_pnl | symbol_pnl_pct_of_initial | trades | win_rate% | global_run_pnl% | global_run_dd% |")
    lines.append("|---|---:|---|---:|---:|---:|---:|---:|---:|")
    for row in rows_sorted:
        lines.append(
            "| {symbol} | {run_id} | {combo_name} | {symbol_pnl:.4f} | {symbol_pnl_pct_initial:.2f} | {symbol_trades} | {symbol_win_rate_pct:.2f} | {global_total_return_pct:.2f} | {global_max_drawdown_pct:.2f} |".format(
                **row
            )
        )

    lines.append("")
    lines.append("## Notes")
    lines.append("- symbol_pnl is the sum of closed-trade PnL for that symbol inside each multi-symbol run.")
    lines.append("- symbol_pnl_pct_of_initial is symbol_pnl normalized by initial balance for ranking comparability.")
    lines.append("- Use symbol_results.csv for full per-symbol, per-recipe details.")

    path.write_text("\n".join(lines), encoding="utf-8")


def render_markdown_report(path: Path, rows: List[dict], meta: dict) -> None:
    sorted_by_return = sorted(rows, key=lambda x: x["total_return_pct"], reverse=True)
    sorted_by_drawdown = sorted(rows, key=lambda x: x["max_drawdown_pct"], reverse=False)

    top_return = sorted_by_return[:15]
    top_drawdown = sorted_by_drawdown[:15]

    def table_for(items: List[dict]) -> str:
        lines = [
            "| run_id | combo | pnl% | max_dd% | trades | win_rate% |",
            "|---:|---|---:|---:|---:|---:|",
        ]
        for row in items:
            lines.append(
                "| {run_id} | {combo_name} | {total_return_pct:.2f} | {max_drawdown_pct:.2f} | {closed_trades} | {win_rate_pct:.2f} |".format(
                    **row
                )
            )
        return "\n".join(lines)

    avg_return = sum(r["total_return_pct"] for r in rows) / len(rows) if rows else 0.0
    avg_drawdown = sum(r["max_drawdown_pct"] for r in rows) / len(rows) if rows else 0.0

    content = []
    content.append("# Permutation Sweep Report")
    content.append("")
    content.append("## Run Summary")
    content.append(f"- Total permutations run: {len(rows)}")
    content.append(f"- Symbols: {meta['symbols_count']}")
    content.append(f"- Average pnl%: {avg_return:.2f}")
    content.append(f"- Average max drawdown%: {avg_drawdown:.2f}")
    content.append(f"- Runtime seconds: {meta['elapsed_seconds']:.2f}")
    content.append("")
    content.append("## Top 15 By pnl%")
    content.append(table_for(top_return))
    content.append("")
    content.append("## Top 15 By Lowest Drawdown")
    content.append(table_for(top_drawdown))
    content.append("")
    content.append("## Notes")
    content.append("- MACD and Stoch RSI confirmations were enabled for all runs so indicator period changes affect entries.")
    content.append("- Full details for every run are in results.csv.")
    path.write_text("\n".join(content), encoding="utf-8")


def compute_single_combo(
    *,
    run_id: int,
    combo_blocks: tuple,
    symbols: List[str],
    symbols_set: set,
    initial_balance: float,
    has_initial_balance: bool,
    category: str,
    interval: str,
    btc_symbol: str,
    start_ms: Optional[int],
    end_ms: Optional[int],
    store: SQLiteStore,
    base_leverage_buckets: dict,
    null_buffer: io.StringIO,
) -> Tuple[dict, List[dict]]:
    combo = merge_blocks(combo_blocks)
    combo_name = "|".join(str(block["name"]) for block in combo_blocks)
    cfg = build_backtest_config(combo, initial_balance=initial_balance)
    param_json = json.dumps(combo, sort_keys=True, separators=(",", ":"))

    leverage_buckets = leverage_profile_from_base(base_leverage_buckets, combo)
    runner = BacktestRunner(
        store=store,
        category=category,
        interval=interval,
        symbols=symbols,
        btc_symbol=btc_symbol,
        start_ms=start_ms,
        end_ms=end_ms,
        leverage_buckets=leverage_buckets,
        config=cfg,
    )

    null_buffer.seek(0)
    null_buffer.truncate(0)
    with contextlib.redirect_stdout(null_buffer):
        summary = runner.run()

    row = {
        "run_id": run_id,
        "combo_name": combo_name,
        "initial_balance": summary["initial_balance"],
        "final_balance": summary["final_balance"],
        "total_pnl": summary["total_pnl"],
        "total_return_pct": summary["total_return"] * 100.0,
        "max_drawdown_pct": summary["max_drawdown"] * 100.0,
        "closed_trades": summary["closed_trades"],
        "win_rate_pct": summary["win_rate"] * 100.0,
        "winning_trades": summary["winning_trades"],
        "losing_trades": summary["losing_trades"],
        "param_json": param_json,
    }

    symbol_stats: Dict[str, dict] = {}
    for trade in runner.closed_trades:
        symbol = str(trade.get("symbol") or "")
        if symbol not in symbols_set:
            continue
        pnl = float(trade.get("pnl") or 0.0)
        stats = symbol_stats.get(symbol)
        if stats is None:
            stats = {"pnl": 0.0, "trades": 0, "wins": 0, "losses": 0}
            symbol_stats[symbol] = stats
        stats["pnl"] += pnl
        stats["trades"] += 1
        if pnl > 0:
            stats["wins"] += 1
        else:
            stats["losses"] += 1

    symbol_rows_for_combo: List[dict] = []
    for symbol in symbols:
        stats = symbol_stats.get(symbol)
        if stats is None:
            stats = {"pnl": 0.0, "trades": 0, "wins": 0, "losses": 0}
        trades = int(stats["trades"])
        wins = int(stats["wins"])
        losses = int(stats["losses"])
        symbol_pnl = float(stats["pnl"])
        symbol_win_rate_pct = (wins / trades * 100.0) if trades > 0 else 0.0
        symbol_pnl_pct_initial = (
            (symbol_pnl / initial_balance) * 100.0
            if has_initial_balance
            else 0.0
        )

        symbol_row = {
            "run_id": run_id,
            "combo_name": combo_name,
            "symbol": symbol,
            "symbol_pnl": symbol_pnl,
            "symbol_pnl_pct_initial": symbol_pnl_pct_initial,
            "symbol_trades": trades,
            "symbol_wins": wins,
            "symbol_losses": losses,
            "symbol_win_rate_pct": symbol_win_rate_pct,
            "global_total_return_pct": row["total_return_pct"],
            "global_max_drawdown_pct": row["max_drawdown_pct"],
            "param_json": row["param_json"],
        }
        symbol_rows_for_combo.append(symbol_row)

    return row, symbol_rows_for_combo


def _worker_init(db_path: str, leverage_config_path: str) -> None:
    _WORKER_STATE["store"] = SQLiteStore(Path(db_path))
    _WORKER_STATE["base_leverage_buckets"] = load_leverage_buckets(Path(leverage_config_path))
    _WORKER_STATE["null_buffer"] = io.StringIO()


def _worker_run_combo(task: dict) -> Tuple[dict, List[dict]]:
    store = _WORKER_STATE.get("store")
    base_leverage_buckets = _WORKER_STATE.get("base_leverage_buckets")
    null_buffer = _WORKER_STATE.get("null_buffer")
    if store is None or base_leverage_buckets is None or null_buffer is None:
        raise RuntimeError("Worker not initialized")

    return compute_single_combo(
        run_id=int(task["run_id"]),
        combo_blocks=task["combo_blocks"],
        symbols=task["symbols"],
        symbols_set=set(task["symbols"]),
        initial_balance=float(task["initial_balance"]),
        has_initial_balance=bool(task["has_initial_balance"]),
        category=str(task["category"]),
        interval=str(task["interval"]),
        btc_symbol=str(task["btc_symbol"]),
        start_ms=task["start_ms"],
        end_ms=task["end_ms"],
        store=store,
        base_leverage_buckets=base_leverage_buckets,
        null_buffer=null_buffer,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run full-factorial strategy recipe permutations")
    parser.add_argument("--db", default="aribot_backtest.db", help="SQLite DB path")
    parser.add_argument("--category", default="linear", help="Bybit category")
    parser.add_argument("--interval", default="240", help="Candle interval")
    parser.add_argument("--buckets", default="", help="Optional leverage buckets: major,large_alt,mid_cap")
    parser.add_argument("--leverage-config", default="leverage_buckets.json", help="Leverage bucket JSON path")
    parser.add_argument("--btc-symbol", default="BTCUSDT", help="BTC regime symbol")
    parser.add_argument("--start-ms", type=int, default=None, help="Optional start timestamp ms")
    parser.add_argument("--end-ms", type=int, default=None, help="Optional end timestamp ms")
    parser.add_argument("--max-symbols", type=int, default=10, help="Cap symbols for tractable sweeps")
    parser.add_argument("--workers", type=int, default=1, help="Process workers for parallel execution (default: 1)")
    parser.add_argument("--initial-balance", type=float, default=400.0, help="Initial balance")
    parser.add_argument("--out-dir", default="backtest_artifacts/recipe_sweep", help="Output directory")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    store = SQLiteStore(Path(args.db))
    base_leverage_buckets = load_leverage_buckets(Path(args.leverage_config))

    available_symbols = store.list_symbols_with_candles(args.category, args.interval)

    symbols = build_symbols(
        store=store,
        category=args.category,
        interval=args.interval,
        leverage_buckets=base_leverage_buckets,
        buckets_csv=args.buckets,
        max_symbols=args.max_symbols,
    )
    if not symbols:
        raise RuntimeError("No symbols selected for sweep")
    symbols_set = set(symbols)

    if args.btc_symbol not in available_symbols:
        raise RuntimeError(f"BTC regime symbol {args.btc_symbol} not present in DB")

    ranges = discrete_ranges()
    blocks = [ranges[k] for k in ranges.keys()]
    total = 1
    for block in blocks:
        total *= len(block)
    print(f"Running full-factorial sweep: {total} permutations")

    started = time.time()
    initial_balance = float(args.initial_balance)
    has_initial_balance = initial_balance > 0
    workers = max(1, int(args.workers))
    rows: List[dict] = []
    symbol_rows: List[dict] = []
    best_by_symbol: Dict[str, dict] = {}

    if workers == 1:
        null_buffer = io.StringIO()
        for idx, combo_blocks in enumerate(itertools.product(*blocks), start=1):
            row, symbol_rows_for_combo = compute_single_combo(
                run_id=idx,
                combo_blocks=combo_blocks,
                symbols=symbols,
                symbols_set=symbols_set,
                initial_balance=initial_balance,
                has_initial_balance=has_initial_balance,
                category=args.category,
                interval=args.interval,
                btc_symbol=args.btc_symbol,
                start_ms=args.start_ms,
                end_ms=args.end_ms,
                store=store,
                base_leverage_buckets=base_leverage_buckets,
                null_buffer=null_buffer,
            )

            rows.append(row)
            symbol_rows.extend(symbol_rows_for_combo)
            for symbol_row in symbol_rows_for_combo:
                symbol = symbol_row["symbol"]
                current_best = best_by_symbol.get(symbol)
                if current_best is None or symbol_row["symbol_pnl"] > current_best["symbol_pnl"]:
                    best_by_symbol[symbol] = symbol_row

            if idx == 1 or idx % max(1, total // 20) == 0 or idx == total:
                elapsed = time.time() - started
                eta = (elapsed / idx) * (total - idx)
                print(f"Progress {idx}/{total} ({(idx / total) * 100:.1f}%) elapsed={elapsed:.1f}s eta={eta:.1f}s")
    else:
        tasks: List[dict] = []
        for idx, combo_blocks in enumerate(itertools.product(*blocks), start=1):
            tasks.append(
                {
                    "run_id": idx,
                    "combo_blocks": combo_blocks,
                    "symbols": symbols,
                    "initial_balance": initial_balance,
                    "has_initial_balance": has_initial_balance,
                    "category": args.category,
                    "interval": args.interval,
                    "btc_symbol": args.btc_symbol,
                    "start_ms": args.start_ms,
                    "end_ms": args.end_ms,
                }
            )

        with mp.Pool(
            processes=workers,
            initializer=_worker_init,
            initargs=(
                str(Path(args.db).resolve()),
                str(Path(args.leverage_config).resolve()),
            ),
        ) as pool:
            for completed, (row, symbol_rows_for_combo) in enumerate(
                pool.imap(_worker_run_combo, tasks, chunksize=1),
                start=1,
            ):
                rows.append(row)
                symbol_rows.extend(symbol_rows_for_combo)
                for symbol_row in symbol_rows_for_combo:
                    symbol = symbol_row["symbol"]
                    current_best = best_by_symbol.get(symbol)
                    if current_best is None or symbol_row["symbol_pnl"] > current_best["symbol_pnl"]:
                        best_by_symbol[symbol] = symbol_row

                if completed == 1 or completed % max(1, total // 20) == 0 or completed == total:
                    elapsed = time.time() - started
                    eta = (elapsed / completed) * (total - completed)
                    print(
                        f"Progress {completed}/{total} ({(completed / total) * 100:.1f}%) "
                        f"elapsed={elapsed:.1f}s eta={eta:.1f}s"
                    )

        rows.sort(key=lambda x: int(x["run_id"]))
        symbol_rows.sort(key=lambda x: (int(x["run_id"]), str(x["symbol"])))

    elapsed = time.time() - started

    results_csv = out_dir / "results.csv"
    write_results_csv(results_csv, rows)

    symbol_results_csv = out_dir / "symbol_results.csv"
    write_symbol_results_csv(symbol_results_csv, symbol_rows)

    symbol_best_csv = out_dir / "symbol_best_recipes.csv"
    write_symbol_results_csv(symbol_best_csv, [best_by_symbol[s] for s in sorted(best_by_symbol.keys())])

    report_md = out_dir / "report.md"
    meta = {
        "elapsed_seconds": elapsed,
        "symbols_count": len(symbols),
        "symbols": symbols,
        "total_permutations": total,
        "ranges": ranges,
        "db": str(Path(args.db).resolve()),
        "category": args.category,
        "interval": args.interval,
        "btc_symbol": args.btc_symbol,
        "start_ms": args.start_ms,
        "end_ms": args.end_ms,
        "max_symbols": args.max_symbols,
    }
    render_markdown_report(report_md, rows, meta)

    symbol_best_report_md = out_dir / "symbol_best_report.md"
    write_best_symbol_report(symbol_best_report_md, best_by_symbol, meta)

    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    best = max(rows, key=lambda x: x["total_return_pct"])
    print("Sweep complete")
    print(f"  permutations: {total}")
    print(f"  elapsed_seconds: {elapsed:.2f}")
    print(f"  best_run_id: {best['run_id']}")
    print(f"  best_pnl_pct: {best['total_return_pct']:.2f}")
    print(f"  best_drawdown_pct: {best['max_drawdown_pct']:.2f}")
    print(f"  report: {report_md.resolve()}")
    print(f"  csv: {results_csv.resolve()}")
    print(f"  symbol_best_report: {symbol_best_report_md.resolve()}")
    print(f"  symbol_best_csv: {symbol_best_csv.resolve()}")

    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
