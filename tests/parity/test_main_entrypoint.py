import types
import unittest
from unittest.mock import Mock, patch

import main as app_main


class MainEntrypointTests(unittest.TestCase):
    def test_resolve_emoji_mode_conflict_raises(self):
        args = types.SimpleNamespace(emojis=True, noemojis=True)
        with self.assertRaises(SystemExit):
            app_main.resolve_emoji_mode(args)

    def test_main_wires_bootstrap_and_runner(self):
        ctx = types.SimpleNamespace(bot=object())
        bootstrap_instance = Mock()
        bootstrap_instance.build.return_value = ctx

        runner_instance = Mock()
        runner_instance.run.return_value = 7

        with patch("main.Bootstrap.from_args", return_value=bootstrap_instance) as from_args_mock, patch(
            "main.Runner", return_value=runner_instance
        ) as runner_cls_mock:
            code = app_main.main(["--profile", "usdc", "--mode", "paper", "--db", "x.db", "--no-migrate"])

        self.assertEqual(code, 7)
        from_args_mock.assert_called_once_with(
            profile="usdc",
            mode="paper",
            db_path="x.db",
            emoji_mode="noemojis",
            run_migrations=False,
        )
        runner_cls_mock.assert_called_once_with(ctx.bot)
        runner_instance.run.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
