from __future__ import annotations


class Runner:
    def __init__(self, bot):
        self.bot = bot

    def run(self) -> int:
        try:
            exit_code = self.bot.run()
        except KeyboardInterrupt:
            self.bot.logger.info("Stopped by user")
            self.bot.persist_runtime_state()
            self.bot.display_status()
            return 0

        return int(exit_code or 0)
