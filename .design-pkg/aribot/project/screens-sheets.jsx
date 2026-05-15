// Design system sheets: components, mascot poses, palette, type scale, flows, trust moment.

function ComponentSheet() {
  const A = window.AT;
  return (
    <div style={{ width: 920, padding: 32, background: A.cream, fontFamily: A.font, color: A.plum }}>
      <SheetHeader title="Components" subtitle="Buttons · inputs · pills · cards · rows" />

      <SheetGroup title="Buttons">
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
          <Btn kind="primary">Primary</Btn>
          <Btn kind="secondary">Secondary</Btn>
          <Btn kind="mint">Mint</Btn>
          <Btn kind="soft">Soft</Btn>
          <Btn kind="danger">Destructive</Btn>
          <Btn kind="ghost">Ghost</Btn>
        </div>
        <div style={{ display: 'flex', gap: 12, marginTop: 14, alignItems: 'center' }}>
          <Btn kind="primary" size="sm">Small</Btn>
          <Btn kind="primary" size="md">Medium</Btn>
          <Btn kind="primary" size="lg" icon={<Icon name="bolt" size={20}/>}>Large + Icon</Btn>
        </div>
      </SheetGroup>

      <SheetGroup title="Inputs">
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, maxWidth: 700 }}>
          <Input label="EMAIL" value="alex@trader.co" />
          <Input label="PASSWORD" secure value="hunter2" />
          <Input label="HOST URL" value="https://aribot.alex.dev" icon={<Icon name="server" size={16}/>} monospace />
          <Input label="BEARER TOKEN" secure value="ari_pat_9c2B" monospace error hint="That token wasn\u2019t accepted." />
        </div>
      </SheetGroup>

      <SheetGroup title="Status">
        <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
          <StatusPill status="running" mode="PAPER"/>
          <StatusPill status="stopped"/>
          <StatusPill status="error"/>
          <StatusPill status="killed"/>
          <ModeChip mode="PAPER" active />
          <ModeChip mode="SHADOW" active />
          <ModeChip mode="LIVE" active />
          <SideChip side="LONG"/>
          <SideChip side="SHORT"/>
        </div>
      </SheetGroup>

      <SheetGroup title="Cards & rows">
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, maxWidth: 700 }}>
          <Card padding={18}>
            <div style={{ fontSize: 12, fontWeight: 800, letterSpacing: 0.7, color: A.plumMid }}>TODAY\u2019S PNL</div>
            <Money value={770.80} size={36} />
            <Sparkline data={[100,98,102,108,112,118,124,128]} width={240} height={40}/>
          </Card>
          <Card padding={16}>
            <PositionRow p={{ symbol:'BTCUSDT', side:'LONG', size:'0.42', entry:'64,210', mark:'65,840', pnl: 684.20 }} />
            <PositionRow p={{ symbol:'ETHUSDT', side:'SHORT', size:'3.10', entry:'3,420', mark:'3,388', pnl: 99.20 }} />
          </Card>
        </div>
      </SheetGroup>

      <SheetGroup title="Controls">
        <div style={{ display: 'flex', gap: 28, alignItems: 'center' }}>
          <Toggle on />
          <Toggle on={false} />
          <Segmented options={['Trades','Equity']} value="Trades" />
          <KillButton holding={0} />
          <KillButton holding={0.7} />
        </div>
      </SheetGroup>

      <SheetGroup title="Tab bar">
        <div style={{ width: 380, height: 90, position: 'relative', background: A.creamDeep, borderRadius: 24, border: A.ol2 }}>
          <TabBar active="home" />
        </div>
      </SheetGroup>
    </div>
  );
}

function MascotSheet() {
  const A = window.AT;
  const poses = [
    { pose: 'alert',       tone: 'yellow', label: 'alert · running' },
    { pose: 'sleeping',    tone: 'cream',  label: 'sleeping · stopped' },
    { pose: 'panicked',    tone: 'cream',  label: 'panicked · error' },
    { pose: 'thumbsup',    tone: 'mint',   label: 'thumbs-up · connected' },
    { pose: 'questioning', tone: 'yellow', label: 'scratching head · ?' },
    { pose: 'napping',     tone: 'cream',  label: 'napping · no data' },
    { pose: 'serious',     tone: 'coral',  label: 'serious · live mode' },
    { pose: 'waving',      tone: 'peri',   label: 'waving · hello' },
    { pose: 'wink',        tone: 'mint',   label: 'wink · peeking' },
    { pose: 'sad',         tone: 'cream',  label: 'sad · loss day' },
  ];
  return (
    <div style={{ width: 920, padding: 32, background: A.cream, fontFamily: A.font, color: A.plum }}>
      <SheetHeader title="Mascot expressions" subtitle="Placeholder bear · all poses share the same SLOT — character is swappable" />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 18 }}>
        {poses.map(p => (
          <div key={p.pose} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10 }}>
            <MascotSlot size={130} pose={p.pose} tone={p.tone} />
            <div style={{ fontSize: 11, fontWeight: 700, color: A.plumMid, letterSpacing: 0.3, textAlign: 'center' }}>{p.label}</div>
          </div>
        ))}
      </div>

      <SheetGroup title="The slot · drop-in container">
        <div style={{ display: 'flex', gap: 22, alignItems: 'center' }}>
          {['yellow','mint','peri','coral','cream'].map(tone => (
            <div key={tone} style={{ display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'center' }}>
              <MascotSlot size={100} pose="alert" tone={tone} />
              <div style={{ fontSize: 11, color: A.plumMid, fontWeight: 700 }}>{tone}</div>
            </div>
          ))}
        </div>
        <div style={{ fontSize: 13, color: A.plumMid, marginTop: 16, maxWidth: 620, lineHeight: 1.5 }}>
          The character lives inside a thick-outlined circular slot. Swap the character art and the slot frame, tone, and shadow stay the same — every screen that uses MascotSlot picks up the new face for free.
        </div>
      </SheetGroup>

      <SheetGroup title="With props (empty/error states)">
        <div style={{ display: 'flex', gap: 22, flexWrap: 'wrap' }}>
          {[['flag','panicked','cream'],['cable','panicked','cream'],['chart','questioning','mint'],['vault','serious','yellow']].map(([prop,pose,tone]) => (
            <div key={prop} style={{ display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'center' }}>
              <div style={{ position: 'relative', width: 130, height: 130 }}>
                <MascotSlot size={130} pose={pose} tone={tone} />
                <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}><MProp kind={prop}/></div>
              </div>
              <div style={{ fontSize: 11, fontWeight: 700, color: A.plumMid }}>{prop}</div>
            </div>
          ))}
        </div>
      </SheetGroup>
    </div>
  );
}

function PaletteSheet() {
  const A = window.AT;
  const swatches = [
    { name: 'cream',     hex: '#FFF4E6', use: 'App background (light)' },
    { name: 'creamDeep', hex: '#FFE9C9', use: 'Filled chips, soft cards' },
    { name: 'paper',     hex: '#FFFAF1', use: 'Inset surfaces inside cards' },
    { name: 'plum',      hex: '#2D1F47', use: 'Text + outlines + hard shadows' },
    { name: 'plumMid',   hex: '#5B4880', use: 'Secondary text' },
    { name: 'plumSoft',  hex: '#9B8FB8', use: 'Placeholder / tertiary' },
    { name: 'coral',     hex: '#FF8B66', use: 'Primary action, active tab' },
    { name: 'yellow',    hex: '#FFC93C', use: 'Secondary action, accent' },
    { name: 'mint',      hex: '#7DD3AE', use: 'Mint button, success bg' },
    { name: 'peri',      hex: '#8B9DFF', use: 'Info, trust strip' },
  ];
  const reserved = [
    { name: 'pnlGreen',  hex: '#30A46C', use: 'POSITIVE PnL ONLY' },
    { name: 'pnlRed',    hex: '#E5484D', use: 'NEGATIVE PnL ONLY / kill switch / live warning' },
  ];
  const dark = [
    { name: 'darkBg',    hex: '#241A2E', use: 'App background (dark)' },
    { name: 'darkPaper', hex: '#2F2440', use: 'Card surface' },
    { name: 'darkCard',  hex: '#3A2C50', use: 'Input bg, segmented track' },
    { name: 'darkText',  hex: '#FFEBC7', use: 'Primary text (warm cream, not white)' },
    { name: 'darkMid',   hex: '#C4B0E0', use: 'Secondary text' },
  ];

  const Sw = ({ name, hex, use, dark, big }) => (
    <div style={{ display: 'flex', gap: 12, alignItems: 'center', padding: 8, borderRadius: 12, background: dark ? '#3A2C50' : '#fff', border: dark ? '2px solid rgba(255,255,255,0.05)' : '2px solid rgba(45,31,71,0.08)' }}>
      <div style={{ width: big ? 70 : 54, height: big ? 70 : 54, borderRadius: 14, background: hex, border: '2.5px solid ' + A.plum, boxShadow: '0 3px 0 ' + A.plum, flexShrink: 0 }}/>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 900, fontSize: 13, color: dark ? '#FFEBC7' : A.plum }}>{name}</div>
        <div style={{ fontSize: 11, fontFamily: 'ui-monospace, Menlo', color: dark ? '#C4B0E0' : A.plumMid, marginTop: 2 }}>{hex}</div>
        <div style={{ fontSize: 11, color: dark ? '#C4B0E0' : A.plumMid, marginTop: 3, lineHeight: 1.3 }}>{use}</div>
      </div>
    </div>
  );

  return (
    <div style={{ width: 920, padding: 32, background: A.cream, fontFamily: A.font, color: A.plum }}>
      <SheetHeader title="Palette" subtitle="Cream base · warm dark base · candy accents · two reserved-for-PnL colors only" />

      <SheetGroup title="Surface & text">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
          {swatches.slice(0,6).map(s => <Sw key={s.name} {...s}/>)}
        </div>
      </SheetGroup>

      <SheetGroup title="Candy accents · decoration & non-PnL UI">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
          {swatches.slice(6).map(s => <Sw key={s.name} {...s}/>)}
        </div>
      </SheetGroup>

      <SheetGroup title="🔒 Reserved · PnL & direction & kill switch only">
        <div style={{ background: A.pnlRedSoft, border: '3px solid ' + A.pnlRed, borderRadius: 16, padding: 16, marginBottom: 16 }}>
          <div style={{ fontWeight: 900, fontSize: 14, color: A.plum, marginBottom: 4 }}>The trust rule</div>
          <div style={{ fontSize: 13, color: A.plum, lineHeight: 1.5, maxWidth: 720 }}>
            Pure red and pure green do not appear anywhere except PnL signs, LONG/SHORT chips, the kill switch, and the LIVE-mode confirm. No buttons, no decorative shapes, no charts in unrelated contexts. The candy accents above carry every other visual job — that's what keeps the cartoon styling from undermining trust on data screens.
          </div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12 }}>
          {reserved.map(s => <Sw key={s.name} {...s} big/>)}
        </div>
      </SheetGroup>

      <SheetGroup title="Dark mode (warm dark, not black)">
        <div style={{ background: A.darkBg, padding: 16, borderRadius: 16, border: A.ol2, display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
          {dark.map(s => <Sw key={s.name} {...s} dark/>)}
        </div>
      </SheetGroup>
    </div>
  );
}

function TypeSheet() {
  const A = window.AT;
  const rows = [
    { name: 'Hero PnL',         size: 56, weight: 800, tab: true,  family: 'SF Pro Rounded', sample: '+$770.80' },
    { name: 'Page title',       size: 32, weight: 900, tab: false, family: 'SF Pro Rounded', sample: 'Positions' },
    { name: 'Section H2',       size: 28, weight: 900, tab: false, family: 'SF Pro Rounded', sample: 'Connect your bot' },
    { name: 'Position PnL',     size: 22, weight: 800, tab: true,  family: 'SF Pro Rounded', sample: '+$684.20' },
    { name: 'Row symbol',       size: 17, weight: 800, tab: true,  family: 'SF Pro Rounded', sample: 'BTCUSDT' },
    { name: 'Body',             size: 16, weight: 600, tab: false, family: 'SF Pro Rounded', sample: 'Keys are encrypted on this device.' },
    { name: 'KV value',         size: 14, weight: 800, tab: true,  family: 'SF Pro Rounded', sample: '$65,840' },
    { name: 'Detail / hint',    size: 13, weight: 600, tab: false, family: 'SF Pro Rounded', sample: 'Last cycle 2m ago' },
    { name: 'Section label',    size: 11, weight: 800, tab: false, family: 'SF Pro Rounded', sample: 'OPEN POSITIONS' },
  ];
  return (
    <div style={{ width: 920, padding: 32, background: A.cream, fontFamily: A.font, color: A.plum }}>
      <SheetHeader title="Type scale" subtitle='SF Pro Rounded · tabular figures on every number · letters always tight' />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {rows.map(r => (
          <div key={r.name} style={{
            display: 'grid', gridTemplateColumns: '170px 100px 70px 80px 1fr',
            alignItems: 'center', gap: 18, padding: '14px 16px',
            background: '#fff', borderRadius: 14, border: '2px solid rgba(45,31,71,0.08)',
          }}>
            <span style={{ fontWeight: 800, fontSize: 13 }}>{r.name}</span>
            <span style={{ fontSize: 12, color: A.plumMid, fontFamily: 'ui-monospace' }}>{r.size}pt / w{r.weight}</span>
            <span style={{ fontSize: 11, color: r.tab ? A.coralDeep : A.plumSoft, fontWeight: 800 }}>{r.tab ? 'TABULAR' : '—'}</span>
            <span style={{ fontSize: 11, color: A.plumMid }}>{r.family.split(' ').slice(-1)[0]}</span>
            <span style={{ fontSize: r.size, fontWeight: r.weight, fontVariantNumeric: r.tab ? 'tabular-nums' : 'normal', letterSpacing: -0.4, color: A.plum }}>{r.sample}</span>
          </div>
        ))}
      </div>
      <SheetGroup title="Hierarchy in context">
        <div style={{ background: '#fff', padding: 28, borderRadius: 18, border: A.ol2 }}>
          <div style={{ fontSize: 11, fontWeight: 800, color: A.plumMid, letterSpacing: 0.8 }}>TODAY'S PNL</div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 14, marginTop: 4 }}>
            <Money value={770.80} size={56}/>
            <span style={{ fontSize: 18, color: A.pnlGreen, fontWeight: 800, fontFamily: A.num, fontVariantNumeric: 'tabular-nums' }}>+6.53%</span>
          </div>
          <div style={{ fontSize: 13, color: A.plumMid, marginTop: 4 }}>Equity $12,560.12 · last cycle 2m ago</div>
        </div>
      </SheetGroup>
    </div>
  );
}

function FlowDiagram({ kind }) {
  const A = window.AT;
  const flows = {
    onboarding: {
      title: 'Onboarding flow', subtitle: 'First-run · Welcome → Dashboard',
      nodes: [
        { id: 'welcome',  label: 'Welcome',          pose: 'waving',     tone: 'yellow' },
        { id: 'signup',   label: 'Sign up',          pose: 'happy',      tone: 'mint' },
        { id: 'connect',  label: 'Connect bot',      pose: 'thumbsup',   tone: 'peri' },
        { id: 'vault',    label: 'Add API keys',     pose: 'serious',    tone: 'yellow' },
        { id: 'mode',     label: 'Pick mode',        pose: 'serious',    tone: 'coral' },
        { id: 'home',     label: 'Dashboard',        pose: 'alert',      tone: 'yellow' },
      ],
    },
    'start-bot': {
      title: 'Start bot flow', subtitle: 'with LIVE-mode confirmation gate',
      nodes: [
        { id: 'home',     label: 'Dashboard',         pose: 'sleeping',  tone: 'cream' },
        { id: 'tap',      label: 'Tap START',         pose: 'alert',     tone: 'yellow' },
        { id: 'mode',     label: 'Mode?',             pose: 'questioning', tone: 'mint', branch: true },
        { id: 'paperok',  label: 'PAPER → start',     pose: 'thumbsup',  tone: 'mint' },
        { id: 'liveconf', label: 'LIVE confirm sheet', pose: 'serious',  tone: 'coral' },
        { id: 'typed',    label: 'Type "LIVE"',       pose: 'serious',   tone: 'coral' },
        { id: 'running',  label: 'Bot running',       pose: 'alert',     tone: 'yellow' },
      ],
    },
  }[kind];

  const Node = ({ n }) => (
    <div style={{
      width: 130, padding: 12, background: '#fff', borderRadius: 18,
      border: n.branch ? '3px solid ' + A.coral : A.ol2,
      boxShadow: A.shStickerHard(A.plum), textAlign: 'center', flexShrink: 0,
    }}>
      <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 6 }}>
        <MascotSlot size={70} pose={n.pose} tone={n.tone}/>
      </div>
      <div style={{ fontSize: 12, fontWeight: 800, lineHeight: 1.2 }}>{n.label}</div>
    </div>
  );

  const Arrow = ({ label }) => (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4, padding: '0 4px' }}>
      {label && <div style={{ fontSize: 10, fontWeight: 800, color: A.plumMid, letterSpacing: 0.4 }}>{label}</div>}
      <svg width="42" height="20" viewBox="0 0 42 20">
        <path d="M2 10 L34 10" stroke={A.plum} strokeWidth="2.5" strokeDasharray="4 4" strokeLinecap="round"/>
        <polygon points="34,4 42,10 34,16" fill={A.plum}/>
      </svg>
    </div>
  );

  if (kind === 'start-bot') {
    return (
      <div style={{ width: 1100, padding: 32, background: A.cream, fontFamily: A.font, color: A.plum }}>
        <SheetHeader title={flows.title} subtitle={flows.subtitle}/>
        <div style={{ display: 'flex', alignItems: 'center', gap: 0, flexWrap: 'wrap' }}>
          <Node n={flows.nodes[0]} />
          <Arrow />
          <Node n={flows.nodes[1]} />
          <Arrow />
          <Node n={flows.nodes[2]} />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center' }}>
              <Arrow label="PAPER / SHADOW" />
              <Node n={flows.nodes[3]} />
              <Arrow label="cycle" />
              <Node n={flows.nodes[6]} />
            </div>
            <div style={{ display: 'flex', alignItems: 'center' }}>
              <Arrow label="LIVE" />
              <Node n={flows.nodes[4]} />
              <Arrow label="hold 1.5s" />
              <Node n={flows.nodes[5]} />
              <Arrow />
              <div style={{ width: 130, padding: 12, background: A.pnlRedSoft, borderRadius: 18, border: '3px solid ' + A.pnlRed, textAlign: 'center', boxShadow: A.shStickerHard(A.plum) }}>
                <div style={{ fontSize: 12, fontWeight: 900, color: A.pnlRed }}>LIVE confirmed</div>
                <div style={{ fontSize: 10, color: A.plum, marginTop: 4 }}>Real orders enabled.</div>
              </div>
            </div>
          </div>
        </div>
        <div style={{ marginTop: 32, padding: 16, background: '#FFFCEB', border: A.ol2, borderRadius: 14, maxWidth: 800 }}>
          <div style={{ fontSize: 12, fontWeight: 800, color: A.plumMid, letterSpacing: 0.6 }}>GUARDRAILS</div>
          <ul style={{ fontSize: 13, color: A.plum, margin: '6px 0 0 18px', lineHeight: 1.6, padding: 0 }}>
            <li>LIVE start requires typed confirmation ("type LIVE") AND a slide-to-confirm.</li>
            <li>Kill switch is hold-to-activate (1.5s); a tap shows a hint, never trips.</li>
            <li>Any non-2xx from /start surfaces a serious-mode mascot, not a toast.</li>
          </ul>
        </div>
      </div>
    );
  }

  return (
    <div style={{ width: 1100, padding: 32, background: A.cream, fontFamily: A.font, color: A.plum }}>
      <SheetHeader title={flows.title} subtitle={flows.subtitle}/>
      <div style={{ display: 'flex', alignItems: 'center', gap: 0, flexWrap: 'wrap' }}>
        {flows.nodes.map((n, i) => (
          <React.Fragment key={n.id}>
            <Node n={n} />
            {i < flows.nodes.length - 1 && <Arrow />}
          </React.Fragment>
        ))}
      </div>
      <div style={{ marginTop: 32, padding: 16, background: '#FFFCEB', border: A.ol2, borderRadius: 14, maxWidth: 800, fontSize: 13, color: A.plum, lineHeight: 1.5 }}>
        Linear by design. The trust steps (connect bot → add keys → pick mode) precede the dashboard so the first time the user sees real numbers, the whole encryption + host story is already in their head.
      </div>
    </div>
  );
}

function SheetHeader({ title, subtitle }) {
  const A = window.AT;
  return (
    <div style={{ marginBottom: 28, paddingBottom: 18, borderBottom: '2px dashed rgba(45,31,71,0.15)' }}>
      <div style={{ fontSize: 32, fontWeight: 900, letterSpacing: -0.5 }}>{title}</div>
      {subtitle && <div style={{ fontSize: 14, color: A.plumMid, marginTop: 4 }}>{subtitle}</div>}
    </div>
  );
}

function SheetGroup({ title, children }) {
  const A = window.AT;
  return (
    <div style={{ marginBottom: 30 }}>
      <div style={{ fontSize: 12, fontWeight: 800, letterSpacing: 0.9, color: A.plumMid, marginBottom: 12 }}>{title.toUpperCase()}</div>
      {children}
    </div>
  );
}

Object.assign(window, { ComponentSheet, MascotSheet, PaletteSheet, TypeSheet, FlowDiagram, SheetHeader, SheetGroup });
