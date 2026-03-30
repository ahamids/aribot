#!/usr/bin/env python3
"""One-time Telegram command menu registration for Aribot.

Usage:
    python deploy/register_telegram_commands.py

Optional:
    python deploy/register_telegram_commands.py --scope all_private_chats --language-code en
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import requests

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional import fallback
    load_dotenv = None


DEFAULT_COMMANDS = [
    {"command": "status", "description": "Mode, regime, pnl, cycle, drawdown, cooldown"},
    {"command": "positions", "description": "Open positions snapshot"},
    {"command": "pnl", "description": "Today realized and cumulative pnl"},
    {"command": "trades", "description": "Today trades or last n: /trades 5"},
    {"command": "pause", "description": "Pause new entries"},
    {"command": "resume", "description": "Resume new entries"},
    {"command": "close", "description": "Close SYMBOL or all; needs YES confirm"},
    {"command": "kill", "description": "Emergency kill; needs YES confirm"},
    {"command": "config", "description": "Read-only runtime config"},
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Register Telegram command menu for Aribot")
    parser.add_argument(
        "--scope",
        default="all_private_chats",
        choices=[
            "default",
            "all_private_chats",
            "all_group_chats",
            "all_chat_administrators",
        ],
        help="Telegram command scope (default: all_private_chats)",
    )
    parser.add_argument(
        "--language-code",
        default="",
        help="Optional IETF language code, for example en",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print payload only; do not call Telegram API",
    )
    return parser.parse_args()


def load_environment() -> None:
    if load_dotenv is not None:
        load_dotenv(override=False)


def build_scope(scope: str) -> dict[str, str]:
    if scope == "default":
        return {"type": "default"}
    return {"type": scope}


def get_bot_token() -> str:
    return str(os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()


def call_telegram(bot_token: str, method: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"https://api.telegram.org/bot{bot_token}/{method}"
    response = requests.post(url, json=payload, timeout=15)
    response.raise_for_status()
    return response.json()


def main() -> int:
    args = parse_args()
    load_environment()

    payload: dict[str, Any] = {
        "commands": DEFAULT_COMMANDS,
        "scope": build_scope(args.scope),
    }
    language_code = str(args.language_code or "").strip()
    if language_code:
        payload["language_code"] = language_code

    if args.dry_run:
        print("DRY RUN payload:")
        print(json.dumps(payload, indent=2))
        return 0

    bot_token = get_bot_token()
    if not bot_token:
        print("ERROR: TELEGRAM_BOT_TOKEN is missing. Set it in environment or .env.")
        return 1

    try:
        result = call_telegram(bot_token, "setMyCommands", payload)
    except requests.RequestException as exc:
        print(f"ERROR: setMyCommands request failed: {exc}")
        return 1

    if not result.get("ok"):
        print(f"ERROR: setMyCommands returned non-ok payload: {result}")
        return 1

    try:
        verify = call_telegram(
            bot_token,
            "getMyCommands",
            {
                "scope": payload["scope"],
                **({"language_code": language_code} if language_code else {}),
            },
        )
    except requests.RequestException as exc:
        print(f"WARNING: setMyCommands succeeded but getMyCommands verification failed: {exc}")
        return 0

    if verify.get("ok"):
        count = len(verify.get("result") or [])
        print(f"SUCCESS: Registered Telegram commands (count={count}) for scope={args.scope}")
        return 0

    print(f"WARNING: setMyCommands succeeded but getMyCommands returned non-ok: {verify}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
