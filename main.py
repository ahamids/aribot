#!/usr/bin/env python3
"""Thin entrypoint for Aribot runtime bootstrap and execution."""

from __future__ import annotations

import argparse
import sys

from aribot.runtime.bootstrap import Bootstrap
from aribot.runtime.runner import Runner
from secret_loader import SecretValidationError


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Aribot")
    parser.add_argument("--profile", default="usdt", help="Config profile under config/profiles/*.yaml")
    parser.add_argument("--mode", choices=["paper", "shadow", "live"], help="Runtime mode override")
    parser.add_argument("--db", help="SQLite DB path override")
    parser.add_argument("--emojis", action="store_true", help="Enable emoji output")
    parser.add_argument("--noemojis", action="store_true", help="Disable emoji output")
    parser.add_argument("--no-migrate", action="store_true", help="Skip startup DB migrations")
    return parser.parse_args(argv)


def resolve_emoji_mode(args: argparse.Namespace) -> str:
    if args.emojis and args.noemojis:
        raise SystemExit("Cannot pass both --emojis and --noemojis")
    if args.emojis:
        return "emojis"
    return "noemojis"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    bootstrap = Bootstrap.from_args(
        profile=args.profile,
        mode=args.mode,
        db_path=args.db,
        emoji_mode=resolve_emoji_mode(args),
        run_migrations=not args.no_migrate,
    )
    try:
        ctx = bootstrap.build()
    except SecretValidationError as exc:
        message = str(exc)
        print(f"Startup validation failed: {message}", file=sys.stderr)
        if "Kill switch file detected at startup" in message:
            print(
                "Action: remove/rename kill_switch.flag when you intentionally want trading enabled.",
                file=sys.stderr,
            )
        return 2

    return Runner(ctx.bot).run()


if __name__ == "__main__":
    raise SystemExit(main())
