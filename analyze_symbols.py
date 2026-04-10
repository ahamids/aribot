#!/usr/bin/env python3
"""Analyze symbol-level backtest performance across seasonal result folders.

Usage:
    python analyze_symbols.py /path/to/backtest_results/
    python analyze_symbols.py /path/to/backtest_results/ --output ./reports/
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


EXPECTED_FILES = ("summary.json", "trades.csv", "equity_curve.csv")
EXIT_TRAIL = "TRAILING_STOP"
EXIT_STOP = "stop_loss"
EXIT_TIME = "time_exit"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze symbol performance from seasonal backtest folders")
    parser.add_argument("root", help="Path to backtest results root directory")
    parser.add_argument(
        "--output",
        default="",
        help="Optional output directory for HTML report (default: current directory)",
    )
    return parser.parse_args()


def warn(msg: str) -> None:
    print(f"WARNING: {msg}")


def parse_partials_pnl(raw: Any) -> float:
    if raw is None:
        return 0.0
    text = str(raw).strip()
    if text == "" or text.lower() == "nan":
        return 0.0
    try:
        payload = json.loads(text)
        if not isinstance(payload, list):
            return 0.0
        total = 0.0
        for item in payload:
            if isinstance(item, dict):
                total += float(item.get("pnl", 0.0) or 0.0)
        return total
    except Exception:
        return 0.0


def safe_div(n: float, d: float) -> float:
    if d == 0:
        return math.nan
    return n / d


def safe_ratio_with_inf(n: float, d: float) -> float:
    if d == 0:
        if n > 0:
            return math.inf
        return 0.0
    return n / d


def season_sort_key(name: str) -> Tuple[int, int, str]:
    m = re.search(r"(\d{4})[_-](\d{4})", name)
    if not m:
        return (9999, 9999, name)
    return (int(m.group(1)), int(m.group(2)), name)


def season_label(name: str) -> str:
    m = re.search(r"(\d{4})[_-](\d{4})", name)
    if not m:
        return name
    a = int(m.group(1)) % 100
    b = int(m.group(2)) % 100
    return f"{a:02d}-{b:02d}"


def discover_season_dirs(root: Path) -> List[Path]:
    candidates = [p for p in root.iterdir() if p.is_dir()]
    return sorted(candidates, key=lambda p: season_sort_key(p.name))


def load_season(path: Path) -> Optional[Dict[str, Any]]:
    missing = [name for name in EXPECTED_FILES if not (path / name).exists()]
    if missing:
        warn(f"Skipping {path.name}: missing files {', '.join(missing)}")
        return None

    try:
        summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
    except Exception as exc:
        warn(f"Skipping {path.name}: failed to parse summary.json ({exc})")
        return None

    try:
        trades = pd.read_csv(path / "trades.csv")
        equity = pd.read_csv(path / "equity_curve.csv")
    except Exception as exc:
        warn(f"Skipping {path.name}: failed to read CSV files ({exc})")
        return None

    required_trade_cols = {
        "symbol",
        "side",
        "entry_time_ms",
        "exit_time_ms",
        "pnl",
        "reason",
        "partials_json",
    }
    missing_cols = sorted(required_trade_cols - set(trades.columns))
    if missing_cols:
        warn(f"Skipping {path.name}: trades.csv missing columns {', '.join(missing_cols)}")
        return None

    for c in ("entry_time_ms", "exit_time_ms"):
        trades[c] = pd.to_datetime(pd.to_numeric(trades[c], errors="coerce"), unit="ms", errors="coerce", utc=True)

    for c in ("pnl",):
        trades[c] = pd.to_numeric(trades[c], errors="coerce").fillna(0.0)

    trades["symbol"] = trades["symbol"].astype(str).str.upper().str.strip()
    trades["side"] = trades["side"].astype(str).str.lower().str.strip()
    trades["reason"] = trades["reason"].astype(str).str.strip()

    trades["partial_pnl"] = trades["partials_json"].apply(parse_partials_pnl)
    trades["true_pnl"] = trades["pnl"] + trades["partial_pnl"]

    if "time_ms" in equity.columns:
        equity["time_ms"] = pd.to_datetime(pd.to_numeric(equity["time_ms"], errors="coerce"), unit="ms", errors="coerce", utc=True)

    season_name = path.name
    return {
        "season_name": season_name,
        "season_label": season_label(season_name),
        "summary": summary,
        "trades": trades,
        "equity": equity,
        "path": path,
    }


def metric_block(df: pd.DataFrame) -> Dict[str, Any]:
    pnls = pd.to_numeric(df["true_pnl"], errors="coerce").fillna(0.0)
    trade_count = int(len(pnls))
    total_pnl = float(pnls.sum())

    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    win_rate = float((pnls > 0).mean()) if trade_count > 0 else math.nan

    avg_win = float(wins.mean()) if not wins.empty else 0.0
    avg_loss = float(losses.mean()) if not losses.empty else 0.0

    payoff_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else (math.inf if avg_win > 0 else math.nan)

    gross_wins = float(wins.sum()) if not wins.empty else 0.0
    gross_losses = float(losses.sum()) if not losses.empty else 0.0
    profit_factor = gross_wins / abs(gross_losses) if gross_losses < 0 else (math.inf if gross_wins > 0 else math.nan)

    expectancy = (win_rate * avg_win + (1.0 - win_rate) * avg_loss) if trade_count > 0 else math.nan

    reasons = df["reason"].astype(str)
    trail_count = int((reasons == EXIT_TRAIL).sum())
    stop_count = int((reasons == EXIT_STOP).sum())
    time_exit_count = int((reasons == EXIT_TIME).sum())
    trail_stop_ratio = safe_ratio_with_inf(float(trail_count), float(stop_count))

    return {
        "trade_count": trade_count,
        "total_pnl": total_pnl,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff_ratio": payoff_ratio,
        "profit_factor": profit_factor,
        "expectancy": expectancy,
        "trail_count": trail_count,
        "stop_count": stop_count,
        "trail_stop_ratio": trail_stop_ratio,
        "time_exit_count": time_exit_count,
    }


def to_rankable_series(s: pd.Series) -> pd.Series:
    out = pd.to_numeric(s, errors="coerce").copy()
    finite = out[np.isfinite(out)]
    if finite.empty:
        return out.fillna(0.0)
    fmin = float(finite.min())
    fmax = float(finite.max())
    out[np.isposinf(out)] = fmax + 1.0
    out[np.isneginf(out)] = fmin - 1.0
    out = out.fillna(fmin)
    return out


def fmt_money(v: float) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "n/a"
    return f"{v:+.1f}"


def fmt_money_dollar(v: float) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "n/a"
    return f"{v:+.1f}".replace("+", "+$").replace("-", "-$")


def fmt_pct(v: float) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "n/a"
    return f"{v * 100:.1f}%"


def fmt_ratio(v: float) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "n/a"
    if math.isinf(v):
        return "inf"
    return f"{v:.3f}"


def build_analysis(seasons: List[Dict[str, Any]]) -> Dict[str, Any]:
    season_rows: List[Dict[str, Any]] = []
    side_rows: List[Dict[str, Any]] = []
    all_trades = []

    for season in seasons:
        s_name = season["season_name"]
        s_label = season["season_label"]
        trades = season["trades"].copy()
        all_trades.append(trades.assign(season=s_name, season_label=s_label))

        for symbol, g in trades.groupby("symbol"):
            row = {
                "season": s_name,
                "season_label": s_label,
                "symbol": symbol,
            }
            row.update(metric_block(g))
            season_rows.append(row)

            for side in ("long", "short"):
                gs = g[g["side"] == side]
                if gs.empty:
                    continue
                srow = {
                    "season": s_name,
                    "season_label": s_label,
                    "symbol": symbol,
                    "side": side,
                }
                srow.update(metric_block(gs))
                side_rows.append(srow)

    season_df = pd.DataFrame(season_rows)
    side_df = pd.DataFrame(side_rows)
    all_trades_df = pd.concat(all_trades, ignore_index=True)

    if season_df.empty:
        raise RuntimeError("No valid trades found across season folders")

    symbol_rows: List[Dict[str, Any]] = []
    for symbol, g in season_df.groupby("symbol"):
        agg = {
            "symbol": symbol,
            "trade_count": int(g["trade_count"].sum()),
            "total_pnl": float(g["total_pnl"].sum()),
            "trail_count": int(g["trail_count"].sum()),
            "stop_count": int(g["stop_count"].sum()),
            "time_exit_count": int(g["time_exit_count"].sum()),
            "seasons_present": int(g["season"].nunique()),
            "seasons_profitable": int((g["total_pnl"] > 0).sum()),
        }

        # Recompute trade-level expectancy metrics from all trades for this symbol.
        symbol_trades = all_trades_df[all_trades_df["symbol"] == symbol]
        m = metric_block(symbol_trades)
        agg.update(
            {
                "win_rate": m["win_rate"],
                "avg_win": m["avg_win"],
                "avg_loss": m["avg_loss"],
                "payoff_ratio": m["payoff_ratio"],
                "profit_factor": m["profit_factor"],
                "expectancy": m["expectancy"],
                "trail_stop_ratio": safe_ratio_with_inf(float(agg["trail_count"]), float(agg["stop_count"])),
            }
        )
        agg["consistency_score"] = safe_div(float(agg["seasons_profitable"]), float(agg["seasons_present"]))
        symbol_rows.append(agg)

    symbol_df = pd.DataFrame(symbol_rows)

    side_agg_rows: List[Dict[str, Any]] = []
    for (symbol, side), g in side_df.groupby(["symbol", "side"]):
        side_slice = all_trades_df[
            (all_trades_df["symbol"] == symbol)
            & (all_trades_df["side"] == side)
        ]
        side_metrics = metric_block(side_slice)
        side_agg_rows.append(
            {
                "symbol": symbol,
                "side": side,
                "trade_count": int(g["trade_count"].sum()),
                "total_pnl": float(g["total_pnl"].sum()),
                "trail_count": int(g["trail_count"].sum()),
                "stop_count": int(g["stop_count"].sum()),
                "win_rate": side_metrics["win_rate"],
                "profit_factor": side_metrics["profit_factor"],
            }
        )

    side_agg = pd.DataFrame(side_agg_rows)
    if not side_agg.empty:
        side_agg["trail_stop_ratio"] = side_agg.apply(
            lambda r: safe_ratio_with_inf(float(r["trail_count"]), float(r["stop_count"])), axis=1
        )

    eligible = symbol_df[symbol_df["seasons_present"] >= 4].copy()

    if not eligible.empty:
        eligible["pct_total_pnl"] = to_rankable_series(eligible["total_pnl"]).rank(method="average", pct=True)
        eligible["pct_consistency"] = to_rankable_series(eligible["consistency_score"]).rank(method="average", pct=True)
        eligible["pct_profit_factor"] = to_rankable_series(eligible["profit_factor"]).rank(method="average", pct=True)
        eligible["pct_ts"] = to_rankable_series(eligible["trail_stop_ratio"]).rank(method="average", pct=True)

        eligible["composite_score"] = (
            0.35 * eligible["pct_total_pnl"]
            + 0.30 * eligible["pct_consistency"]
            + 0.20 * eligible["pct_profit_factor"]
            + 0.15 * eligible["pct_ts"]
        )
        eligible = eligible.sort_values(["composite_score", "total_pnl"], ascending=[False, False]).reset_index(drop=True)
        eligible["rank"] = np.arange(1, len(eligible) + 1)
    else:
        eligible["composite_score"] = []
        eligible["rank"] = []

    infrequent = symbol_df[symbol_df["seasons_present"] < 4].sort_values("symbol")

    # Exclude list: PF < 0.90 in 3+ seasons.
    exclude_rows: List[Dict[str, Any]] = []
    for symbol, g in season_df.groupby("symbol"):
        pf_bad = int((pd.to_numeric(g["profit_factor"], errors="coerce") < 0.90).sum())
        if pf_bad < 3:
            continue

        seasons_profitable = int((g["total_pnl"] > 0).sum())
        ts_bad = int((pd.to_numeric(g["trail_stop_ratio"], errors="coerce") < 1.0).sum())

        reason = "profit factor < 0.90 in 3+ seasons"
        if seasons_profitable == 0:
            reason = "never profitable"
        elif ts_bad >= 3:
            reason = "persistent trail/stop < 1.0"

        per_season_pf = {
            row["season_label"]: row["profit_factor"]
            for _, row in g.iterrows()
        }
        exclude_rows.append(
            {
                "symbol": symbol,
                "reason": reason,
                "pf_bad_seasons": pf_bad,
                "pf_by_season": per_season_pf,
            }
        )

    exclude_df = pd.DataFrame(exclude_rows).sort_values(["pf_bad_seasons", "symbol"], ascending=[False, True]) if exclude_rows else pd.DataFrame(columns=["symbol", "reason", "pf_bad_seasons", "pf_by_season"])

    date_min = all_trades_df["entry_time_ms"].min()
    date_max = all_trades_df["exit_time_ms"].max()

    season_labels = [s["season_label"] for s in seasons]

    season_pnl_pivot = (
        season_df.pivot_table(index="symbol", columns="season_label", values="total_pnl", aggfunc="sum")
        .reindex(columns=season_labels)
        .sort_index()
    )

    season_presence = (
        season_df.assign(is_profitable=season_df["total_pnl"] > 0)
        .pivot_table(index="symbol", columns="season_label", values="is_profitable", aggfunc="first")
        .reindex(columns=season_labels)
        .sort_index()
    )

    return {
        "season_df": season_df,
        "side_df": side_df,
        "symbol_df": symbol_df,
        "eligible_df": eligible,
        "side_agg": side_agg,
        "exclude_df": exclude_df,
        "infrequent_df": infrequent,
        "season_pnl_pivot": season_pnl_pivot,
        "season_presence": season_presence,
        "season_labels": season_labels,
        "date_min": date_min,
        "date_max": date_max,
        "all_trades_count": int(len(all_trades_df)),
    }


def print_terminal_report(root: Path, seasons: List[Dict[str, Any]], analysis: Dict[str, Any], html_path: Path) -> None:
    eligible = analysis["eligible_df"]
    symbol_df = analysis["symbol_df"]
    infrequent = analysis["infrequent_df"]
    side_agg = analysis["side_agg"]
    exclude_df = analysis["exclude_df"]

    date_min = analysis["date_min"]
    date_max = analysis["date_max"]
    date_text = "n/a"
    if pd.notna(date_min) and pd.notna(date_max):
        date_text = f"{date_min.date().isoformat()} -> {date_max.date().isoformat()}"

    print(
        f"Path={root} | seasons={len(seasons)} | date_range={date_text} | "
        f"symbols={len(symbol_df)} | symbols_4plus={len(eligible)}"
    )

    print("\nTOP 10 (Composite Ranked)")
    print("Rank | Symbol     | TotalPnL | WR%   | PF    | TS-Ratio | Seasons | Composite")
    top10 = eligible.head(10)
    for _, row in top10.iterrows():
        print(
            f"{int(row['rank']):>4} | {row['symbol']:<10} | {fmt_money(float(row['total_pnl'])):>8} | "
            f"{fmt_pct(float(row['win_rate'])):>5} | {fmt_ratio(float(row['profit_factor'])):>5} | "
            f"{fmt_ratio(float(row['trail_stop_ratio'])):>8} | {int(row['seasons_present']):>7} | "
            f"{fmt_ratio(float(row['composite_score'])):>9}"
        )

    print("\nSuggested focus lists")
    for n in (3, 5, 10):
        take = eligible.head(n)
        items = ", ".join(f"{r['symbol']} ({fmt_ratio(float(r['composite_score']))})" for _, r in take.iterrows())
        print(f"Top {n}: {items if items else 'n/a'}")

    print("\nSIDE BREAKDOWN (Top 10 symbols)")
    for _, row in top10.iterrows():
        sym = row["symbol"]
        for side in ("long", "short"):
            g = side_agg[(side_agg["symbol"] == sym) & (side_agg["side"] == side)]
            if g.empty:
                print(f"  {sym:<10} {side:<5}: n=0  WR=n/a  PF=n/a  TS=n/a  PnL=n/a")
                continue
            rr = g.iloc[0]
            print(
                f"  {sym:<10} {side:<5}: n={int(rr['trade_count'])}  "
                f"WR={fmt_pct(float(rr['win_rate']))}  PF={fmt_ratio(float(rr['profit_factor']))}  "
                f"TS={fmt_ratio(float(rr['trail_stop_ratio']))}x  PnL={fmt_money_dollar(float(rr['total_pnl']))}"
            )

    print("\nEXCLUDE LIST")
    if exclude_df.empty:
        print("  none")
    else:
        for _, row in exclude_df.iterrows():
            print(f"  {row['symbol']}: {row['reason']}")

    if not infrequent.empty:
        names = ", ".join(infrequent["symbol"].tolist())
        print(f"\nInfrequent symbols (<4 seasons, heatmap only): {names}")

    print(f"\nHTML report: {html_path}")


def season_dots_row(symbol: str, season_labels: List[str], season_presence: pd.DataFrame) -> str:
    dots = []
    for label in season_labels:
        val = season_presence.loc[symbol, label] if symbol in season_presence.index and label in season_presence.columns else np.nan
        cls = "dot dot-absent"
        title = f"{label}: absent"
        if pd.notna(val):
            if bool(val):
                cls = "dot dot-pos"
                title = f"{label}: profitable"
            else:
                cls = "dot dot-neg"
                title = f"{label}: loss"
        dots.append(f"<span class=\"{cls}\" title=\"{html.escape(title)}\"></span>")
    return "".join(dots)


def pnl_cell_class(v: Any) -> str:
    if pd.isna(v):
        return "pnl-na"
    if float(v) > 0:
        return "pnl-pos"
    if float(v) < 0:
        return "pnl-neg"
    return "pnl-zero"


def heat_color(v: Any, max_abs: float) -> str:
    if pd.isna(v):
        return "#b3b3b3"
    val = float(v)
    if max_abs <= 0:
        return "#ffffff"
    x = max(-1.0, min(1.0, val / max_abs))
    if x >= 0:
        r = int(255 - (120 * x))
        g = int(255 - (35 * x))
        b = int(255 - (120 * x))
    else:
        t = abs(x)
        r = int(255 - (35 * t))
        g = int(255 - (120 * t))
        b = int(255 - (120 * t))
    return f"rgb({r},{g},{b})"


def build_html(root: Path, seasons: List[Dict[str, Any]], analysis: Dict[str, Any]) -> str:
    eligible = analysis["eligible_df"]
    side_agg = analysis["side_agg"]
    season_pivot = analysis["season_pnl_pivot"]
    season_presence = analysis["season_presence"]
    season_labels = analysis["season_labels"]
    exclude_df = analysis["exclude_df"]

    top3 = eligible.head(3)
    top5 = eligible.head(5)
    top10 = eligible.head(10)

    date_min = analysis["date_min"]
    date_max = analysis["date_max"]
    date_text = "n/a"
    if pd.notna(date_min) and pd.notna(date_max):
        date_text = f"{date_min.date().isoformat()} -> {date_max.date().isoformat()}"

    ranked_rows = []
    for _, row in eligible.iterrows():
        symbol = row["symbol"]
        season_cells = []
        for label in season_labels:
            val = season_pivot.loc[symbol, label] if symbol in season_pivot.index and label in season_pivot.columns else np.nan
            season_cells.append(f"<td class=\"{pnl_cell_class(val)}\">{fmt_money(float(val)) if pd.notna(val) else 'n/a'}</td>")

        ranked_rows.append(
            "<tr>"
            f"<td>{int(row['rank'])}</td>"
            f"<td><b>{html.escape(symbol)}</b></td>"
            f"<td>{fmt_money(float(row['total_pnl']))}</td>"
            f"<td>{fmt_pct(float(row['win_rate']))}</td>"
            f"<td>{fmt_ratio(float(row['profit_factor']))}</td>"
            f"<td>{fmt_ratio(float(row['trail_stop_ratio']))}</td>"
            f"<td class=\"season-dots\">{season_dots_row(symbol, season_labels, season_presence)}</td>"
            + "".join(season_cells)
            + "</tr>"
        )

    side_rows = []
    for _, row in top10.iterrows():
        symbol = row["symbol"]
        for side in ("long", "short"):
            g = side_agg[(side_agg["symbol"] == symbol) & (side_agg["side"] == side)]
            if g.empty:
                side_rows.append(
                    "<tr class=\"side-sep\">"
                    f"<td>{html.escape(symbol)}</td><td>{side}</td><td>0</td><td>n/a</td><td>n/a</td><td>n/a</td><td>n/a</td>"
                    "</tr>"
                )
                continue
            rr = g.iloc[0]
            side_rows.append(
                "<tr class=\"side-sep\">"
                f"<td>{html.escape(symbol)}</td>"
                f"<td>{html.escape(side)}</td>"
                f"<td>{int(rr['trade_count'])}</td>"
                f"<td>{fmt_pct(float(rr['win_rate']))}</td>"
                f"<td>{fmt_ratio(float(rr['profit_factor']))}</td>"
                f"<td>{fmt_ratio(float(rr['trail_stop_ratio']))}</td>"
                f"<td>{fmt_money(float(rr['total_pnl']))}</td>"
                "</tr>"
            )

    heat_max_abs = 0.0
    if not season_pivot.empty:
        vals = season_pivot.values.astype(float)
        vals = vals[np.isfinite(vals)]
        if vals.size > 0:
            heat_max_abs = float(np.max(np.abs(vals)))

    heat_rows = []
    for symbol in sorted(season_pivot.index.tolist()):
        tds = [f"<td><b>{html.escape(symbol)}</b></td>"]
        for label in season_labels:
            val = season_pivot.loc[symbol, label] if label in season_pivot.columns else np.nan
            color = heat_color(val, heat_max_abs)
            text = fmt_money(float(val)) if pd.notna(val) else "n/a"
            tds.append(f"<td style=\"background:{color}\">{text}</td>")
        heat_rows.append("<tr>" + "".join(tds) + "</tr>")

    exclude_rows = []
    if exclude_df.empty:
        exclude_rows.append("<tr><td colspan=\"3\">none</td></tr>")
    else:
        for _, row in exclude_df.iterrows():
            pf_map = row["pf_by_season"]
            per = []
            for label in season_labels:
                v = pf_map.get(label)
                per.append(f"{label}:{fmt_ratio(float(v))}" if v is not None else f"{label}:n/a")
            exclude_rows.append(
                "<tr>"
                f"<td>{html.escape(str(row['symbol']))}</td>"
                f"<td>{html.escape(str(row['reason']))}</td>"
                f"<td>{html.escape(', '.join(per))}</td>"
                "</tr>"
            )

    def focus_items(df: pd.DataFrame) -> str:
        if df.empty:
            return "<li>n/a</li>"
        return "".join(
            f"<li><span>{html.escape(str(r['symbol']))}</span><b>{fmt_ratio(float(r['composite_score']))}</b></li>"
            for _, r in df.iterrows()
        )

    season_headers_html = "".join(f"<th>{html.escape(label)}</th>" for label in season_labels)

    return f"""<!doctype html>
<html lang=\"en\">
<head>
<meta charset=\"utf-8\" />
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
<title>Symbol Analysis Report</title>
<style>
:root {{
  --bg: #f7f8fa;
  --fg: #111827;
  --muted: #4b5563;
  --card: #ffffff;
  --border: #d1d5db;
  --accent1: #0ea5e9;
  --accent2: #16a34a;
  --accent3: #f59e0b;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #0b1020;
    --fg: #e5e7eb;
    --muted: #9ca3af;
    --card: #111827;
    --border: #374151;
    --accent1: #38bdf8;
    --accent2: #22c55e;
    --accent3: #fbbf24;
  }}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; padding: 20px; background: var(--bg); color: var(--fg); font: 14px/1.4 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif; }}
h1, h2 {{ margin: 0 0 12px 0; }}
.small {{ color: var(--muted); }}
.section {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 14px; margin: 14px 0; overflow-x: auto; }}
.summary-grid {{ display: grid; gap: 10px; grid-template-columns: repeat(4, minmax(160px, 1fr)); }}
.summary-item {{ border: 1px solid var(--border); border-radius: 8px; padding: 10px; }}
.cards {{ display: grid; gap: 10px; grid-template-columns: repeat(3, minmax(220px, 1fr)); }}
.card {{ border: 2px solid var(--border); border-radius: 8px; padding: 10px; }}
.card.top3 {{ border-color: var(--accent1); }}
.card.top5 {{ border-color: var(--accent2); }}
.card.top10 {{ border-color: var(--accent3); }}
.card ul {{ margin: 8px 0 0 0; padding: 0; list-style: none; }}
.card li {{ display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px dashed var(--border); }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid var(--border); padding: 6px 8px; white-space: nowrap; text-align: right; }}
th:first-child, td:first-child {{ text-align: left; }}
th:nth-child(2), td:nth-child(2) {{ text-align: left; }}
.season-dots {{ text-align: left; }}
.dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 999px; margin-right: 5px; border: 1px solid rgba(0,0,0,.2); }}
.dot-pos {{ background: #22c55e; }}
.dot-neg {{ background: #ef4444; }}
.dot-absent {{ background: #9ca3af; }}
.pnl-pos {{ color: #15803d; font-weight: 600; }}
.pnl-neg {{ color: #b91c1c; font-weight: 600; }}
.pnl-zero {{ color: var(--muted); }}
.pnl-na {{ color: var(--muted); }}
.side-sep td {{ border-top: 2px solid var(--border); }}
.legend {{ display: flex; align-items: center; gap: 10px; }}
.legend-bar {{ width: 220px; height: 12px; border-radius: 8px; border: 1px solid var(--border); background: linear-gradient(90deg, rgb(220,120,120), rgb(255,255,255), rgb(120,220,120)); }}
</style>
</head>
<body>
  <h1>Symbol Performance Analysis</h1>
  <div class=\"small\">Root: {html.escape(str(root))}</div>

  <section class=\"section\">
    <h2>1. Run summary bar</h2>
    <div class=\"summary-grid\">
      <div class=\"summary-item\"><b>Season count</b><div>{len(seasons)}</div></div>
      <div class=\"summary-item\"><b>Date range</b><div>{html.escape(date_text)}</div></div>
      <div class=\"summary-item\"><b>Symbol count</b><div>{int(len(analysis['symbol_df']))}</div></div>
      <div class=\"summary-item\"><b>Total trades</b><div>{analysis['all_trades_count']}</div></div>
    </div>
  </section>

  <section class=\"section\">
    <h2>2. Focus list cards</h2>
    <div class=\"cards\">
      <div class=\"card top3\"><b>Top 3</b><ul>{focus_items(top3)}</ul></div>
      <div class=\"card top5\"><b>Top 5</b><ul>{focus_items(top5)}</ul></div>
      <div class=\"card top10\"><b>Top 10</b><ul>{focus_items(top10)}</ul></div>
    </div>
  </section>

  <section class=\"section\">
    <h2>3. Full ranked table</h2>
    <table>
      <thead>
        <tr>
          <th>Rank</th><th>Symbol</th><th>Total PnL</th><th>Win Rate</th><th>Profit Factor</th><th>Trail/Stop</th><th>Seasons</th>
          {season_headers_html}
        </tr>
      </thead>
      <tbody>
        {''.join(ranked_rows) if ranked_rows else '<tr><td colspan="99">No symbols with 4+ seasons present.</td></tr>'}
      </tbody>
    </table>
  </section>

  <section class=\"section\">
    <h2>4. Side breakdown table</h2>
    <table>
      <thead>
        <tr><th>Symbol</th><th>Side</th><th>Trades</th><th>Win Rate</th><th>Profit Factor</th><th>Trail/Stop Ratio</th><th>Total PnL</th></tr>
      </thead>
      <tbody>
        {''.join(side_rows) if side_rows else '<tr><td colspan="7">No ranked symbols available.</td></tr>'}
      </tbody>
    </table>
  </section>

  <section class=\"section\">
    <h2>5. Season-by-season heatmap</h2>
    <div class=\"legend\"><span class=\"small\">deep red</span><div class=\"legend-bar\"></div><span class=\"small\">deep green</span></div>
    <table>
      <thead><tr><th>Symbol</th>{season_headers_html}</tr></thead>
      <tbody>{''.join(heat_rows)}</tbody>
    </table>
  </section>

  <section class=\"section\">
    <h2>6. Exclude list</h2>
    <table>
      <thead><tr><th>Symbol</th><th>Reason</th><th>Profit factor by season</th></tr></thead>
      <tbody>{''.join(exclude_rows)}</tbody>
    </table>
  </section>

  <section class=\"section\">
    <h2>7. Methodology note</h2>
    <p class=\"small\">
      Composite score uses weighted percentile ranks across symbols with 4+ seasons present:
      total_pnl (35%), consistency_score (30%), profit_factor (20%), trail_stop_ratio (15%).
      Trade PnL accounting uses true trade PnL = trades.pnl + sum(partial['pnl'] from partials_json);
      trades.pnl alone is not treated as final trade result.
    </p>
  </section>
</body>
</html>
"""


def main() -> int:
    args = parse_args()
    root = Path(args.root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        print(f"ERROR: invalid root directory: {root}")
        return 1

    season_dirs = discover_season_dirs(root)
    if not season_dirs:
        print(f"ERROR: no season subfolders found in {root}")
        return 1

    seasons: List[Dict[str, Any]] = []
    for d in season_dirs:
        loaded = load_season(d)
        if loaded is not None:
            seasons.append(loaded)

    if not seasons:
        print("ERROR: no valid seasons to analyze")
        return 1

    analysis = build_analysis(seasons)

    out_dir = Path(args.output).expanduser().resolve() if args.output else Path.cwd().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    html_path = out_dir / f"symbol_analysis_{ts}.html"

    html_content = build_html(root, seasons, analysis)
    html_path.write_text(html_content, encoding="utf-8")

    print_terminal_report(root, seasons, analysis, html_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
