Recommended command surface

/status
Mode, regime direction, session PnL, loop cycle count, drawdown %, cooldown state
The one command you'll send 10× a day
[add]
/positions
All open positions: symbol, side, entry, current price, pnl%, trail active
Replaces checking Bybit UI when you're away from your desk
[add]
/pnl
Today's realised PnL, total cumulative PnL, win/loss count this session
Pulls from closed_trades + bot_state
[add]
/trades [n]
Last n closed trades with reason (stop, trail, time_exit, partial)
Defaults to (number of trades today) i.e. all today's trades if n not supplied
[add]
/pause
Suspend new entries — equivalent to manual daily drawdown pause
Does not close existing positions; managed loop continues
[add]
/resume
Re-enable new entries after a /pause
Should log the manual override and timestamp
[add]
/close SYMBOL
Manually close a specific open position at market
Requires confirmation reply — bot sends "Reply YES to close BTC/USDC long @ $70,400"
[confirm gate]
/close all
Manually close all open positions at market
Requires confirmation reply — bot sends "Reply YES to close all open positions"
[confirm gate]
/kill
Emergency shutdown — writes kill_switch.flag, triggers close-all flow, exits with code 42
Requires YES confirmation. Already partially wired — this just adds a remote trigger
[confirm gate]
/config
Read-only view of key runtime parameters (mode, leverage buckets, position cap, stop %)
Never expose API keys, secrets, or raw env values
[add]