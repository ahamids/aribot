# Aribot Deployment Checklist

## VPS Preparation

1. Provision Ubuntu 24 VPS.
2. Create app directory: `/opt/aribot`.
3. Create config directory: `/etc/aribot`.
4. Install OS packages:
   - `python3`
   - `python3-venv`
   - `python3-pip`
5. Create virtualenv at `/opt/aribot/.venv`.
6. Install Python dependencies:
   - `ccxt`
   - `requests`

## Source and Runtime Configuration

1. Deploy repository contents into `/opt/aribot`.
2. Create `/etc/aribot/aribot.env` with:
   - `BOT_MODE=live|shadow`
   - `BYBIT_TESTNET=true|false`
   - `BYBIT_READ_API_KEY`
   - `BYBIT_READ_API_SECRET`
   - `BYBIT_TRADE_API_KEY`
   - `BYBIT_TRADE_API_SECRET`
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `KILL_SWITCH_FILE=/opt/aribot/kill_switch.flag`
3. Ensure `/etc/aribot/aribot.env` permissions are restricted:
   - owner root or service user
   - mode `600`

## systemd Service Setup

1. Copy [deploy/aribot.service](deploy/aribot.service) to `/etc/systemd/system/aribot.service`.
2. Run:

```bash
sudo systemctl daemon-reload
sudo systemctl enable aribot
sudo systemctl start aribot
```

3. Verify status:

```bash
sudo systemctl status aribot
journalctl -u aribot -f
```

## Alerting Validation

1. Confirm Telegram bot token and chat id are valid.
2. Trigger a test startup and verify message delivery for:
   - position_opened
   - position_closed
   - circuit_breaker_triggered
   - kill_switch_detected
3. Confirm failures to send alerts do not crash the bot.

## Kill Switch Validation

1. Create kill switch file:

```bash
touch /opt/aribot/kill_switch.flag
```

2. Confirm bot:
   - detects kill switch on loop iteration
   - logs CRITICAL event
   - closes positions
   - exits with code `42`
3. Confirm systemd does **not** restart service after intentional kill-switch shutdown.
4. Remove flag before restart:

```bash
rm /opt/aribot/kill_switch.flag
sudo systemctl start aribot
```

## Crash Recovery Validation

1. Kill the process unexpectedly.
2. Confirm systemd restarts it automatically.
3. Confirm startup validation and reconciliation still run before trading resumes.

## Final Go-Live Checks

1. `BYBIT_TESTNET=false` only after shadow/testnet sign-off.
2. Telegram alerts confirmed in production chat.
3. Structured logs present in `observability.jsonl`.
4. Funding entries appear in `funding_payments`.
5. Kill switch tested and documented.
6. Branch protections and verify harness green on deployed commit.