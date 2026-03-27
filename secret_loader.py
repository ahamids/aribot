#!/usr/bin/env python3
"""Startup secrets loading and validation for live/shadow Bybit bot modes."""

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Set


class SecretValidationError(RuntimeError):
    """Raised when environment secrets or permission checks fail."""


@dataclass(frozen=True)
class BotSecrets:
    bot_mode: str
    bybit_testnet: bool
    kill_switch_file: str
    read_api_key: str
    read_api_secret: str
    trade_api_key: str
    trade_api_secret: str


class SecretLoader:
    REQUIRED_ENV_VARS = (
        "BYBIT_READ_API_KEY",
        "BYBIT_READ_API_SECRET",
        "BYBIT_TRADE_API_KEY",
        "BYBIT_TRADE_API_SECRET",
    )

    def __init__(self, environ: Dict[str, str] | None = None):
        self.environ = dict(environ or os.environ)

    @staticmethod
    def _parse_bool(raw: str | None, default: bool = False) -> bool:
        if raw is None:
            return default
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}

    def load(self) -> BotSecrets:
        bot_mode = self.environ.get("BOT_MODE", "paper").strip().lower()
        if bot_mode not in {"paper", "shadow", "live"}:
            raise SecretValidationError(
                "BOT_MODE must be one of: paper, shadow, live"
            )

        secrets = BotSecrets(
            bot_mode=bot_mode,
            bybit_testnet=self._parse_bool(self.environ.get("BYBIT_TESTNET"), default=True),
            kill_switch_file=self.environ.get("KILL_SWITCH_FILE", "kill_switch.flag").strip() or "kill_switch.flag",
            read_api_key=self.environ.get("BYBIT_READ_API_KEY", "").strip(),
            read_api_secret=self.environ.get("BYBIT_READ_API_SECRET", "").strip(),
            trade_api_key=self.environ.get("BYBIT_TRADE_API_KEY", "").strip(),
            trade_api_secret=self.environ.get("BYBIT_TRADE_API_SECRET", "").strip(),
        )

        if secrets.bot_mode in {"shadow", "live"}:
            self._validate_presence(secrets)
            self._validate_distinct_keypairs(secrets)

        return secrets

    def config_fingerprint(self, secrets: BotSecrets) -> str:
        payload = {
            "bot_mode": secrets.bot_mode,
            "bybit_testnet": secrets.bybit_testnet,
            "kill_switch_file": secrets.kill_switch_file,
            "read_key_hash": hashlib.sha256(secrets.read_api_key.encode("utf-8")).hexdigest(),
            "trade_key_hash": hashlib.sha256(secrets.trade_api_key.encode("utf-8")).hexdigest(),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def validate_startup(self, secrets: BotSecrets) -> None:
        self._assert_kill_switch_not_triggered(secrets.kill_switch_file)
        if secrets.bot_mode not in {"shadow", "live"}:
            return

        read_perms = self._query_api_permissions(
            api_key=secrets.read_api_key,
            api_secret=secrets.read_api_secret,
            testnet=secrets.bybit_testnet,
        )
        trade_perms = self._query_api_permissions(
            api_key=secrets.trade_api_key,
            api_secret=secrets.trade_api_secret,
            testnet=secrets.bybit_testnet,
        )

        self._validate_permission_profile(read_perms, role="read")
        self._validate_permission_profile(trade_perms, role="trade")

    @staticmethod
    def is_kill_switch_triggered(kill_switch_file: str) -> bool:
        return Path(kill_switch_file).exists()

    def _validate_presence(self, secrets: BotSecrets) -> None:
        missing = [
            env_name
            for env_name in self.REQUIRED_ENV_VARS
            if not self.environ.get(env_name, "").strip()
        ]
        if missing:
            raise SecretValidationError(
                "Missing required environment variables: " + ", ".join(sorted(missing))
            )

    @staticmethod
    def _validate_distinct_keypairs(secrets: BotSecrets) -> None:
        if secrets.read_api_key == secrets.trade_api_key:
            raise SecretValidationError(
                "BYBIT_READ_API_KEY and BYBIT_TRADE_API_KEY must be different key pairs"
            )

    @staticmethod
    def _assert_kill_switch_not_triggered(kill_switch_file: str) -> None:
        if Path(kill_switch_file).exists():
            raise SecretValidationError(
                f"Kill switch file detected at startup: {kill_switch_file}. Refusing to run."
            )

    def _query_api_permissions(self, api_key: str, api_secret: str, testnet: bool) -> Dict[str, Any]:
        base_url = "https://api-testnet.bybit.com" if testnet else "https://api.bybit.com"
        endpoint = "/v5/user/query-api"
        recv_window = "5000"
        timestamp = str(int(time.time() * 1000))
        query = ""
        prehash = f"{timestamp}{api_key}{recv_window}{query}"
        signature = hmac.new(
            api_secret.encode("utf-8"),
            prehash.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        request = urllib.request.Request(
            url=f"{base_url}{endpoint}",
            method="GET",
            headers={
                "X-BAPI-API-KEY": api_key,
                "X-BAPI-TIMESTAMP": timestamp,
                "X-BAPI-RECV-WINDOW": recv_window,
                "X-BAPI-SIGN": signature,
                "X-BAPI-SIGN-TYPE": "2",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise SecretValidationError(f"Failed permission validation call to Bybit: {exc}") from exc

        if str(payload.get("retCode", "")) != "0":
            raise SecretValidationError(
                "Bybit permission validation failed: "
                f"retCode={payload.get('retCode')} retMsg={payload.get('retMsg')}"
            )

        result = payload.get("result")
        if not isinstance(result, dict):
            raise SecretValidationError("Bybit permission validation returned unexpected payload")

        return result

    def _validate_permission_profile(self, permission_result: Dict[str, Any], role: str) -> None:
        tokens = self._extract_permission_tokens(permission_result)

        has_withdraw = any("withdraw" in token for token in tokens)
        if has_withdraw:
            raise SecretValidationError(
                f"{role} API key appears to have withdraw permission. Refusing to run."
            )

        has_trade = any(("trade" in token or "order" in token) for token in tokens)
        has_read = any(
            ("read" in token or "readonly" in token or "account" in token or "position" in token)
            for token in tokens
        )

        if role == "read":
            if not has_read:
                raise SecretValidationError("Read-only key does not appear to have read permissions")
            if has_trade:
                raise SecretValidationError("Read-only key appears to have trade permissions")
        elif role == "trade":
            if not has_trade:
                raise SecretValidationError("Trade key does not appear to have trade permissions")

    def _extract_permission_tokens(self, obj: Any) -> Set[str]:
        tokens: Set[str] = set()

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                for k, v in value.items():
                    tokens.add(str(k).strip().lower())
                    walk(v)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
            elif isinstance(value, str):
                tokens.add(value.strip().lower())
            elif isinstance(value, (int, float, bool)):
                tokens.add(str(value).strip().lower())

        walk(obj)
        return tokens
