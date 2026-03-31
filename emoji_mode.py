#!/usr/bin/env python3
"""Helpers for bot emoji output modes."""

from __future__ import annotations

import argparse
import logging
import re
from typing import Iterable, List, Optional, Tuple


# Covers common emoji and pictograph blocks used in bot log messages.
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F000-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "]+",
    flags=re.UNICODE,
)
_EMOJI_JOINERS_PATTERN = re.compile(r"[\u200d\ufe0f]")


def normalize_emoji_mode(mode: Optional[str]) -> str:
    """Normalize the mode value to either 'emojis' or 'noemojis'."""
    normalized = str(mode or "").strip().lower()
    if normalized == "emojis":
        return "emojis"
    return "noemojis"


def strip_emojis(text: object) -> str:
    """Return text with emoji code points removed."""
    value = str(text)
    value = _EMOJI_PATTERN.sub("", value)
    value = _EMOJI_JOINERS_PATTERN.sub("", value)
    return value


def parse_emoji_mode_args(argv: Optional[Iterable[str]] = None) -> Tuple[str, List[str]]:
    """Parse emoji mode flags and return (mode, remaining_args)."""
    parser = argparse.ArgumentParser(add_help=False)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--emojis",
        action="store_true",
        help="Enable emoji output in screen and text logs.",
    )
    group.add_argument(
        "--noemojis",
        action="store_true",
        help="Disable emoji output in screen and text logs (default).",
    )
    parsed, remaining = parser.parse_known_args(list(argv or []))
    mode = "emojis" if parsed.emojis else "noemojis"
    return mode, remaining


class EmojiLogFilter(logging.Filter):
    """Strip emojis from rendered logging records when noemojis mode is active."""

    def __init__(self, emoji_mode: str = "noemojis") -> None:
        super().__init__()
        self.emoji_mode = normalize_emoji_mode(emoji_mode)

    def filter(self, record: logging.LogRecord) -> bool:
        if self.emoji_mode == "emojis":
            return True

        rendered = record.getMessage()
        record.msg = strip_emojis(rendered)
        record.args = ()
        return True
