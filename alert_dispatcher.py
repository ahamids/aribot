#!/usr/bin/env python3
"""Telegram alert dispatcher for trading bot runtime events."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import requests


class AlertDispatcher:
    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
        timeout: int = 10,
    ) -> None:
        self.bot_token = (bot_token or os.getenv('TELEGRAM_BOT_TOKEN', '')).strip()
        self.chat_id = (chat_id or os.getenv('TELEGRAM_CHAT_ID', '')).strip()
        self.logger = logger or logging.getLogger(__name__)
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send_message(self, text: str) -> bool:
        if not self.enabled:
            return False

        url = f'https://api.telegram.org/bot{self.bot_token}/sendMessage'
        payload = {
            'chat_id': self.chat_id,
            'text': text,
            'parse_mode': 'HTML',
            'disable_web_page_preview': True,
        }

        try:
            response = requests.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            if not data.get('ok'):
                self.logger.warning('Telegram API returned non-ok response: %s', data)
                return False
            return True
        except requests.RequestException as exc:
            self.logger.warning('Telegram alert dispatch failed: %s', exc)
            return False

    def verify_delivery(self, probe_text: str) -> bool:
        """Run an end-to-end Telegram verification: bot auth + message delivery."""
        if not self.enabled:
            self.logger.warning('Telegram verification skipped: TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not configured')
            return False

        me_url = f'https://api.telegram.org/bot{self.bot_token}/getMe'
        try:
            me_response = requests.get(me_url, timeout=self.timeout)
            me_response.raise_for_status()
            me_payload = me_response.json()
            if not me_payload.get('ok'):
                self.logger.warning('Telegram getMe verification failed: %s', me_payload)
                return False
        except requests.RequestException as exc:
            self.logger.warning('Telegram getMe call failed during verification: %s', exc)
            return False

        return self.send_message(probe_text)

    def dispatch_event(
        self,
        level: str,
        event_type: str,
        message: str,
        symbol: Optional[str] = None,
        values: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if not self.should_alert(level, event_type):
            return False

        values = values or {}
        headline = f'<b>[{level.upper()}] {event_type}</b>'
        lines = [headline, message]
        if symbol:
            lines.append(f'Symbol: <code>{symbol}</code>')
        for key, value in values.items():
            lines.append(f'{key}: <code>{value}</code>')

        return self.send_message('\n'.join(lines))

    @staticmethod
    def should_alert(level: str, event_type: str) -> bool:
        normalized_level = str(level).upper()
        if event_type in {'position_opened', 'position_closed'}:
            return True
        if event_type in {'circuit_breaker_triggered', 'kill_switch_detected', 'kill_switch_executed', 'kill_switch_execution_error'}:
            return True
        return normalized_level == 'CRITICAL'