// Aribot — main canvas assembling every artboard.

function App() {
  return (
    <DesignCanvas minScale={0.1} maxScale={4}>
      {/* ─────────── LEAD: DASHBOARD ─────────── */}
      <DCSection id="lead" title="Dashboard — the lead screen" subtitle="Playful frame, serious numbers. Bot status, today's PnL, open positions.">
        <DCArtboard id="dash-running" label="Running · PAPER" width={402} height={874}>
          <IOSDevice><Dashboard status="running" mode="PAPER"/></IOSDevice>
        </DCArtboard>
        <DCArtboard id="dash-running-live" label="Running · LIVE" width={402} height={874}>
          <IOSDevice><Dashboard status="running" mode="LIVE"/></IOSDevice>
        </DCArtboard>
        <DCArtboard id="dash-stopped" label="Stopped" width={402} height={874}>
          <IOSDevice><Dashboard status="stopped" mode="PAPER"/></IOSDevice>
        </DCArtboard>
        <DCArtboard id="dash-error" label="Error" width={402} height={874}>
          <IOSDevice><Dashboard status="error" mode="SHADOW"/></IOSDevice>
        </DCArtboard>
        <DCArtboard id="dash-killed" label="Kill switch tripped" width={402} height={874}>
          <IOSDevice><Dashboard status="killed" mode="LIVE"/></IOSDevice>
        </DCArtboard>
        <DCArtboard id="dash-large-text" label="Dynamic type · XXL" width={402} height={874}>
          <IOSDevice><Dashboard status="running" mode="PAPER" dynamicType/></IOSDevice>
        </DCArtboard>
      </DCSection>

      {/* ─────────── ONBOARDING ─────────── */}
      <DCSection id="onb" title="Onboarding" subtitle="Welcome → Sign up → Connect bot → Vault → Pick mode → Dashboard">
        <DCArtboard id="splash" label="Splash" width={402} height={874}><IOSDevice><Splash/></IOSDevice></DCArtboard>
        <DCArtboard id="signup" label="Sign up" width={402} height={874}><IOSDevice><SignUp/></IOSDevice></DCArtboard>
        <DCArtboard id="signin" label="Sign in" width={402} height={874}><IOSDevice><SignIn/></IOSDevice></DCArtboard>
        <DCArtboard id="onb-a" label="Carousel · A" width={402} height={874}><IOSDevice><OnboardCard idx={0}/></IOSDevice></DCArtboard>
        <DCArtboard id="onb-b" label="Carousel · B" width={402} height={874}><IOSDevice><OnboardCard idx={1}/></IOSDevice></DCArtboard>
        <DCArtboard id="onb-c" label="Carousel · C" width={402} height={874}><IOSDevice><OnboardCard idx={2}/></IOSDevice></DCArtboard>
        <DCArtboard id="bot-idle" label="Bot setup · idle" width={402} height={874}><IOSDevice><BotSetup state="idle"/></IOSDevice></DCArtboard>
        <DCArtboard id="bot-ok" label="Bot setup · ✓" width={402} height={874}><IOSDevice><BotSetup state="success"/></IOSDevice></DCArtboard>
        <DCArtboard id="bot-err" label="Bot setup · error" width={402} height={874}><IOSDevice><BotSetup state="error"/></IOSDevice></DCArtboard>
        <DCArtboard id="vault" label="API key vault" width={402} height={874}><IOSDevice><ApiVault/></IOSDevice></DCArtboard>
      </DCSection>

      {/* ─────────── MAIN APP ─────────── */}
      <DCSection id="app" title="Main app" subtitle="Positions · History · Settings + LIVE-mode gate">
        <DCArtboard id="positions" label="Positions" width={402} height={874}><IOSDevice><Positions/></IOSDevice></DCArtboard>
        <DCArtboard id="history-trades" label="History · trades" width={402} height={874}><IOSDevice><History view="trades"/></IOSDevice></DCArtboard>
        <DCArtboard id="history-equity" label="History · equity" width={402} height={874}><IOSDevice><History view="equity"/></IOSDevice></DCArtboard>
        <DCArtboard id="settings" label="Settings" width={402} height={874}><IOSDevice><Settings/></IOSDevice></DCArtboard>
        <DCArtboard id="live-confirm" label="LIVE confirm sheet" width={402} height={874}>
          <div style={{ position: 'relative', width: '100%', height: '100%' }}>
            <IOSDevice><Dashboard status="stopped" mode="LIVE"/></IOSDevice>
            <div style={{ position: 'absolute', inset: 0 }}><IOSDevice><LiveConfirmSheet/></IOSDevice></div>
          </div>
        </DCArtboard>
      </DCSection>

      {/* ─────────── EMPTY + ERROR STATES ─────────── */}
      <DCSection id="states" title="Empty + error states" subtitle="The mascot does the emotional lifting — every state has a pose.">
        <DCArtboard id="empty-pos" label="No positions" width={402} height={874}><IOSDevice><EmptyState kind="no-positions"/></IOSDevice></DCArtboard>
        <DCArtboard id="empty-trades" label="No trades" width={402} height={874}><IOSDevice><EmptyState kind="no-trades"/></IOSDevice></DCArtboard>
        <DCArtboard id="err-host" label="Host unreachable" width={402} height={874}><IOSDevice><EmptyState kind="host-down"/></IOSDevice></DCArtboard>
        <DCArtboard id="err-kill" label="Kill switch active" width={402} height={874}><IOSDevice><EmptyState kind="kill-active"/></IOSDevice></DCArtboard>
        <DCArtboard id="err-auth" label="Auth error" width={402} height={874}><IOSDevice><EmptyState kind="auth-error"/></IOSDevice></DCArtboard>
        <DCArtboard id="empty-chart" label="Chart loading" width={402} height={874}><IOSDevice><EmptyState kind="chart-empty"/></IOSDevice></DCArtboard>
      </DCSection>

      {/* ─────────── DARK MODE ─────────── */}
      <DCSection id="dark" title="Dark mode" subtitle="Warm dark — never pure black. Cream becomes plum-violet; numbers keep their PnL color rules.">
        <DCArtboard id="dark-dash" label="Dashboard · dark" width={402} height={874}><IOSDevice dark><Dashboard status="running" mode="PAPER" dark/></IOSDevice></DCArtboard>
        <DCArtboard id="dark-pos" label="Positions · dark" width={402} height={874}><IOSDevice dark><Positions dark/></IOSDevice></DCArtboard>
        <DCArtboard id="dark-hist" label="History · dark" width={402} height={874}><IOSDevice dark><History view="equity" dark/></IOSDevice></DCArtboard>
      </DCSection>

      {/* ─────────── TRUST MOMENT ─────────── */}
      <DCSection id="trust" title="Trust moment · annotated" subtitle="The screen where the cartoon style most risks undermining trust. Here's how it earns it back.">
        <DCArtboard id="trust-annot" label="API vault · annotated" width={760} height={920}>
          <div style={{ background: window.AT.cream, width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 40, boxSizing: 'border-box' }}>
            <div style={{ position: 'relative' }}>
              <IOSDevice><ApiVault annotated/></IOSDevice>
            </div>
          </div>
        </DCArtboard>
      </DCSection>

      {/* ─────────── DESIGN SYSTEM SHEETS ─────────── */}
      <DCSection id="ds-mascot" title="Mascot sheet" subtitle="8+ poses · the swappable slot · accessory props">
        <DCArtboard id="mascot-sheet" label="Expressions + slot" width={920} height={1040}><MascotSheet/></DCArtboard>
      </DCSection>

      <DCSection id="ds-comp" title="Components" subtitle="Buttons · inputs · pills · cards · rows · tab bar · controls">
        <DCArtboard id="components" label="Component sheet" width={920} height={1200}><ComponentSheet/></DCArtboard>
      </DCSection>

      <DCSection id="ds-color" title="Color palette" subtitle="Light · dark · the reserved-for-PnL rule">
        <DCArtboard id="palette" label="Palette + usage rules" width={920} height={1280}><PaletteSheet/></DCArtboard>
      </DCSection>

      <DCSection id="ds-type" title="Type scale" subtitle="Every size used in the app · tabular figures on every number">
        <DCArtboard id="type" label="Type scale" width={920} height={960}><TypeSheet/></DCArtboard>
      </DCSection>

      <DCSection id="flow-onb" title="Flow · onboarding" subtitle="Welcome → Dashboard">
        <DCArtboard id="flow-onboarding" label="Onboarding flow" width={1100} height={420}><FlowDiagram kind="onboarding"/></DCArtboard>
      </DCSection>

      <DCSection id="flow-start" title="Flow · start bot" subtitle="With LIVE-mode confirmation gate">
        <DCArtboard id="flow-start-bot" label="Start-bot flow" width={1100} height={580}><FlowDiagram kind="start-bot"/></DCArtboard>
      </DCSection>
    </DesignCanvas>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App/>);
