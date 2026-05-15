// Empty + error states. Each leads with mascot in a relevant pose.

function EmptyState({ kind, dark = false }) {
  const A = window.AT;
  const data = {
    'no-positions':  { pose: 'napping',    tone: 'cream',  title: 'No open positions',       body: 'Aribot will let you know when it opens one.', cta: 'Wake the bot' },
    'no-trades':     { pose: 'questioning',tone: 'mint',   title: 'No trades yet',           body: 'The bot needs at least one closed cycle to show history.', cta: null },
    'host-down':     { pose: 'panicked',   tone: 'cream',  title: 'Can\u2019t reach host',   body: 'aribot.alex.dev didn\u2019t respond. Check the URL, token, and that the server is up.', cta: 'Retry', prop: 'cable' },
    'kill-active':   { pose: 'serious',    tone: 'cream',  title: 'Kill switch is active',   body: 'New orders are blocked. Toggle it off in Settings to resume.', cta: 'Open settings', prop: 'flag' },
    'auth-error':    { pose: 'questioning',tone: 'yellow', title: 'That didn\u2019t work',   body: 'Wrong password, or the email isn\u2019t signed up yet.', cta: 'Try again' },
    'chart-empty':   { pose: 'alert',      tone: 'yellow', title: 'Reading the tape\u2026',  body: 'Not enough data points yet to draw a chart.', cta: null, prop: 'chart' },
  }[kind];
  return (
    <Screen tab={kind === 'no-positions' ? 'positions' : kind === 'no-trades' || kind === 'chart-empty' ? 'history' : kind === 'kill-active' ? 'home' : null} dark={dark}>
      <div style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', textAlign: 'center', padding: '0 24px', gap: 18 }}>
        <div style={{ position: 'relative', width: 200, height: 200 }}>
          <MascotSlot size={180} pose={data.pose} tone={data.tone} />
          {data.prop && <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}><MProp kind={data.prop}/></div>}
        </div>
        <div>
          <div style={{ fontSize: 24, fontWeight: 900, letterSpacing: -0.4 }}>{data.title}</div>
          <div style={{ fontSize: 14, color: dark ? A.darkMid : A.plumMid, marginTop: 6, maxWidth: 280, lineHeight: 1.45 }}>{data.body}</div>
        </div>
        {data.cta && <Btn kind="primary" size="md">{data.cta}</Btn>}
      </div>
    </Screen>
  );
}

Object.assign(window, { EmptyState });
