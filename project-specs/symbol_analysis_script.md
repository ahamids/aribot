# Symbol performance analysis script — project spec
**For**: Agents Orchestrator autonomous pipeline
**Repo**: aribot
**Deliverable**: A standalone Python script `analyze_symbols.py` and
an accompanying HTML report template. No changes to any existing bot files.

---

## Purpose

A self-contained, on-demand analysis script that reads backtest result
folders and produces both a terminal summary and a self-contained HTML
report covering symbol-level trading performance across all available
seasons.

---

## Input — backtest folder structure

The script receives one argument: the path to a backtest results root
directory. That directory contains one or more season subfolders, each
containing exactly three files:

- `summary.json` — season-level aggregate stats and run config
- `trades.csv` — one row per closed trade with columns:
  `symbol, side, entry_time_ms, exit_time_ms, entry_price, exit_price,
  quantity, pnl, pnl_pct, reason, leverage, leverage_tier, partials_json`
- `equity_curve.csv` — columns: `time_ms, balance, unrealized_pnl, equity`

**Critical accounting rule**: `trades.csv` records final-exit PnL only.
Partial profits are stored in the `partials_json` column as a JSON array
of objects with a `pnl` key. True per-trade PnL = `trades.pnl` +
`sum(partial['pnl'] for partial in partials_json)`. All PnL calculations
in this script must use this combined figure. Never use `trades.pnl`
alone as the basis for win/loss or expectancy metrics.

Exit reason values in the data: `TRAILING_STOP`, `stop_loss`,
`time_exit`, `end_of_test`.

---

## Usage

```bash
python analyze_symbols.py /path/to/backtest_results/
python analyze_symbols.py /path/to/backtest_results/ --output ./reports/
```

`--output` is optional. If omitted, the HTML report is saved in the
current working directory as `symbol_analysis_YYYYMMDD_HHMMSS.html`.

---

## Metrics to compute — per symbol, per season, and aggregated

### True trade-level PnL (always use combined final + partial)
- `total_pnl` — sum of true trade PnL across all trades
- `win_rate` — fraction of trades where true trade PnL > 0
- `avg_win` — mean true PnL of winning trades
- `avg_loss` — mean true PnL of losing trades
- `payoff_ratio` — abs(avg_win / avg_loss)
- `profit_factor` — gross_wins / abs(gross_losses)
- `expectancy` — (win_rate × avg_win) + ((1 - win_rate) × avg_loss)
- `trade_count`

### Exit reason metrics
- `trail_count` — trades exiting via TRAILING_STOP
- `stop_count` — trades exiting via stop_loss
- `trail_stop_ratio` — trail_count / stop_count (key ranking signal)
- `time_exit_count`

### Side breakdown (long vs short) — per symbol per season AND aggregated
For each of long and short separately:
- `trade_count`, `total_pnl`, `win_rate`, `profit_factor`,
  `trail_stop_ratio`
This must appear in both the terminal output and the HTML report.

### Consistency
- `seasons_present` — number of seasons the symbol appeared in
- `seasons_profitable` — seasons where total_pnl > 0
- `consistency_score` — seasons_profitable / seasons_present

### Composite ranking score
Weighted percentile rank across all symbols with 4+ seasons present:
- total_pnl rank: 35%
- consistency_score rank: 30%
- profit_factor rank: 20%
- trail_stop_ratio rank: 15%

Higher composite score = better. Rank symbols 1 to N by composite score.

---

## Terminal output

Print to stdout in this order:

1. Header line: path analysed, number of seasons found, date range
   covered, total symbols found, symbols with 4+ seasons.

2. TOP 10 table (composite ranked), columns:
   Rank | Symbol | TotalPnL | WR% | PF | TS-Ratio | Seasons | Composite

3. Suggested focus lists:
   - Top 3 symbols (print names + composite score)
   - Top 5 symbols
   - Top 10 symbols

4. SIDE BREAKDOWN for top 10 symbols — for each symbol one compact
   line per side:
   `  ADAUSDT  long : n=72  WR=54.2%  PF=1.21  TS=1.38x  PnL=+$48.3`
   `  ADAUSDT  short: n=71  WR=63.1%  PF=1.37  TS=1.61x  PnL=+$28.9`

5. EXCLUDE LIST — symbols with profit_factor < 0.90 in 3+ seasons,
   labelled with the reason (e.g. "persistent trail/stop < 1.0",
   "never profitable").

6. Footer line: HTML report path.

All monetary values formatted to 1 decimal place with sign prefix.
All percentages to 1 decimal place. All ratios to 3 decimal places.

---

## HTML report

Self-contained single-file HTML. No external dependencies — all CSS
and JS must be inline. Must render correctly when opened directly from
the filesystem (no server). Dark mode support via
`prefers-color-scheme: dark`.

### Sections in order:

**1. Run summary bar**
Season count, date range, symbol count, total trades across all seasons.

**2. Focus list cards**
Three side-by-side cards: Top 3 / Top 5 / Top 10.
Each card lists the symbol names with their composite score.
Visually distinct (use border accent colours to differentiate tiers).

**3. Full ranked table**
One row per symbol (4+ seasons only). Columns:
Rank | Symbol | Total PnL | Win Rate | Profit Factor | Trail/Stop |
Seasons (dots: green=profitable, red=loss, grey=absent) | 21-22 | 22-23 |
23-24 | 24-25 | 25-26 (per-season PnL cells, colour-coded pos/neg)

**4. Side breakdown table**
For each of the top 10 ranked symbols, two rows (long / short) showing:
Symbol | Side | Trades | Win Rate | Profit Factor | Trail/Stop Ratio |
Total PnL
Group rows by symbol with a subtle separator between symbols.

**5. Season-by-season heatmap**
Grid: symbols as rows, seasons as columns.
Cell value = total_pnl for that symbol/season.
Colour scale: deep red (large negative) → white (zero) → deep green
(large positive). Grey cell = symbol not present in that season.
Include the colour scale legend.

**6. Exclude list**
Table of symbols that fail the exclusion criteria with their
profit_factor per season and the disqualifying reason.

**7. Methodology note**
One short paragraph explaining the composite score weights and the
partial PnL accounting rule (trades.pnl alone is not true PnL).

---

## Code requirements

- Python 3.10+. Dependencies: `pandas`, `numpy`. No other third-party
  libraries. Standard library only beyond those two.
- All HTML/CSS/JS generated programmatically as strings within the
  Python script. No Jinja2 or template files.
- Single file: `analyze_symbols.py`. No supporting modules.
- The script must handle seasons folders that are missing any of the
  three expected files — skip that folder with a printed warning, do not
  crash.
- Must handle symbols that appear in only 1, 2, or 3 seasons — include
  them in the heatmap but exclude them from the composite ranking and
  focus lists. Print a note in the terminal output listing these
  infrequent symbols separately.
- `partials_json` parsing must be wrapped in try/except — treat
  malformed rows as zero partial PnL, do not crash.
- Timestamp conversion: all `_ms` columns are Unix milliseconds.
  Convert with `pd.to_datetime(col, unit='ms')`.

---

## File to produce

- `analyze_symbols.py` — the complete, runnable script

---

## Acceptance criteria

1. `python analyze_symbols.py /path/to/backtest_results/` runs without
   error on the five-season dataset structure described above.
2. Terminal output matches the section order specified.
3. HTML report opens in a browser, all six sections visible, dark mode
   works.
4. Top-ranked symbol in terminal and HTML matches the manual calculation:
   ADA should rank #1 given its 5/5 consistent profitability.
5. Side breakdown appears for every top-10 symbol in both terminal and
   HTML with no missing rows.
6. A symbol present in only 2 seasons appears in the heatmap but not in
   the composite ranking table.
7. A deliberately malformed `partials_json` value in a test row does not
   crash the script.

---

## Orchestration pipeline

`agents-orchestrator → project-manager-senior → backend-architect →
senior-developer + copilot-inline → api-tester → reality-checker`

The backend-architect must produce the data model and function
signatures before any code is written. The senior-developer implements
against those signatures. The api-tester validates acceptance criteria
1–7 above against the actual five-season dataset. The reality-checker
signs off only after all seven pass.

Single branch: `feature/symbol-analysis-script`.
One PR. No changes outside `analyze_symbols.py`.