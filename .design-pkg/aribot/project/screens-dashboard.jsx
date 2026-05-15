// Dashboard — the lead screen. Playful frame, serious numbers.

function Dashboard({ status = 'running', mode = 'PAPER', dark = false, dynamicType = false }) {
  const A = window.AT;
  const positions = [
    { symbol: 'BTCUSDT',  side: 'LONG',  size: '0.42', entry: '64,210', mark: '65,840', pnl: 684.20 },
    { symbol: 'ETHUSDT',  side: 'SHORT', size: '3.10', entry: '3,420',  mark: '3,388',  pnl: 99.20 },
    { symbol: 'SOLUSDT',  side: 'LONG',  size: '18.0', entry: '142.10', mark: '141.40', pnl: -12.60 },
  ];
  const equity = [12200, 12180, 12220, 12260, 12190, 12150, 12210, 12340, 12380, 12420, 12500, 12480, 12560];
  const pnlToday = 770.80;
  const bigSize = dynamicType ? 64 : 56;

  const mascotPose = status === 'running' ? 'alert' : status === 'error' ? 'panicked' : status === 'killed' ? 'panicked' : 'sleeping';

  return (
    <Screen tab="home" dark={dark}>
      {/* GREETING + MODE */}
      <div style={{ padding: '8px 6px 14px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: dark ? A.darkMid : A.plumMid, letterSpacing: 0.4 }}>HI THERE</div>
          <div style={{ fontSize: dynamicType ? 32 : 26, fontWeight: 900, letterSpacing: -0.5 }}>Aribot</div>
        </div>
        <ModeChip mode={mode} active />
      </div>

      {/* STATUS CARD */}
      <Card dark={dark} padding={0} style={{ overflow: 'hidden', marginBottom: 18 }}>
        <div style={{
          padding: '18px 20px 16px',
          background: status === 'running' ? `linear-gradient(180deg, ${A.mint} 0%, ${dark ? A.darkPaper : '#fff'} 70%)`
            : status === 'error' || status === 'killed' ? `linear-gradient(180deg, ${A.pnlRedSoft} 0%, ${dark ? A.darkPaper : '#fff'} 70%)`
            : `linear-gradient(180deg, ${A.creamDeep} 0%, ${dark ? A.darkPaper : '#fff'} 70%)`,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <MascotSlot size={92} pose={mascotPose} tone={status === 'running' ? 'yellow' : 'cream'} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <StatusPill status={status} mode={mode} style={{ marginBottom: 10 }} />
              <div style={{ fontSize: 13, color: dark ? A.darkMid : A.plumMid, fontWeight: 600 }}>
                {status === 'running' ? 'Last cycle 2m ago · next in 1h 58m'
                  : status === 'error' ? 'Last cycle failed · 12m ago'
                  : status === 'killed' ? 'Kill switch tripped · 5m ago'
                  : 'Last cycle 4h ago'}
              </div>
            </div>
          </div>

          {/* Primary action */}
          <div style={{ marginTop: 18 }}>
            {status === 'running' ? (
              <Btn kind="danger" size="lg" style={{ width: '100%' }} icon={<Icon name="x" size={20}/>}>STOP BOT</Btn>
            ) : status === 'killed' ? (
              <Btn kind="ghost" size="lg" style={{ width: '100%' }} dark={dark}>KILL SWITCH ACTIVE</Btn>
            ) : (
              <Btn kind="primary" size="lg" style={{ width: '100%' }} icon={<Icon name="bolt" size={20}/>}>START BOT</Btn>
            )}
          </div>
        </div>
      </Card>

      {/* PNL CARD */}
      <Card dark={dark} color={dark ? A.darkPaper : '#fff'} style={{ marginBottom: 18 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
          <div style={{ fontSize: 12, fontWeight: 800, letterSpacing: 0.8, color: dark ? A.darkMid : A.plumMid }}>TODAY'S PNL</div>
          <div style={{ fontSize: 11, color: dark ? A.darkMid : A.plumMid, fontFamily: A.num, fontVariantNumeric: 'tabular-nums' }}>EQUITY $12,560.12</div>
        </div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
          <Money value={pnlToday} size={bigSize} dark={dark} />
          <span style={{ fontSize: 16, fontWeight: 700, color: A.pnlGreen, fontFamily: A.num, fontVariantNumeric: 'tabular-nums' }}>
            +6.53%
          </span>
        </div>
        <div style={{ marginTop: 10, marginLeft: -4 }}>
          <Sparkline data={equity} width={320} height={56} dark={dark} />
        </div>
      </Card>

      {/* POSITIONS PREVIEW */}
      <Card dark={dark} color={dark ? A.darkPaper : '#fff'}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
          <div style={{ fontSize: 12, fontWeight: 800, letterSpacing: 0.8, color: dark ? A.darkMid : A.plumMid }}>OPEN POSITIONS · 3</div>
          <span style={{ fontSize: 13, fontWeight: 800, color: A.coralDeep, display: 'flex', alignItems: 'center', gap: 4 }}>
            See all <Icon name="chevron" size={14} />
          </span>
        </div>
        <div>
          {positions.map((p, i) => (
            <div key={p.symbol} style={i === positions.length - 1 ? { borderBottom: 'none' } : {}}>
              <PositionRow p={p} dark={dark} />
            </div>
          ))}
        </div>
      </Card>
    </Screen>
  );
}

Object.assign(window, { Dashboard });
