// Positions full screen, History, Settings, Live confirm, Kill switch.

function Positions({ dark = false }) {
  const A = window.AT;
  const positions = [
    { symbol: 'BTCUSDT', side: 'LONG',  size: '0.42', entry: '64,210', mark: '65,840', pnl: 684.20, lev: '5x',  liq: '54,820', age: '3h 22m', spark: [100,102,98,101,104,106,110,108,112,115,118,116,122] },
    { symbol: 'ETHUSDT', side: 'SHORT', size: '3.10', entry: '3,420',  mark: '3,388',  pnl: 99.20,  lev: '3x',  liq: '4,120',  age: '1h 04m', spark: [100,101,99,102,100,98,96,97,95,94,96,95,93] },
    { symbol: 'SOLUSDT', side: 'LONG',  size: '18.0', entry: '142.10', mark: '141.40', pnl: -12.60, lev: '5x',  liq: '128.40', age: '0h 38m', spark: [100,101,103,102,100,99,98,99,97,96,95,97,96] },
    { symbol: 'AVAXUSDT',side: 'LONG',  size: '24.0', entry: '38.20',  mark: '39.10',  pnl: 21.60,  lev: '4x',  liq: '32.80',  age: '6h 12m', spark: [100,99,101,103,102,104,103,105,107,106,108,109,107] },
  ];
  return (
    <Screen tab="positions" title="Positions" dark={dark}>
      <div style={{ padding: '0 0 8px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <Segmented options={['Open · 4','Closed']} value="Open · 4" dark={dark} />
        <button style={{
          width: 40, height: 40, borderRadius: '50%',
          background: dark ? A.darkCard : '#fff', border: dark ? '2px solid rgba(255,255,255,0.06)' : A.ol2,
          color: dark ? A.darkText : A.plum, boxShadow: A.shStickerHard(dark ? '#000' : A.plum),
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}><Icon name="refresh" size={18} /></button>
      </div>
      <div style={{ fontSize: 11, color: dark ? A.darkMid : A.plumMid, textAlign: 'center', padding: '4px 0 12px', fontWeight: 700, letterSpacing: 0.6 }}>↓  PULL TO REFRESH</div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {positions.map(p => (
          <Card key={p.symbol} dark={dark} color={dark ? A.darkPaper : '#fff'} padding={16}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 18, fontWeight: 900, fontFamily: A.num, letterSpacing: -0.3 }}>{p.symbol}</span>
                <SideChip side={p.side} />
                <span style={{ fontSize: 11, fontWeight: 800, color: dark ? A.darkMid : A.plumMid, padding: '2px 8px', borderRadius: A.rPill, background: dark ? '#3F324F' : A.creamDeep }}>{p.lev}</span>
              </div>
              <Money value={p.pnl} size={22} dark={dark} />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 14px', marginBottom: 10 }}>
              <KV label="SIZE" value={p.size} dark={dark} />
              <KV label="MARK" value={'$' + p.mark} dark={dark} />
              <KV label="ENTRY" value={'$' + p.entry} dark={dark} />
              <KV label="LIQ" value={'$' + p.liq} dark={dark} danger />
            </div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderTop: '1.5px dashed ' + (dark ? 'rgba(255,255,255,0.08)' : 'rgba(45,31,71,0.12)'), paddingTop: 10 }}>
              <span style={{ fontSize: 11, color: dark ? A.darkMid : A.plumMid, fontWeight: 700 }}>OPEN {p.age}</span>
              <Sparkline data={p.spark} width={120} height={28} dark={dark} />
            </div>
          </Card>
        ))}
      </div>
    </Screen>
  );
}

function KV({ label, value, dark, danger }) {
  const A = window.AT;
  return (
    <div>
      <div style={{ fontSize: 10, fontWeight: 800, letterSpacing: 0.7, color: dark ? A.darkMid : A.plumMid }}>{label}</div>
      <div style={{ fontSize: 14, fontWeight: 800, fontFamily: A.num, fontVariantNumeric: 'tabular-nums', color: danger ? A.pnlRed : (dark ? A.darkText : A.plum) }}>{value}</div>
    </div>
  );
}

function History({ view = 'trades', dark = false }) {
  const A = window.AT;
  const trades = [
    { symbol: 'BTCUSDT', side: 'LONG',  pnl: 412.20, when: '2:14 PM',  date: 'Today' },
    { symbol: 'ETHUSDT', side: 'SHORT', pnl: -88.40, when: '11:02 AM', date: 'Today' },
    { symbol: 'SOLUSDT', side: 'LONG',  pnl: 124.60, when: '8:30 AM',  date: 'Today' },
    { symbol: 'BTCUSDT', side: 'SHORT', pnl: 220.10, when: '6:14 PM',  date: 'Yesterday' },
    { symbol: 'AVAXUSDT',side: 'LONG',  pnl: -42.00, when: '12:00 PM', date: 'Yesterday' },
    { symbol: 'ETHUSDT', side: 'LONG',  pnl: 312.00, when: '4:00 AM',  date: 'Yesterday' },
  ];
  const eq = [11800,11820,11760,11900,12050,11990,12100,12180,12240,12200,12320,12410,12380,12500,12480,12550,12560];
  return (
    <Screen tab="history" title="History" dark={dark}>
      <div style={{ display: 'flex', justifyContent: 'center', padding: '0 0 16px' }}>
        <Segmented options={['Trades','Equity']} value={view === 'trades' ? 'Trades' : 'Equity'} dark={dark}/>
      </div>

      {view === 'equity' ? (
        <>
          <Card dark={dark} color={dark ? A.darkPaper : '#fff'} style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: 0.7, color: dark ? A.darkMid : A.plumMid }}>7-DAY EQUITY</div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginTop: 2 }}>
              <Money value={760.40} size={36} dark={dark} />
              <span style={{ fontSize: 13, color: A.pnlGreen, fontWeight: 800, fontFamily: A.num }}>+6.45%</span>
            </div>
            <div style={{ marginTop: 16, marginLeft: -6 }}>
              {/* Chart with toon axes */}
              <svg width="320" height="160" viewBox="0 0 320 160">
                <line x1="22" y1="10" x2="22" y2="140" stroke={dark ? A.darkMid : A.plumMid} strokeWidth="2.5" strokeLinecap="round"/>
                <line x1="22" y1="140" x2="312" y2="140" stroke={dark ? A.darkMid : A.plumMid} strokeWidth="2.5" strokeLinecap="round"/>
                {[0,1,2,3].map(i => (
                  <line key={i} x1="22" y1={140 - i*30 - 5} x2="312" y2={140 - i*30 - 5} stroke={dark ? 'rgba(255,255,255,0.05)' : 'rgba(45,31,71,0.07)'} strokeDasharray="3 4" />
                ))}
                {(() => {
                  const min = Math.min(...eq), max = Math.max(...eq); const sp = max-min;
                  const stepX = 290 / (eq.length-1);
                  const pts = eq.map((v,i) => `${22+i*stepX},${140 - ((v-min)/sp)*115}`).join(' ');
                  return (<>
                    <polyline points={pts} fill="none" stroke={A.coral} strokeWidth="3.5" strokeLinejoin="round" strokeLinecap="round"/>
                    <polygon points={`22,140 ${pts} 312,140`} fill={A.coral} opacity="0.18"/>
                  </>);
                })()}
                {['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].map((d,i) => (
                  <text key={d} x={22 + i*42 + 8} y="156" fontSize="10" fontWeight="700" fill={dark ? A.darkMid : A.plumMid} fontFamily={A.font}>{d}</text>
                ))}
              </svg>
            </div>
          </Card>
          <Card dark={dark} color={dark ? A.darkPaper : '#fff'} padding={16}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <KV label="WIN RATE" value="62%" dark={dark}/>
              <KV label="TRADES" value="184" dark={dark}/>
              <KV label="AVG WIN" value="+$142" dark={dark}/>
              <KV label="AVG LOSS" value="−$78" dark={dark}/>
            </div>
          </Card>
        </>
      ) : (
        <div>
          {['Today', 'Yesterday'].map(day => (
            <div key={day} style={{ marginBottom: 18 }}>
              <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: 0.7, color: dark ? A.darkMid : A.plumMid, margin: '0 4px 8px' }}>{day.toUpperCase()}</div>
              <Card dark={dark} color={dark ? A.darkPaper : '#fff'} padding={4}>
                {trades.filter(t => t.date === day).map((t, i, arr) => (
                  <div key={i} style={{
                    padding: '14px 16px',
                    borderBottom: i < arr.length - 1 ? '1.5px dashed ' + (dark ? 'rgba(255,255,255,0.08)' : 'rgba(45,31,71,0.1)') : 'none',
                    display: 'flex', alignItems: 'center', gap: 12,
                  }}>
                    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ fontWeight: 900, fontSize: 15, fontFamily: A.num }}>{t.symbol}</span>
                        <SideChip side={t.side}/>
                      </div>
                      <div style={{ fontSize: 11, color: dark ? A.darkMid : A.plumMid }}>{t.when}</div>
                    </div>
                    <Money value={t.pnl} size={18} dark={dark} />
                  </div>
                ))}
              </Card>
            </div>
          ))}
        </div>
      )}
    </Screen>
  );
}

function Settings({ dark = false }) {
  const A = window.AT;
  return (
    <Screen tab="settings" title="Settings" dark={dark}>
      <SectionLabel dark={dark}>ACCOUNT</SectionLabel>
      <Card dark={dark} color={dark ? A.darkPaper : '#fff'} padding={0} style={{ marginBottom: 18 }}>
        <Row dark={dark} left="Email" right="alex@trader.co" />
        <Row dark={dark} left="Plan" right="Personal" />
        <Row dark={dark} left="Sign out" right={<span style={{ color: A.pnlRed, fontWeight: 800 }}>›</span>} last />
      </Card>

      <SectionLabel dark={dark}>BOT</SectionLabel>
      <Card dark={dark} color={dark ? A.darkPaper : '#fff'} padding={0} style={{ marginBottom: 14 }}>
        <Row dark={dark} left="Host URL" right="aribot.alex.dev" />
        <Row dark={dark} left="Bearer token" right="ari_pat_…3920" />
        <Row dark={dark} left="Test connection" right={<span style={{ color: A.pnlGreen, fontWeight: 800 }}>✓ OK</span>} last />
      </Card>

      <SectionLabel dark={dark}>MODE</SectionLabel>
      <Card dark={dark} color={dark ? A.darkPaper : '#fff'} padding={16} style={{ marginBottom: 14 }}>
        <div style={{ display: 'flex', gap: 8 }}>
          <ModeChip mode="PAPER" active />
          <ModeChip mode="SHADOW" />
          <ModeChip mode="LIVE" />
        </div>
        <div style={{ marginTop: 12, padding: '10px 12px', background: A.pnlRedSoft, borderRadius: A.rM, border: '2px solid ' + A.pnlRed, display: 'flex', gap: 8, alignItems: 'flex-start' }}>
          <span style={{ fontSize: 16 }}>⚠</span>
          <div style={{ fontSize: 12, color: A.plum, lineHeight: 1.4, fontWeight: 600 }}>
            LIVE places real orders on Bybit. Requires typed confirmation.
          </div>
        </div>
      </Card>

      <SectionLabel dark={dark}>SAFETY</SectionLabel>
      <Card dark={dark} color={dark ? A.darkPaper : '#fff'} padding={16} style={{ marginBottom: 14 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 6 }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 900, fontSize: 15 }}>Kill switch</div>
            <div style={{ fontSize: 12, color: dark ? A.darkMid : A.plumMid, lineHeight: 1.4 }}>Closes everything, blocks new orders.</div>
          </div>
          <KillButton armed={false} dark={dark}/>
        </div>
      </Card>

      <SectionLabel dark={dark}>NOTIFICATIONS</SectionLabel>
      <Card dark={dark} color={dark ? A.darkPaper : '#fff'} padding={0} style={{ marginBottom: 14 }}>
        <Row dark={dark} left="Fill alerts" right={<Toggle on dark={dark}/>} />
        <Row dark={dark} left="Error alerts" right={<Toggle on dark={dark}/>} />
        <Row dark={dark} left="Daily summary" right={<Toggle on={false} dark={dark}/>} last />
      </Card>

      <div style={{ textAlign: 'center', padding: '14px 0 0', fontSize: 11, color: dark ? A.darkMid : A.plumMid }}>
        Aribot · v1.0.0 · build 24
      </div>
    </Screen>
  );
}

function SectionLabel({ children, dark }) {
  const A = window.AT;
  return <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: 0.8, color: dark ? A.darkMid : A.plumMid, margin: '4px 8px 8px' }}>{children}</div>;
}

function Row({ left, right, last, dark }) {
  const A = window.AT;
  return (
    <div style={{
      padding: '14px 16px', display: 'flex', alignItems: 'center', gap: 12,
      borderBottom: last ? 'none' : '1.5px dashed ' + (dark ? 'rgba(255,255,255,0.08)' : 'rgba(45,31,71,0.1)'),
    }}>
      <div style={{ flex: 1, fontSize: 15, fontWeight: 700 }}>{left}</div>
      <div style={{ fontSize: 14, color: dark ? A.darkMid : A.plumMid, fontWeight: 600 }}>{right}</div>
    </div>
  );
}

function KillButton({ armed = false, holding = 0, dark }) {
  const A = window.AT;
  return (
    <div style={{
      position: 'relative', width: 72, height: 40, borderRadius: A.rPill,
      background: A.pnlRedSoft, border: '3px solid ' + A.pnlRed, overflow: 'hidden',
      boxShadow: A.shStickerHard(A.plum),
    }}>
      <div style={{ position: 'absolute', inset: 0, background: A.pnlRed, transform: `scaleX(${holding})`, transformOrigin: 'left', transition: 'transform .12s' }}/>
      <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, fontWeight: 900, color: A.plum, letterSpacing: 0.5 }}>
        HOLD 1.5s
      </div>
    </div>
  );
}

// LIVE-mode confirmation sheet
function LiveConfirmSheet() {
  const A = window.AT;
  return (
    <Screen bgOverride={'rgba(45,31,71,0.55)'} hideHomeIndicator>
      <div style={{ height: '100%', display: 'flex', alignItems: 'flex-end', padding: '0 0 0' }}>
        <div style={{
          width: '100%', background: A.cream, borderRadius: '28px 28px 0 0',
          border: A.ol3, borderBottom: 'none', padding: 24,
          boxShadow: '0 -12px 30px rgba(45,31,71,0.25)',
        }}>
          <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 14 }}>
            <div style={{ width: 44, height: 5, background: A.plumMid, borderRadius: 3 }}/>
          </div>
          <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 12 }}>
            <MascotSlot size={100} pose="serious" tone="coral" />
          </div>
          <div style={{ textAlign: 'center', fontWeight: 900, fontSize: 22, letterSpacing: -0.3 }}>
            Start in <span style={{ color: A.pnlRed }}>LIVE</span> mode?
          </div>
          <div style={{ textAlign: 'center', fontSize: 13, color: A.plumMid, lineHeight: 1.4, padding: '6px 16px 14px' }}>
            Real orders will be placed on Bybit using your trade key.
          </div>

          <Card color={A.paper} padding={14} style={{ marginBottom: 14 }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px 16px' }}>
              <KV label="MARKET" value="BTC/USDT 4H" />
              <KV label="MAX RISK" value="2% / trade" />
              <KV label="LEVERAGE" value="5x" />
              <KV label="DAILY CAP" value="$2,500" />
            </div>
          </Card>

          <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: 0.7, color: A.plumMid, margin: '0 4px 6px' }}>TYPE LIVE TO CONFIRM</div>
          <Input value="LIVE" />
          <div style={{ display: 'flex', gap: 10, marginTop: 14 }}>
            <Btn kind="soft" size="lg" style={{ flex: 1 }}>Cancel</Btn>
            <Btn kind="danger" size="lg" style={{ flex: 1.4 }}>Start live</Btn>
          </div>
        </div>
      </div>
    </Screen>
  );
}

Object.assign(window, { Positions, History, Settings, KillButton, LiveConfirmSheet });
