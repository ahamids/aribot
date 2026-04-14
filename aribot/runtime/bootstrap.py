from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from aribot.config.loader import load_bot_config
from aribot.config.models import BotConfig
from aribot.config.recipes import resolve_recipe_defaults
from aribot.persistence.db import run_startup_migrations
from aribot.plugins.execution_context import PluginExecutionContext
from aribot.plugins.factory import build_runtime_plugins
from aribot.plugins.registry import PluginSelection, build_builtin_registry
from aribot.runtime.engine import Aribot
from secret_loader import SecretLoader, SecretValidationError


@dataclass(frozen=True)
class BootstrapContext:
    config: BotConfig
    bot: Aribot


class Bootstrap:
    def __init__(
        self,
        *,
        profile: str,
        mode: str | None,
        db_path: str | None,
        emoji_mode: str,
        run_migrations: bool,
    ):
        self.profile = profile
        self.mode = mode
        self.db_path = db_path
        self.emoji_mode = emoji_mode
        self.run_migrations = run_migrations

    @classmethod
    def from_args(
        cls,
        *,
        profile: str,
        mode: str | None,
        db_path: str | None,
        emoji_mode: str,
        run_migrations: bool,
    ) -> "Bootstrap":
        return cls(
            profile=profile,
            mode=mode,
            db_path=db_path,
            emoji_mode=emoji_mode,
            run_migrations=run_migrations,
        )

    def build(self) -> BootstrapContext:
        load_dotenv(override=True)

        config = load_bot_config(
            profile=self.profile,
            mode=self.mode,
            emoji_mode=self.emoji_mode,
            db_path=self.db_path,
            run_migrations=self.run_migrations,
        )

        registry = build_builtin_registry()
        selection = PluginSelection(
            exchange=config.plugins.exchange,
            strategy=config.plugins.strategy,
            regime_filter=config.plugins.regime_filter,
            risk=config.plugins.risk,
        )
        registry.ensure_available(selection)

        os.environ["BOT_MODE"] = config.runtime.mode

        if config.runtime.run_migrations:
            run_startup_migrations(config.runtime.db_path)

        secret_loader = SecretLoader()
        startup_secrets = secret_loader.load()
        try:
            secret_loader.validate_startup(startup_secrets)
        except SecretValidationError:
            raise

        bot_settings = dict(config.raw.get("bot", {}))
        recipe_name = str(bot_settings.get("recipe") or os.getenv("ARIBOT_RECIPE", "")).strip().lower()
        if recipe_name:
            recipe_defaults = resolve_recipe_defaults(recipe_name)
            for key, value in recipe_defaults.items():
                # Keep explicit config overrides higher priority than recipe defaults.
                bot_settings.setdefault(key, value)
            bot_settings["recipe"] = recipe_name
        bot_settings.setdefault("db_file", config.runtime.db_path)
        bot_settings.setdefault("market_quote", config.trading.market_quote)

        bot = Aribot(
            startup_secrets=startup_secrets,
            emoji_mode=config.runtime.emoji_mode,
            bot_settings=bot_settings,
        )
        _apply_market_quote(bot, config.trading.market_quote)
        bot.runtime_plugins = build_runtime_plugins(selection, bot)
        bot.runtime_context = PluginExecutionContext(bot, bot.runtime_plugins)
        bot.verify_telegram_readiness()

        return BootstrapContext(config=config, bot=bot)


def _apply_market_quote(bot: Aribot, market_quote: str) -> None:
    quote = market_quote.upper()
    excluded = set(getattr(bot, "excluded_bases", []))

    symbols = []
    for symbol, market in getattr(bot, "markets", {}).items():
        if not market.get("active"):
            continue
        if not market.get("swap"):
            continue
        if market.get("quote") != quote:
            continue
        if market.get("base") in excluded:
            continue
        symbols.append(symbol)

    bot.quote_swaps = sorted(symbols)

    bot.btc_regime_symbol = _resolve_btc_regime_symbol(getattr(bot, "markets", {}), quote) or bot.btc_regime_symbol


def _resolve_btc_regime_symbol(markets: dict, quote: str) -> str | None:
    candidates = [
        f"BTC/{quote}:{quote}",
        f"BTC/{quote}",
        f"BTC{quote}",
    ]
    for symbol in candidates:
        market = markets.get(symbol)
        if isinstance(market, dict) and market.get("active"):
            return symbol
    return None
