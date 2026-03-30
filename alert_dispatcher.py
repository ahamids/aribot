#!/usr/bin/env python3
"""Telegram alert dispatcher for trading bot runtime events."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

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

    def get_updates(
        self,
        offset: Optional[int] = None,
        timeout_seconds: int = 0,
        limit: int = 25,
    ) -> Dict[str, Any]:
        """Fetch inbound Telegram updates without raising transport exceptions."""
        if not self.enabled:
            return {
                'ok': False,
                'updates': [],
                'next_offset': offset,
                'error': 'telegram_not_configured',
            }

        url = f'https://api.telegram.org/bot{self.bot_token}/getUpdates'
        params: Dict[str, Any] = {
            'timeout': max(0, int(timeout_seconds)),
            'limit': max(1, min(int(limit), 100)),
        }
        if offset is not None:
            params['offset'] = int(offset)

        try:
            # Keep timeout bounded and deterministic for loop-level polling.
            request_timeout = max(self.timeout, params['timeout'] + 2)
            response = requests.get(url, params=params, timeout=request_timeout)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            self.logger.warning('Telegram update polling failed: %s', exc)
            return {
                'ok': False,
                'updates': [],
                'next_offset': offset,
                'error': str(exc),
            }
        except ValueError as exc:
            self.logger.warning('Telegram update polling returned invalid JSON: %s', exc)
            return {
                'ok': False,
                'updates': [],
                'next_offset': offset,
                'error': 'invalid_json',
            }

        if not data.get('ok'):
            self.logger.warning('Telegram getUpdates returned non-ok response: %s', data)
            return {
                'ok': False,
                'updates': [],
                'next_offset': offset,
                'error': 'telegram_api_non_ok',
            }

        updates = data.get('result')
        if not isinstance(updates, list):
            self.logger.warning('Telegram getUpdates payload missing list result: %s', data)
            return {
                'ok': False,
                'updates': [],
                'next_offset': offset,
                'error': 'invalid_result_shape',
            }

        next_offset = offset
        for item in updates:
            if not isinstance(item, dict):
                continue
            update_id = item.get('update_id')
            try:
                update_id_int = int(update_id)
            except (TypeError, ValueError):
                continue
            candidate = update_id_int + 1
            if next_offset is None or candidate > next_offset:
                next_offset = candidate

        return {
            'ok': True,
            'updates': updates,
            'next_offset': next_offset,
            'error': None,
        }

    @staticmethod
    def extract_text_updates(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract text-bearing message updates with normalized fields."""
        if not isinstance(payload, dict):
            return []

        updates = payload.get('updates') if 'updates' in payload else payload.get('result')
        if not isinstance(updates, list):
            return []

        extracted: List[Dict[str, Any]] = []
        for raw_update in updates:
            if not isinstance(raw_update, dict):
                continue

            try:
                update_id = int(raw_update.get('update_id'))
            except (TypeError, ValueError):
                continue

            message = raw_update.get('message') or raw_update.get('edited_message')
            if not isinstance(message, dict):
                continue

            chat = message.get('chat')
            if not isinstance(chat, dict):
                continue

            text = message.get('text')
            if not isinstance(text, str):
                continue

            extracted.append(
                {
                    'update_id': update_id,
                    'chat_id': str(chat.get('id', '')).strip(),
                    'text': text.strip(),
                }
            )

        extracted.sort(key=lambda item: item['update_id'])
        return extracted

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