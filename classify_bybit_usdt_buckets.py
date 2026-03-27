#!/usr/bin/env python3
"""
Classify all Bybit USDT swap symbols into leverage buckets using anchor symbols
from leverage_buckets.json as calibration yardsticks.

Usage example:
    python classify_bybit_usdt_buckets.py \
        --config leverage_buckets.json \
        --out leverage_buckets_suggested.json \
        --report bucket_classification_report.json
"""

import argparse
import datetime as dt
import json
import math
import statistics
from pathlib import Path

import ccxt


BUCKET_KEYS = ("major", "large_alt", "mid_cap")
DEFAULT_SMALL_CAP_BUCKET = "default_small_cap"


def load_bucket_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    for key in BUCKET_KEYS:
        if key not in data:
            raise ValueError(f"Missing required bucket in config: {key}")
        if "symbols" not in data[key] or not isinstance(data[key]["symbols"], list):
            raise ValueError(f"Bucket {key} must contain a symbols list")
        if "leverage" not in data[key]:
            raise ValueError(f"Bucket {key} must contain leverage")

    if "default_leverage" not in data:
        raise ValueError("Missing default_leverage in config")

    return data


def safe_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def pct_rank(sorted_values, value):
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return 1.0

    idx = 0
    while idx < len(sorted_values) and sorted_values[idx] <= value:
        idx += 1
    return (idx - 1) / (len(sorted_values) - 1)


def median_or_raise(values, label):
    vals = [v for v in values if v is not None]
    if not vals:
        raise ValueError(f"No values available for {label}")
    return statistics.median(vals)


def euclidean_distance(v1, v2):
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(v1, v2)))


def extract_turnover_usd(ticker):
    quote_volume = safe_float(ticker.get("quoteVolume"))
    if quote_volume is not None and quote_volume > 0:
        return quote_volume

    info = ticker.get("info") or {}
    for key in ("turnover24h", "quoteVolume", "volume24h"):
        value = safe_float(info.get(key))
        if value is not None and value > 0:
            return value

    base_volume = safe_float(ticker.get("baseVolume"))
    last_price = safe_float(ticker.get("last"))
    if base_volume is not None and last_price is not None and base_volume > 0 and last_price > 0:
        return base_volume * last_price

    return None


def extract_open_interest_usd(ticker):
    info = ticker.get("info") or {}

    for key in ("openInterestValue", "open_interest_value"):
        value = safe_float(info.get(key))
        if value is not None and value > 0:
            return value

    oi = None
    for key in ("openInterest", "open_interest"):
        oi = safe_float(info.get(key))
        if oi is not None and oi > 0:
            break

    if oi is None:
        return None

    mark = safe_float(ticker.get("mark"))
    last = safe_float(ticker.get("last"))
    px = mark if mark is not None and mark > 0 else last
    if px is None:
        return None

    return oi * px


def normalize_base_asset(code: str) -> str:
    return (code or "").upper().strip()


def fetch_usdt_swap_markets(exchange):
    markets = exchange.load_markets()
    usdt_swaps = []

    for symbol, market in markets.items():
        if market.get("type") != "swap":
            continue
        if market.get("quote") != "USDT":
            continue
        if market.get("active") is False:
            continue

        usdt_swaps.append(
            {
                "symbol": symbol,
                "base": normalize_base_asset(market.get("base")),
            }
        )

    return usdt_swaps


def build_records(exchange, usdt_swaps):
    symbols = [m["symbol"] for m in usdt_swaps]
    tickers = exchange.fetch_tickers(symbols)

    records = []
    for market in usdt_swaps:
        symbol = market["symbol"]
        base = market["base"]
        ticker = tickers.get(symbol) or {}

        turnover_usd = extract_turnover_usd(ticker)
        oi_usd = extract_open_interest_usd(ticker)
        if turnover_usd is None:
            turnover_usd = 0.0
        if oi_usd is None:
            oi_usd = 0.0

        records.append(
            {
                "symbol": symbol,
                "base": base,
                "turnover_usd": turnover_usd,
                "open_interest_usd": oi_usd,
                "last": safe_float(ticker.get("last")) or 0.0,
            }
        )

    # If a base has multiple contracts, keep the strongest one by turnover.
    deduped = {}
    for rec in records:
        base = rec["base"]
        if not base:
            continue
        prev = deduped.get(base)
        if prev is None or rec["turnover_usd"] > prev["turnover_usd"]:
            deduped[base] = rec

    return list(deduped.values())


def compute_percentile_features(records):
    turnover_logs = [math.log1p(max(r["turnover_usd"], 0.0)) for r in records]
    oi_logs = [math.log1p(max(r["open_interest_usd"], 0.0)) for r in records]

    sorted_turnover = sorted(turnover_logs)
    sorted_oi = sorted(oi_logs)

    for rec in records:
        t_log = math.log1p(max(rec["turnover_usd"], 0.0))
        oi_log = math.log1p(max(rec["open_interest_usd"], 0.0))

        rec["turnover_pct"] = pct_rank(sorted_turnover, t_log)
        rec["oi_pct"] = pct_rank(sorted_oi, oi_log)
        rec["liq_score"] = 0.65 * rec["turnover_pct"] + 0.35 * rec["oi_pct"]


def get_anchor_sets(config):
    out = {}
    for key in BUCKET_KEYS:
        out[key] = {normalize_base_asset(s) for s in config[key]["symbols"] if str(s).strip()}
    return out


def compute_bucket_profiles(records_by_base, anchor_sets):
    profiles = {}
    for bucket, anchors in anchor_sets.items():
        rows = [records_by_base[b] for b in anchors if b in records_by_base]
        if not rows:
            raise ValueError(
                f"No live Bybit USDT swap records found for anchor symbols in bucket: {bucket}"
            )

        centroid = (
            median_or_raise([r["turnover_pct"] for r in rows], f"{bucket}.turnover_pct"),
            median_or_raise([r["oi_pct"] for r in rows], f"{bucket}.oi_pct"),
        )
        liq_values = [r["liq_score"] for r in rows]
        anchor_distances = [
            euclidean_distance((r["turnover_pct"], r["oi_pct"]), centroid)
            for r in rows
        ]

        profiles[bucket] = {
            "centroid": centroid,
            "liq_p25": statistics.quantiles(liq_values, n=4)[0]
            if len(rows) >= 2
            else liq_values[0],
            "liq_median": statistics.median(liq_values),
            "dist_p75": statistics.quantiles(anchor_distances, n=4)[2]
            if len(anchor_distances) >= 2
            else anchor_distances[0],
            "anchors_present": sorted(r["base"] for r in rows),
        }

    # Tight mid-cap gate: must be at or above anchor median liquidity and reasonably
    # close to the mid-cap anchor centroid, else it falls to default leverage tier.
    profiles["mid_cap"]["liq_strict_floor"] = profiles["mid_cap"]["liq_median"]
    profiles["mid_cap"]["dist_strict_radius"] = max(0.08, profiles["mid_cap"]["dist_p75"] * 1.25)

    return profiles


def classify_records(records, anchor_sets, profiles):
    records_by_base = {r["base"]: r for r in records}

    for rec in records:
        base = rec["base"]

        # Keep configured anchor symbols pinned to their configured bucket.
        pinned = None
        for bucket, anchors in anchor_sets.items():
            if base in anchors:
                pinned = bucket
                break

        if pinned:
            assigned = pinned
            distances = {
                b: euclidean_distance((rec["turnover_pct"], rec["oi_pct"]), profiles[b]["centroid"])
                for b in BUCKET_KEYS
            }
        else:
            distances = {
                b: euclidean_distance((rec["turnover_pct"], rec["oi_pct"]), profiles[b]["centroid"])
                for b in BUCKET_KEYS
            }
            assigned = min(distances, key=distances.get)

            # Guardrails based on anchor liquidity floors.
            if assigned == "major" and rec["liq_score"] < profiles["major"]["liq_p25"]:
                assigned = "large_alt"
            if assigned == "large_alt" and rec["liq_score"] < profiles["large_alt"]["liq_p25"]:
                assigned = "mid_cap"

            # Tight mid-cap admission; otherwise leave unbucketed so default leverage applies.
            if assigned == "mid_cap":
                if (
                    rec["liq_score"] < profiles["mid_cap"]["liq_strict_floor"]
                    or distances["mid_cap"] > profiles["mid_cap"]["dist_strict_radius"]
                ):
                    assigned = DEFAULT_SMALL_CAP_BUCKET

        ordered = sorted((v, k) for k, v in distances.items())
        best, second = ordered[0][0], ordered[1][0]
        margin = second - best

        confidence = "low"
        if margin >= 0.20:
            confidence = "high"
        elif margin >= 0.08:
            confidence = "medium"

        rec["assigned_bucket"] = assigned
        rec["distance_major"] = distances["major"]
        rec["distance_large_alt"] = distances["large_alt"]
        rec["distance_mid_cap"] = distances["mid_cap"]
        rec["distance_margin"] = margin
        rec["confidence"] = confidence

    # Stable ordering by liquidity, then base code.
    records.sort(key=lambda r: (-r["liq_score"], r["base"]))
    return records


def build_suggested_bucket_json(config, records):
    bucket_to_symbols = {key: [] for key in BUCKET_KEYS}
    for rec in records:
        assigned = rec["assigned_bucket"]
        if assigned in bucket_to_symbols:
            bucket_to_symbols[assigned].append(rec["base"])

    for key in BUCKET_KEYS:
        bucket_to_symbols[key] = sorted(set(bucket_to_symbols[key]))

    return {
        "major": {
            "leverage": config["major"]["leverage"],
            "symbols": bucket_to_symbols["major"],
        },
        "large_alt": {
            "leverage": config["large_alt"]["leverage"],
            "symbols": bucket_to_symbols["large_alt"],
        },
        "mid_cap": {
            "leverage": config["mid_cap"]["leverage"],
            "symbols": bucket_to_symbols["mid_cap"],
        },
        "default_leverage": config["default_leverage"],
    }


def build_report(records, profiles, config_path):
    ts = dt.datetime.now(dt.timezone.utc).isoformat()
    rows = []
    for rec in records:
        rows.append(
            {
                "base": rec["base"],
                "source_symbol": rec["symbol"],
                "assigned_bucket": rec["assigned_bucket"],
                "confidence": rec["confidence"],
                "turnover_usd": rec["turnover_usd"],
                "open_interest_usd": rec["open_interest_usd"],
                "turnover_pct": round(rec["turnover_pct"], 6),
                "oi_pct": round(rec["oi_pct"], 6),
                "liq_score": round(rec["liq_score"], 6),
                "distance_margin": round(rec["distance_margin"], 6),
                "distance_major": round(rec["distance_major"], 6),
                "distance_large_alt": round(rec["distance_large_alt"], 6),
                "distance_mid_cap": round(rec["distance_mid_cap"], 6),
            }
        )

    return {
        "generated_at_utc": ts,
        "config_path": str(config_path),
        "method": {
            "feature_weights": {"turnover_pct": 0.65, "oi_pct": 0.35},
            "distance_metric": "euclidean_on_percentile_space",
            "anchor_buckets": list(BUCKET_KEYS),
            "guards": [
                "anchor symbols are pinned to their configured bucket",
                "major/large_alt assignments are floored by bucket anchor liq_score p25",
                "mid_cap requires both liq_score >= anchor median and centroid-distance <= strict radius",
                "symbols failing strict mid_cap gate are assigned to default_small_cap (default leverage)",
            ],
        },
        "profiles": {
            k: {
                "centroid_turnover_pct": round(v["centroid"][0], 6),
                "centroid_oi_pct": round(v["centroid"][1], 6),
                "liq_floor_p25": round(v["liq_p25"], 6),
                "liq_median": round(v["liq_median"], 6),
                "dist_p75": round(v["dist_p75"], 6),
                "liq_strict_floor": round(v.get("liq_strict_floor", v["liq_median"]), 6),
                "dist_strict_radius": round(v.get("dist_strict_radius", v["dist_p75"]), 6),
                "anchors_present": v["anchors_present"],
            }
            for k, v in profiles.items()
        },
        "records": rows,
    }


def parse_args():
    parser = argparse.ArgumentParser(
        description="Classify Bybit USDT swap base assets into major/large_alt/mid_cap buckets"
    )
    parser.add_argument("--config", default="leverage_buckets.json", help="Path to leverage bucket config")
    parser.add_argument(
        "--out",
        default="leverage_buckets_suggested.json",
        help="Output path for suggested bucket config",
    )
    parser.add_argument(
        "--report",
        default="bucket_classification_report.json",
        help="Output path for detailed classification report",
    )
    parser.add_argument(
        "--print-top",
        type=int,
        default=20,
        help="How many top-liquidity symbols to print to stdout",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    config_path = Path(args.config)
    out_path = Path(args.out)
    report_path = Path(args.report)

    config = load_bucket_config(config_path)

    exchange = ccxt.bybit(
        {
            "enableRateLimit": True,
            "options": {
                "defaultType": "swap",
            },
        }
    )

    usdt_swaps = fetch_usdt_swap_markets(exchange)
    if not usdt_swaps:
        raise RuntimeError("No active Bybit USDT swap markets found")

    records = build_records(exchange, usdt_swaps)
    if not records:
        raise RuntimeError("No records created from Bybit tickers")

    compute_percentile_features(records)

    records_by_base = {r["base"]: r for r in records}
    anchor_sets = get_anchor_sets(config)
    profiles = compute_bucket_profiles(records_by_base, anchor_sets)

    classified = classify_records(records, anchor_sets, profiles)
    suggested = build_suggested_bucket_json(config, classified)
    report = build_report(classified, profiles, config_path)

    with out_path.open("w", encoding="utf-8") as f:
        json.dump(suggested, f, indent=2)

    with report_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"Universe size (deduped bases): {len(classified)}")
    default_small_count = sum(1 for r in classified if r["assigned_bucket"] == DEFAULT_SMALL_CAP_BUCKET)
    print(
        "Assigned counts: "
        f"major={len(suggested['major']['symbols'])}, "
        f"large_alt={len(suggested['large_alt']['symbols'])}, "
        f"mid_cap={len(suggested['mid_cap']['symbols'])}, "
        f"default_small_cap={default_small_count}"
    )
    print(f"Suggested config written to: {out_path}")
    print(f"Detailed report written to: {report_path}")

    n = max(0, args.print_top)
    if n > 0:
        print("\\nTop symbols by liquidity score:")
        for rec in classified[:n]:
            print(
                f"{rec['base']:>12}  {rec['assigned_bucket']:<10} "
                f"score={rec['liq_score']:.4f} conf={rec['confidence']} "
                f"sym={rec['symbol']}"
            )


if __name__ == "__main__":
    main()
