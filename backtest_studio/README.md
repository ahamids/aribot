# Backtest Studio

Backtest Studio provides a FastAPI backend plus a single-file React SPA for running backfills, strategy runs, and parameter sweeps.

## Files

- backtest_studio/api.py
- backtest_studio/studio.html
- backtest_studio/run.sh

## Requirements

- Python 3.10+
- `fastapi`, `uvicorn`, `pydantic`

## Environment Variables

- `BACKTEST_SCRIPT` (default: `backtest_aribot.py`)
- `SWEEP_SCRIPT` (default: `sweep_recipe_permutations.py`)
- `LEVERAGE_FILE` (default: `leverage_buckets.json`)
- `RESULTS_BASE_DIR` (default: `backtest_results`)
- `STUDIO_PORT` (default: `8766`)
- `PYTHON_CMD` (default: `python`)

## Run

From repository root:

```bash
bash backtest_studio/run.sh
```

Or directly:

```bash
python -m uvicorn backtest_studio.api:app --host 0.0.0.0 --port 8766
```

Open:

- `http://localhost:8766/`

## API Endpoints

- `GET /api/health`
- `GET /api/buckets`
- `GET /api/recent-runs`
- `POST /api/backfill/start`
- `POST /api/run/start`
- `GET /api/stream/{run_id}` (SSE)
- `GET /api/run/{run_id}/status`
- `POST /api/run/{run_id}/cancel`
- `POST /api/sweep/start`
- `GET /api/results?dir=PATH`
- `GET /api/sweep-results?dir=PATH`
- `GET /api/recipes`
- `POST /api/recipes`
- `DELETE /api/recipes/{name}`

## Behavior Notes

- Process management uses module-level maps:
  - `active_processes: dict[str, Process]`
  - `process_logs: dict[str, list[str]]`
- Concurrency limits:
  - max 1 active backtest (shared by backfill/run)
  - max 1 active sweep
- SSE stream sends `log` updates and a final `done` event:
  - `{"type":"done","exit_code":int,"output_dir":str}`
  - Keepalive comments are emitted every 15 seconds.
- Recipes are persisted in `RESULTS_BASE_DIR/recipes.json` with atomic temp-file + rename writes.
- `GET /api/results` returns:
  - `summary`, `equity_curve`, `trades`, `season_breakdown`, `side_breakdown`, `exclude_list`, `run_config`

## Frontend Features

- Three tabs: Run, Analysis, Sweep
- Run tab:
  - Backfill and Run subcommands
  - Recipe load/save
  - Dynamic partial exits with validation (`sum(sizes) <= 1.0`)
  - Live SSE console with cancel and View Results
- Analysis tab:
  - Directory loader + recent runs dropdown
  - Summary cards
  - Recharts equity chart with starting-balance reference line
  - Sortable per-symbol table
  - Side breakdown driven by selected symbol
  - Season heatmap and exclude list
- Sweep tab:
  - Permutation preview
  - Start disabled for `> 500` combinations
  - Ranked results with top-3 gold/silver/bronze styling
