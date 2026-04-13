import asyncio
import json
import os
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field, model_validator

BACKTEST_SCRIPT = os.getenv("BACKTEST_SCRIPT", "backtest_aribot.py")
SWEEP_SCRIPT = os.getenv("SWEEP_SCRIPT", "sweep_recipe_permutations.py")
LEVERAGE_FILE = os.getenv("LEVERAGE_FILE", "leverage_buckets.json")
RESULTS_BASE_DIR = os.getenv("RESULTS_BASE_DIR", "backtest_results")
STUDIO_PORT = int(os.getenv("STUDIO_PORT", "8766"))
PYTHON_CMD = os.getenv("PYTHON_CMD", "python")

MAX_LOG_LINES = 5000
PING_SECONDS = 15.0

active_processes: dict[str, asyncio.subprocess.Process] = {}
process_logs: dict[str, list[str]] = {}
run_meta: dict[str, dict[str, Any]] = {}
run_tasks: dict[str, dict[str, asyncio.Task[Any]]] = {}

RESULTS_DIR = Path(RESULTS_BASE_DIR)
RECIPES_PATH = RESULTS_DIR / "recipes.json"
STUDIO_HTML = Path(__file__).with_name("studio.html")


class BackfillStartRequest(BaseModel):
    db: str
    symbols: list[str] | None = None
    bucket: Literal["major", "large_alt", "mid_cap"] | None = None
    start_ms: int
    end_ms: int
    interval: Literal["1h", "4h", "1d"] = "1h"
    limit: int = 1000
    sleep: float = 0.5
    max_retries: int = 3
    output_dir: str = "backtest_results"
    manifest_label: str | None = None

    @model_validator(mode="after")
    def validate_symbol_source(self) -> "BackfillStartRequest":
        has_symbols = bool(self.symbols)
        has_bucket = bool(self.bucket)
        if has_symbols == has_bucket:
            raise ValueError("Provide exactly one of symbols or bucket.")
        return self


class RunStartRequest(BaseModel):
    db: str
    symbols: list[str] | None = None
    bucket: Literal["major", "large_alt", "mid_cap"] | None = None
    output_dir: str = "backtest_results"
    signal_source: Literal["ohlc4", "close", "hl2"] | None = None
    wma_period: int | None = None
    wma_offset: int | None = None
    regime_btc_symbol: str | None = None
    regime_source: Literal["ohlc4", "close", "hl2"] | None = None
    regime_wma_period: int | None = None
    regime_wma_offset: int | None = None
    hard_stop_pct: float | None = None
    trail_activation_pct: float | None = None
    trail_callback_pct: float | None = None
    partial_levels: list[float] | None = None
    partial_sizes: list[float] | None = None
    time_exit_hours: int | None = None
    atr_period: int | None = None
    atr_cutoff_pct: float | None = None
    atr_size_scalar: float | None = None
    major_leverage: int | None = None
    large_alt_leverage: int | None = None
    mid_cap_leverage: int | None = None
    default_leverage: int | None = None

    @model_validator(mode="after")
    def validate_fields(self) -> "RunStartRequest":
        has_symbols = bool(self.symbols)
        has_bucket = bool(self.bucket)
        if has_symbols == has_bucket:
            raise ValueError("Provide exactly one of symbols or bucket.")
        levels = self.partial_levels or []
        sizes = self.partial_sizes or []
        if levels or sizes:
            if len(levels) != len(sizes):
                raise ValueError("partial_levels and partial_sizes must have equal length.")
        return self


class SweepStartRequest(BaseModel):
    db: str
    output_dir: str
    bucket: Literal["major", "large_alt", "mid_cap"]
    wma_periods: list[int]
    hard_stop_pcts: list[float]
    trail_activation_pcts: list[float]
    trail_callback_pcts: list[float]
    atr_cutoff_pcts: list[float]


class RecipeUpsertRequest(BaseModel):
    name: str
    config: dict[str, Any]


app = FastAPI(title="Backtest Studio API", version="1.0.0")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_dir(path_value: str) -> Path:
    p = Path(path_value)
    if p.is_absolute():
        return p
    return RESULTS_DIR / p


def enforce_slot(kind: str) -> None:
    for rid, proc in active_processes.items():
        meta = run_meta.get(rid, {})
        if meta.get("kind") == kind and proc.returncode is None:
            raise HTTPException(status_code=409, detail=f"An active {kind} process is already running.")


def add_args(args: list[str], flag: str, value: Any) -> None:
    if value is None:
        return
    args.extend([flag, str(value)])


def add_multi(args: list[str], flag: str, values: list[Any] | None) -> None:
    if not values:
        return
    args.append(flag)
    args.extend(str(v) for v in values)


def build_backfill_args(payload: BackfillStartRequest) -> list[str]:
    args = [PYTHON_CMD, BACKTEST_SCRIPT, "backfill"]
    add_args(args, "--db", payload.db)
    if payload.symbols:
        args.append("--symbols")
        args.extend(payload.symbols)
    if payload.bucket:
        add_args(args, "--bucket", payload.bucket)
    add_args(args, "--start-ms", payload.start_ms)
    add_args(args, "--end-ms", payload.end_ms)
    add_args(args, "--interval", payload.interval)
    add_args(args, "--limit", payload.limit)
    add_args(args, "--sleep", payload.sleep)
    add_args(args, "--max-retries", payload.max_retries)
    add_args(args, "--output-dir", payload.output_dir)
    add_args(args, "--manifest-label", payload.manifest_label)
    return args


def build_run_args(payload: RunStartRequest) -> list[str]:
    args = [PYTHON_CMD, BACKTEST_SCRIPT, "run"]
    add_args(args, "--db", payload.db)
    if payload.symbols:
        args.append("--symbols")
        args.extend(payload.symbols)
    if payload.bucket:
        add_args(args, "--bucket", payload.bucket)
    add_args(args, "--output-dir", payload.output_dir)
    add_args(args, "--signal-source", payload.signal_source)
    add_args(args, "--wma-period", payload.wma_period)
    add_args(args, "--wma-offset", payload.wma_offset)
    add_args(args, "--regime-btc-symbol", payload.regime_btc_symbol)
    add_args(args, "--regime-source", payload.regime_source)
    add_args(args, "--regime-wma-period", payload.regime_wma_period)
    add_args(args, "--regime-wma-offset", payload.regime_wma_offset)
    add_args(args, "--hard-stop-pct", payload.hard_stop_pct)
    add_args(args, "--trail-activation-pct", payload.trail_activation_pct)
    add_args(args, "--trail-callback-pct", payload.trail_callback_pct)
    add_multi(args, "--partial-levels", payload.partial_levels)
    add_multi(args, "--partial-sizes", payload.partial_sizes)
    add_args(args, "--time-exit-hours", payload.time_exit_hours)
    add_args(args, "--atr-period", payload.atr_period)
    add_args(args, "--atr-cutoff-pct", payload.atr_cutoff_pct)
    add_args(args, "--atr-size-scalar", payload.atr_size_scalar)
    add_args(args, "--major-leverage", payload.major_leverage)
    add_args(args, "--large-alt-leverage", payload.large_alt_leverage)
    add_args(args, "--mid-cap-leverage", payload.mid_cap_leverage)
    add_args(args, "--default-leverage", payload.default_leverage)
    return args


def build_sweep_args(payload: SweepStartRequest) -> list[str]:
    args = [PYTHON_CMD, SWEEP_SCRIPT]
    add_args(args, "--db", payload.db)
    add_args(args, "--output-dir", payload.output_dir)
    add_args(args, "--bucket", payload.bucket)
    add_multi(args, "--wma-periods", payload.wma_periods)
    add_multi(args, "--hard-stop-pcts", payload.hard_stop_pcts)
    add_multi(args, "--trail-activation-pcts", payload.trail_activation_pcts)
    add_multi(args, "--trail-callback-pcts", payload.trail_callback_pcts)
    add_multi(args, "--atr-cutoff-pcts", payload.atr_cutoff_pcts)
    return args


def compute_permutations(payload: SweepStartRequest) -> int:
    lens = [
        len(payload.wma_periods),
        len(payload.hard_stop_pcts),
        len(payload.trail_activation_pcts),
        len(payload.trail_callback_pcts),
        len(payload.atr_cutoff_pcts),
    ]
    total = 1
    for ln in lens:
        total *= max(ln, 0)
    return total


def read_json_file(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            json.dump(payload, tmp, indent=2, ensure_ascii=False)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def load_or_create_recipes() -> dict[str, Any]:
    if not RECIPES_PATH.exists():
        atomic_write_json(RECIPES_PATH, {})
        return {}
    data = read_json_file(RECIPES_PATH)
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="recipes.json must be an object")
    return data


async def read_process_output(run_id: str, proc: asyncio.subprocess.Process) -> None:
    if proc.stdout is None:
        return
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        decoded = line.decode("utf-8", errors="replace").rstrip("\r\n")
        logs = process_logs.setdefault(run_id, [])
        logs.append(decoded)
        if len(logs) > MAX_LOG_LINES:
            del logs[: len(logs) - MAX_LOG_LINES]


async def wait_process_done(run_id: str, proc: asyncio.subprocess.Process) -> None:
    code = await proc.wait()
    meta = run_meta.get(run_id)
    if meta is not None:
        meta["exit_code"] = code
        meta["status"] = "completed" if code == 0 else "failed"
        if meta.get("cancelled"):
            meta["status"] = "cancelled"
        meta["ended_at"] = now_iso()
    active_processes.pop(run_id, None)


async def start_process(kind: str, args: list[str], output_dir: str) -> dict[str, Any]:
    run_id = uuid.uuid4().hex
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    active_processes[run_id] = proc
    process_logs[run_id] = []
    run_meta[run_id] = {
        "run_id": run_id,
        "kind": kind,
        "status": "running",
        "exit_code": None,
        "output_dir": output_dir,
        "started_at": now_iso(),
        "ended_at": None,
        "cancelled": False,
        "args": args,
    }
    reader_task = asyncio.create_task(read_process_output(run_id, proc))
    wait_task = asyncio.create_task(wait_process_done(run_id, proc))
    run_tasks[run_id] = {"reader": reader_task, "waiter": wait_task}
    return {"run_id": run_id, "status": "started"}


@app.get("/")
def studio_home() -> FileResponse:
    if STUDIO_HTML.exists():
        return FileResponse(STUDIO_HTML)
    raise HTTPException(status_code=404, detail="studio.html not found")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "ts": now_iso()}


@app.get("/api/buckets")
def buckets() -> dict[str, Any]:
    path = Path(LEVERAGE_FILE)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Leverage file not found: {LEVERAGE_FILE}")
    data = read_json_file(path)
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="leverage file must be a JSON object")
    return {
        "major": data.get("major", []),
        "large_alt": data.get("large_alt", []),
        "mid_cap": data.get("mid_cap", []),
    }


@app.get("/api/recent-runs")
def recent_runs() -> list[dict[str, Any]]:
    if not RESULTS_DIR.exists():
        return []
    rows: list[dict[str, Any]] = []
    for sub in RESULTS_DIR.iterdir():
        if not sub.is_dir():
            continue
        summary_path = sub / "results_summary.json"
        if not summary_path.exists():
            continue
        run_config_path = sub / "run_config.json"
        summary = read_json_file(summary_path)
        run_config: dict[str, Any] = {}
        if run_config_path.exists():
            cfg_data = read_json_file(run_config_path)
            if isinstance(cfg_data, dict):
                run_config = cfg_data
        run_date = datetime.fromtimestamp(sub.stat().st_mtime, tz=timezone.utc).isoformat()
        symbol_count = len(summary) if isinstance(summary, list) else 1
        total_pnl = 0.0
        if isinstance(summary, list):
            total_pnl = float(sum(float(x.get("total_pnl", 0.0)) for x in summary if isinstance(x, dict)))
        elif isinstance(summary, dict):
            total_pnl = float(summary.get("total_pnl", 0.0))
        rows.append(
            {
                "dir_name": sub.name,
                "dir_path": str(sub.resolve()),
                "run_date": run_date,
                "symbol_count": symbol_count,
                "total_pnl": total_pnl,
                "run_config": run_config,
            }
        )
    rows.sort(key=lambda x: x["run_date"], reverse=True)
    return rows[:20]


@app.post("/api/backfill/start")
async def backfill_start(payload: BackfillStartRequest) -> dict[str, Any]:
    enforce_slot("backtest")
    args = build_backfill_args(payload)
    return await start_process("backtest", args, payload.output_dir)


@app.post("/api/run/start")
async def run_start(payload: RunStartRequest) -> dict[str, Any]:
    enforce_slot("backtest")
    args = build_run_args(payload)
    return await start_process("backtest", args, payload.output_dir)


@app.post("/api/sweep/start")
async def sweep_start(payload: SweepStartRequest) -> dict[str, Any]:
    enforce_slot("sweep")
    combos = compute_permutations(payload)
    if combos > 500:
        raise HTTPException(status_code=422, detail="Too many permutations; reduce ranges.")
    args = build_sweep_args(payload)
    return await start_process("sweep", args, payload.output_dir)


@app.get("/api/run/{run_id}/status")
def run_status(run_id: str) -> dict[str, Any]:
    meta = run_meta.get(run_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="run not found")
    proc = active_processes.get(run_id)
    active = bool(proc and proc.returncode is None)
    return {
        "run_id": run_id,
        "active": active,
        "exit_code": meta.get("exit_code"),
        "line_count": len(process_logs.get(run_id, [])),
    }


@app.post("/api/run/{run_id}/cancel")
async def run_cancel(run_id: str) -> dict[str, Any]:
    proc = active_processes.get(run_id)
    if proc and proc.returncode is None:
        meta = run_meta.get(run_id)
        if meta is not None:
            meta["cancelled"] = True
        proc.terminate()
    return {"ok": True}


@app.get("/api/stream/{run_id}")
async def stream(run_id: str, request: Request) -> StreamingResponse:
    async def event_stream() -> Any:
        if run_id not in run_meta and run_id not in process_logs:
            yield f"data: {json.dumps({'type': 'error', 'message': 'run not found'})}\n\n"
            return

        sent = 0
        last_ping = time.monotonic()
        done_sent = False

        while True:
            if await request.is_disconnected():
                break

            logs = process_logs.get(run_id, [])
            while sent < len(logs):
                payload = {"type": "log", "line": logs[sent]}
                sent += 1
                yield f"data: {json.dumps(payload)}\n\n"

            meta = run_meta.get(run_id)
            proc = active_processes.get(run_id)
            active = bool(proc and proc.returncode is None)
            if meta and (not active) and (not done_sent):
                done_sent = True
                done_payload = {
                    "type": "done",
                    "exit_code": int(meta.get("exit_code") if meta.get("exit_code") is not None else -1),
                    "output_dir": str(meta.get("output_dir", "")),
                }
                yield f"data: {json.dumps(done_payload)}\n\n"
                break

            now = time.monotonic()
            if now - last_ping >= PING_SECONDS:
                yield ": ping\n\n"
                last_ping = now

            await asyncio.sleep(0.25)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/results")
def results(dir: str = Query(..., description="Absolute path or relative path under RESULTS_BASE_DIR")) -> dict[str, Any]:
    target = resolve_dir(dir)
    summary_path = target / "results_summary.json"
    if not summary_path.exists():
        raise HTTPException(status_code=404, detail="results_summary.json not found")

    def read_or_default(name: str, default: Any) -> Any:
        path = target / name
        return read_json_file(path) if path.exists() else default

    return {
        "summary": read_or_default("results_summary.json", []),
        "equity_curve": read_or_default("equity_curve.json", []),
        "trades": read_or_default("trades.json", []),
        "season_breakdown": read_or_default("season_breakdown.json", {}),
        "side_breakdown": read_or_default("side_breakdown.json", {}),
        "exclude_list": read_or_default("exclude_list.json", []),
        "run_config": read_or_default("run_config.json", {}),
    }


@app.get("/api/sweep-results")
def sweep_results(dir: str = Query(..., description="Absolute path or relative path under RESULTS_BASE_DIR")) -> dict[str, Any]:
    target = resolve_dir(dir)
    sweep_path = target / "sweep_results.json"
    best_path = target / "best_per_symbol.json"
    if not sweep_path.exists() or not best_path.exists():
        raise HTTPException(status_code=404, detail="sweep result files not found")
    return {
        "sweep_results": read_json_file(sweep_path),
        "best_per_symbol": read_json_file(best_path),
    }


@app.get("/api/recipes")
def recipes_get() -> dict[str, Any]:
    return {"recipes": load_or_create_recipes()}


@app.post("/api/recipes")
def recipes_upsert(payload: RecipeUpsertRequest) -> dict[str, Any]:
    key = payload.name.strip()
    if not key:
        raise HTTPException(status_code=422, detail="name is required")
    recipes = load_or_create_recipes()
    recipes[key] = payload.config
    atomic_write_json(RECIPES_PATH, recipes)
    return {"ok": True}


@app.delete("/api/recipes/{name}")
def recipes_delete(name: str) -> dict[str, Any]:
    key = name.strip()
    recipes = load_or_create_recipes()
    recipes.pop(key, None)
    atomic_write_json(RECIPES_PATH, recipes)
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backtest_studio.api:app", host="0.0.0.0", port=STUDIO_PORT)
