from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from .models import BotConfig, PluginConfig, RuntimeConfig, TradingConfig


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}

    try:
        import yaml  # type: ignore
    except ModuleNotFoundError:
        return _load_simple_yaml(path)

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _load_simple_yaml(path: Path) -> Dict[str, Any]:
    """Parse a minimal YAML subset (nested mappings + scalar values).

    This fallback keeps bootstrap functional before optional dependencies are
    installed. For advanced YAML features, install PyYAML.
    """
    root: Dict[str, Any] = {}
    stack: list[tuple[int, Dict[str, Any]]] = [(-1, root)]

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if ":" not in stripped:
            raise RuntimeError(f"Unsupported YAML line in {path}: {raw_line}")

        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        value = raw_value.strip()

        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()

        current = stack[-1][1]
        if value == "":
            child: Dict[str, Any] = {}
            current[key] = child
            stack.append((indent, child))
            continue

        current[key] = _parse_scalar(value)

    return root


def _parse_scalar(value: str) -> Any:
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"

    if value.startswith(("\"", "'")) and value.endswith(("\"", "'")):
        return value[1:-1]

    try:
        return int(value)
    except ValueError:
        pass

    try:
        return float(value)
    except ValueError:
        pass

    return value


def load_bot_config(
    *,
    profile: str,
    mode: str | None,
    emoji_mode: str,
    db_path: str | None,
    run_migrations: bool,
) -> BotConfig:
    repo_root = Path(__file__).resolve().parents[2]
    defaults = _load_yaml(repo_root / "config" / "bot.yaml")
    profile_cfg = _load_yaml(repo_root / "config" / "profiles" / f"{profile}.yaml")
    merged = _deep_merge(defaults, profile_cfg)

    runtime_raw = merged.get("runtime", {})
    trading_raw = merged.get("trading", {})
    plugins_raw = merged.get("plugins", {})

    runtime = RuntimeConfig(
        profile=profile,
        mode=(mode or runtime_raw.get("mode") or "paper").strip().lower(),
        emoji_mode=emoji_mode,
        db_path=(db_path or runtime_raw.get("db_path") or "usdt_bot_v2.db").strip(),
        run_migrations=run_migrations,
    )

    trading = TradingConfig(
        market_quote=str(trading_raw.get("market_quote", "USDT")).strip().upper(),
    )

    plugins = PluginConfig(
        exchange=str(plugins_raw.get("exchange", "bybit")).strip(),
        strategy=str(plugins_raw.get("strategy", "wma45_ohlc4")).strip(),
        regime_filter=str(plugins_raw.get("regime_filter", "wma_regime")).strip(),
        risk=str(plugins_raw.get("risk", "default_risk")).strip(),
    )

    return BotConfig(runtime=runtime, trading=trading, plugins=plugins, raw=merged)
