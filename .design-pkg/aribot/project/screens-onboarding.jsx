// Onboarding screens — splash, signup, signin, carousel, bot setup, vault.

function Splash() {
  const A = window.AT;
  return (
    <Screen hideHomeIndicator>
      <div style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 28, padding: '0 32px' }}>
        <div style={{ position: 'relative' }}>
          {/* Decorative blobs */}
          <div style={{ position: 'absolute', width: 30, height: 30, top: -10, left: -20, borderRadius: '50%', background: A.coral, border: A.ol2, transform: 'rotate(-10deg)' }}/>
          <div style={{ position: 'absolute', width: 22, height: 22, top: 30, right: -30, borderRadius: '50%', background: A.peri, border: A.ol2 }}/>
          <div style={{ position: 'absolute', width: 18, height: 18, bottom: 10, right: -10, borderRadius: 6, background: A.mint, border: A.ol2, transform: 'rotate(15deg)' }}/>
          <MascotSlot size={200} pose="waving" tone="yellow" />
        </div>
        <div style={{ textAlign: 'center' }}>
          <h1 style={{ margin: 0, fontSize: 56, fontWeight: 900, letterSpacing: -2, color: A.plum, lineHeight: 1 }}>
            Ari<span style={{ color: A.coralDeep }}>bot</span>
          </h1>
          <div style={{ fontSize: 16, color: A.plumMid, marginTop: 10, fontWeight: 600 }}>
            Your friendly trading bot — on your terms.
          </div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, width: '100%' }}>
          <Btn kind="primary" size="lg" style={{ width: '100%' }}>Create account</Btn>
          <Btn kind="soft" size="lg" style={{ width: '100%' }}>I already have one</Btn>
        </div>
        <div style={{ fontSize: 11, color: A.plumMid, textAlign: 'center' }}>
          BYO server · keys encrypted on-device · v1.0
        </div>
      </div>
    </Screen>
  );
}

function SignUp() {
  const A = window.AT;
  return (
    <Screen hideHomeIndicator>
      <div style={{ padding: '0 6px' }}>
        <button style={{ background: '#fff', border: A.ol2, borderRadius: A.rPill, width: 44, height: 44, fontSize: 18, fontWeight: 800, color: A.plum, marginBottom: 4, boxShadow: A.shStickerHard(A.plum) }}>‹</button>
        <div style={{ display: 'flex', justifyContent: 'center', margin: '8px 0 16px' }}>
          <MascotSlot size={130} pose="waving" tone="mint" />
        </div>
        <h1 style={{ fontSize: 30, fontWeight: 900, letterSpacing: -0.6, margin: 0, textAlign: 'center' }}>Make an account</h1>
        <div style={{ fontSize: 14, color: A.plumMid, textAlign: 'center', margin: '4px 0 22px' }}>
          So we can sync your settings across devices.
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <Input label="EMAIL" value="alex@trader.co" />
          <Input label="PASSWORD" secure value="hunter2hunter2" hint="At least 12 characters." />
          <Input label="CONFIRM PASSWORD" secure value="hunter2hunter2" />
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, marginTop: 4 }}>
            <div style={{ width: 24, height: 24, borderRadius: 7, background: A.coral, border: A.ol2, color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, marginTop: 2 }}>
              <Icon name="check" size={16} color="#fff" />
            </div>
            <div style={{ fontSize: 12, color: A.plumMid, lineHeight: 1.45 }}>
              I understand that my Bybit keys will be <b style={{ color: A.plum }}>encrypted on this device</b>. Aribot never sees them.
            </div>
          </div>
          <Btn kind="primary" size="lg" style={{ width: '100%', marginTop: 6 }}>Create account →</Btn>
          <div style={{ fontSize: 13, color: A.plumMid, textAlign: 'center', marginTop: 6 }}>
            Or <span style={{ color: A.coralDeep, fontWeight: 800 }}>send me a magic link</span>
          </div>
        </div>
      </div>
    </Screen>
  );
}

function SignIn() {
  const A = window.AT;
  return (
    <Screen hideHomeIndicator>
      <div style={{ padding: '0 6px' }}>
        <button style={{ background: '#fff', border: A.ol2, borderRadius: A.rPill, width: 44, height: 44, fontSize: 18, fontWeight: 800, color: A.plum, marginBottom: 4, boxShadow: A.shStickerHard(A.plum) }}>‹</button>
        {/* Peeking mascot */}
        <div style={{ display: 'flex', justifyContent: 'center', margin: '8px 0 16px', position: 'relative', height: 120 }}>
          <div style={{ position: 'absolute', top: 30, overflow: 'hidden', width: 140, height: 80, borderRadius: '50% 50% 0 0' }}>
            <div style={{ marginTop: 0 }}>
              <MascotSlot size={140} pose="wink" tone="peri" />
            </div>
          </div>
          {/* "fence" line they peek over */}
          <div style={{ position: 'absolute', bottom: 0, left: 60, right: 60, height: 8, background: A.plum, borderRadius: 4 }}/>
        </div>
        <h1 style={{ fontSize: 30, fontWeight: 900, letterSpacing: -0.6, margin: 0, textAlign: 'center' }}>Welcome back</h1>
        <div style={{ fontSize: 14, color: A.plumMid, textAlign: 'center', margin: '4px 0 22px' }}>
          Quick check before you trade.
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <Input label="EMAIL" value="alex@trader.co" />
          <Input label="PASSWORD" secure value="hunter2hunter2" />
          <Btn kind="primary" size="lg" style={{ width: '100%', marginTop: 6 }}>Sign in</Btn>
          <Btn kind="soft" size="lg" style={{ width: '100%' }}>Send me a magic link</Btn>
          <div style={{ fontSize: 13, color: A.plumMid, textAlign: 'center', marginTop: 6 }}>
            Forgot your password?
          </div>
        </div>
      </div>
    </Screen>
  );
}

function OnboardCard({ idx, total = 3 }) {
  const A = window.AT;
  const data = [
    {
      pose: 'thumbsup', tone: 'mint', title: 'Connect your bot',
      body: 'Aribot runs on your own VPS. Paste its URL + a bearer token and we\u2019ll do a handshake.',
      art: (
        <svg width="280" height="120" viewBox="0 0 280 120">
          <rect x="10" y="30" width="80" height="60" rx="14" fill={A.peri} stroke={A.plum} strokeWidth="3" />
          <text x="50" y="64" textAnchor="middle" fontSize="11" fontWeight="800" fill="#fff">YOUR SERVER</text>
          <text x="50" y="78" textAnchor="middle" fontSize="9" fill="#fff">aribot.py</text>
          <path d="M95 60 Q140 30 185 60" fill="none" stroke={A.plum} strokeWidth="3" strokeDasharray="6 4" />
          <polygon points="178,55 192,60 178,65" fill={A.plum} />
          <rect x="190" y="30" width="80" height="60" rx="14" fill={A.coral} stroke={A.plum} strokeWidth="3" />
          <text x="230" y="64" textAnchor="middle" fontSize="11" fontWeight="800" fill="#fff">ARIBOT iOS</text>
          <text x="230" y="78" textAnchor="middle" fontSize="9" fill="#fff">this app</text>
        </svg>
      ),
    },
    {
      pose: 'serious', tone: 'yellow', title: 'Add your Bybit keys',
      body: 'Keys are encrypted on this device before they go anywhere. Even we can\u2019t read them.',
      art: (
        <svg width="200" height="120" viewBox="0 0 200 120">
          <rect x="40" y="40" width="120" height="70" rx="14" fill={A.yellow} stroke={A.plum} strokeWidth="3.5" />
          <path d="M70 40 V28 a30 30 0 0 1 60 0 V40" fill="none" stroke={A.plum} strokeWidth="3.5" strokeLinecap="round" />
          <circle cx="100" cy="72" r="10" fill={A.plum} />
          <rect x="96" y="78" width="8" height="16" rx="2" fill={A.plum} />
          <text x="100" y="106" textAnchor="middle" fontSize="9" fontWeight="800" fill={A.plum}>SEALED-BOX</text>
        </svg>
      ),
    },
    {
      pose: 'serious', tone: 'coral', title: 'Pick a mode',
      body: 'Start safe. Move to live only when you\u2019re comfy.',
      art: (
        <div style={{ display: 'flex', gap: 8, marginTop: 20 }}>
          {['PAPER','SHADOW','LIVE'].map((m,i) => (
            <div key={m} style={{
              padding: '14px 10px', borderRadius: 16, border: A.ol2,
              background: ['#fff', A.yellow, A.pnlRedSoft][i],
              flex: 1, textAlign: 'center', boxShadow: A.shStickerHard(A.plum),
            }}>
              <div style={{ fontSize: 14, fontWeight: 900, letterSpacing: 0.5 }}>{m}</div>
              <div style={{ fontSize: 10, color: A.plumMid, marginTop: 4, lineHeight: 1.3 }}>
                {['Sim only.', 'Dry-run real auth.', 'Real money.'][i]}
              </div>
            </div>
          ))}
        </div>
      ),
    },
  ][idx];

  return (
    <Screen hideHomeIndicator>
      <div style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: '0 4px' }}>
        <div style={{ display: 'flex', justifyContent: 'flex-end', padding: '4px 0' }}>
          <span style={{ fontSize: 14, fontWeight: 800, color: A.plumMid }}>Skip</span>
        </div>
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 18, textAlign: 'center' }}>
          <MascotSlot size={150} pose={data.pose} tone={data.tone} />
          <div style={{ minHeight: 130, display: 'flex', alignItems: 'center' }}>{data.art}</div>
          <h2 style={{ fontSize: 28, fontWeight: 900, letterSpacing: -0.4, margin: '4px 0 0' }}>{data.title}</h2>
          <p style={{ fontSize: 16, color: A.plumMid, margin: 0, lineHeight: 1.45, padding: '0 16px' }}>{data.body}</p>
        </div>
        {/* Dots */}
        <div style={{ display: 'flex', justifyContent: 'center', gap: 8, padding: '14px 0' }}>
          {Array.from({ length: total }).map((_, i) => (
            <div key={i} style={{
              width: i === idx ? 26 : 8, height: 8, borderRadius: 4,
              background: i === idx ? A.coral : A.creamDeep, border: A.ol2,
            }}/>
          ))}
        </div>
        <Btn kind="primary" size="lg" style={{ width: '100%', marginBottom: 18 }}>
          {idx === total - 1 ? 'Let\u2019s go' : 'Next'} →
        </Btn>
      </div>
    </Screen>
  );
}

function BotSetup({ state = 'idle' }) {
  const A = window.AT;
  return (
    <Screen title="Connect bot" hideHomeIndicator>
      <div style={{ padding: '4px 0 20px', display: 'flex', alignItems: 'center', gap: 14 }}>
        <MascotSlot size={70} pose={state === 'success' ? 'thumbsup' : state === 'error' ? 'questioning' : 'alert'} tone="peri" />
        <div style={{ flex: 1, fontSize: 14, color: A.plumMid, lineHeight: 1.4 }}>
          Point the app at your Aribot server. It must be reachable over HTTPS.
        </div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <Input label="HOST URL" value="https://aribot.alex.dev" icon={<Icon name="server" size={18}/>} monospace />
        <Input label="BEARER TOKEN" value="ari_pat_8c1f...3920" secure monospace />

        {state === 'success' && (
          <Card color={A.pnlGreenSoft} padding={14}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <div style={{ width: 32, height: 32, borderRadius: '50%', background: A.pnlGreen, border: A.ol2, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff' }}>
                <Icon name="check" size={20} color="#fff"/>
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 800, fontSize: 14 }}>Connected · v1.4.2</div>
                <div style={{ fontSize: 12, color: A.plumMid }}>Mode: PAPER · uptime 2d 4h</div>
              </div>
            </div>
          </Card>
        )}
        {state === 'error' && (
          <Card color={A.pnlRedSoft} padding={14}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <div style={{ width: 32, height: 32, borderRadius: '50%', background: A.pnlRed, border: A.ol2, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff' }}>
                <Icon name="x" size={18} color="#fff"/>
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 800, fontSize: 14 }}>Couldn't reach host</div>
                <div style={{ fontSize: 12, color: A.plumMid }}>ECONNREFUSED · Check the URL and that /status is up.</div>
              </div>
            </div>
          </Card>
        )}

        <Btn kind="primary" size="lg" style={{ width: '100%', marginTop: 6 }} icon={<Icon name="plug" size={20}/>}>
          {state === 'success' ? 'Continue' : 'Test connection'}
        </Btn>
        <Btn kind="ghost" size="md" style={{ width: '100%' }}>How do I find these?</Btn>
      </div>
    </Screen>
  );
}

function ApiVault({ annotated = false }) {
  const A = window.AT;
  return (
    <Screen title="Bybit keys" hideHomeIndicator>
      <div style={{ padding: '0 0 16px', display: 'flex', alignItems: 'center', gap: 14, position: 'relative' }}>
        <MascotSlot size={80} pose="serious" tone="yellow" prop={<MProp kind="vault"/>} />
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 900, fontSize: 17, letterSpacing: -0.2 }}>Encrypted on this device.</div>
          <div style={{ fontSize: 13, color: A.plumMid, lineHeight: 1.4 }}>
            We seal with a key only your phone holds. Even we can\u2019t read these.
          </div>
        </div>
      </div>

      {/* trust strip */}
      <Card color={A.peri} padding={14} hard style={{ marginBottom: 14, color: '#fff', border: A.ol2 }}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
          <div style={{ width: 28, height: 28, borderRadius: '50%', background: '#fff', border: A.ol2, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
            <Icon name="lock" size={16} color={A.plum} />
          </div>
          <div style={{ fontSize: 13, lineHeight: 1.5, fontWeight: 600 }}>
            <b style={{ color: '#fff' }}>Sealed-box</b> ciphertext is uploaded to our server so it can sync.
            Your private key lives in iOS Keychain — never leaves the phone.
          </div>
        </div>
      </Card>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 12, position: 'relative' }}>
        <div style={{
          fontSize: 11, fontWeight: 800, letterSpacing: 0.8, color: A.plumMid,
          margin: '0 0 -4px 4px',
        }}>READ-ONLY KEY · for status & positions</div>
        <Input label="READ API KEY" value="K-rO8X-1f2A...3920" secure monospace />
        <Input label="READ SECRET" value="rs_9e7c41...8b" secure monospace />
        <div style={{
          fontSize: 11, fontWeight: 800, letterSpacing: 0.8, color: A.plumMid,
          margin: '10px 0 -4px 4px',
        }}>TRADE KEY · scoped to USDT perps</div>
        <Input label="TRADE API KEY" value="K-tR3K-9c2B...d41a" secure monospace />
        <Input label="TRADE SECRET" value="ts_b41a72...4f" secure monospace />

        <Btn kind="primary" size="lg" style={{ width: '100%', marginTop: 8 }} icon={<Icon name="lock" size={20}/>}>
          Encrypt &amp; save
        </Btn>

        {annotated && <TrustAnnotations />}
      </div>
    </Screen>
  );
}

// Callouts overlay for the annotated "trust moment" deliverable.
function TrustAnnotations() {
  const A = window.AT;
  const C = ({ top, left, text, anchor }) => (
    <div style={{ position: 'absolute', top, left, width: 170, zIndex: 50 }}>
      <div style={{ background: '#FFFCEB', border: A.ol2, borderRadius: 14, padding: '8px 10px', fontSize: 11, lineHeight: 1.4, color: A.plum, fontWeight: 600, boxShadow: A.shStickerHard(A.plum) }}>{text}</div>
      <svg width="100" height="60" style={{ position: 'absolute', top: 10, left: anchor === 'right' ? -90 : 170, pointerEvents: 'none' }}>
        <path d={anchor === 'right' ? 'M 100 10 Q 60 20 10 30' : 'M 0 10 Q 50 20 90 30'} fill="none" stroke={A.coralDeep} strokeWidth="2" strokeDasharray="3 3" strokeLinecap="round"/>
      </svg>
    </div>
  );
  return (
    <>
      <C top={-460} left={-150} text="Eye toggle never logs key — show is local state only." anchor="left"/>
      <C top={-370} left={380} text="Monospace = these are NOT human strings. Reduces transcription errors." anchor="right"/>
      <C top={-200} left={-160} text="Section grouped by SCOPE (read vs trade) so user feels the principle of least privilege." anchor="left"/>
      <C top={-90} left={380} text="The button SAYS 'Encrypt'. The verb leads — saving is secondary." anchor="right"/>
    </>
  );
}

Object.assign(window, { Splash, SignUp, SignIn, OnboardCard, BotSetup, ApiVault });
