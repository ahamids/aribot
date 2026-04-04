import unittest

from aribot.config.loader import load_bot_config


class ConfigProfileLoadingTests(unittest.TestCase):
    def test_usdt_profile_sets_usdt_quote(self):
        config = load_bot_config(
            profile="usdt",
            mode="paper",
            emoji_mode="noemojis",
            db_path=None,
            run_migrations=False,
        )
        self.assertEqual(config.trading.market_quote, "USDT")

    def test_usdc_profile_sets_usdc_quote(self):
        config = load_bot_config(
            profile="usdc",
            mode="paper",
            emoji_mode="noemojis",
            db_path=None,
            run_migrations=False,
        )
        self.assertEqual(config.trading.market_quote, "USDC")


if __name__ == "__main__":
    unittest.main()
