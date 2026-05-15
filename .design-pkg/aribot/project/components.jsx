// Aribot UI components — buttons, inputs, pills, cards, position rows, tab bar.
// All shapes use sticker shadows + plum outlines; numbers always tabular.

const A = window.AT;

// ─────────── Buttons ───────────
function Btn({ kind = 'primary', size = 'lg', icon, children, style, dark = false, ...rest }) {
  const pads = size === 'sm' ? '10px 18px' : size === 'md' ? '14px 22px' : '18px 28px';
  const fontSize = size === 'sm' ? 15 : size === 'md' ? 17 : 19;
  const radius = size === 'sm' ? A.rM : A.rL;

  const variants = {
    primary:    { bg: A.coral,   fg: '#fff',    hard: A.plum, ol: A.ol3 },
    secondary:  { bg: A.yellow,  fg: A.plum,    hard: A.plum, ol: A.ol3 },
    soft:       { bg: dark ? A.darkCard : '#fff', fg: dark ? A.darkText : A.plum, hard: A.plum, ol: A.ol2 },
    mint:       { bg: A.mint,    fg: A.plum,    hard: A.plum, ol: A.ol3 },
    danger:     { bg: A.pnlRed,  fg: '#fff',    hard: A.plum, ol: A.ol3 },
    ghost:      { bg: 'transparent', fg: dark ? A.darkText : A.plum, hard: 'transparent', ol: '2px dashed ' + (dark ? A.darkMid : A.plumMid) },
  };
  const v = variants[kind];

  return (
    <button {...rest} style={{
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 10,
      padding: pads, fontSize, fontWeight: 800, letterSpacing: 0.2,
      fontFamily: A.font, color: v.fg, background: v.bg,
      border: v.ol, borderRadius: radius,
      boxShadow: kind === 'ghost' ? 'none' : `${A.shStickerHard(v.hard)}, ${A.shInset}`,
      cursor: 'pointer', position: 'relative',
      ...style,
    }}>
      {icon}
      {children}
    </button>
  );
}

// ─────────── Status pill (text + icon + color, never color alone) ───────────
function StatusPill({ status = 'running', mode, style }) {
  const cfg = {
    running:  { bg: A.mint,   fg: A.plum, label: 'RUNNING', dot: A.pnlGreen, icon: '▶' },
    stopped:  { bg: A.creamDeep, fg: A.plum, label: 'STOPPED', dot: A.plumMid, icon: '■' },
    error:    { bg: A.pnlRedSoft, fg: A.plum, label: 'ERROR', dot: A.pnlRed, icon: '!' },
    killed:   { bg: A.pnlRedSoft, fg: A.plum, label: 'KILLED', dot: A.pnlRed, icon: '⚑' },
  }[status];
  return (
    <div style={{
      display: 'inline-flex', alignItems: 'center', gap: 8,
      padding: '8px 14px 8px 10px', background: cfg.bg, color: cfg.fg,
      border: A.ol2, borderRadius: A.rPill, fontWeight: 800, fontSize: 13,
      letterSpacing: 0.6, fontFamily: A.font,
      boxShadow: A.shStickerHard(A.plum),
      ...style,
    }}>
      <span style={{
        width: 18, height: 18, borderRadius: '50%', background: cfg.dot,
        border: '2px solid ' + A.plum, color: '#fff', fontSize: 10,
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      }}>{cfg.icon}</span>
      {cfg.label}
      {mode && (
        <span style={{
          padding: '2px 8px', borderRadius: A.rPill, marginLeft: 6,
          fontSize: 11, background: A.plum, color: A.cream,
        }}>{mode}</span>
      )}
    </div>
  );
}

// ─────────── Mode chip ───────────
function ModeChip({ mode, active, onClick }) {
  const colors = {
    PAPER:  { bg: A.peri,   fg: '#fff' },
    SHADOW: { bg: A.yellow, fg: A.plum },
    LIVE:   { bg: A.pnlRed, fg: '#fff' },
  }[mode];
  return (
    <button onClick={onClick} style={{
      padding: '6px 12px', borderRadius: A.rPill, fontWeight: 800, fontSize: 12,
      fontFamily: A.font, letterSpacing: 0.6, color: colors.fg,
      background: active ? colors.bg : '#fff',
      border: A.ol2, cursor: 'pointer',
      boxShadow: active ? A.shStickerHard(A.plum) : 'none',
    }}>{mode}</button>
  );
}

// ─────────── Side chip (LONG/SHORT) ───────────
function SideChip({ side }) {
  const isLong = side === 'LONG';
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '3px 9px', borderRadius: A.rS, fontSize: 11, fontWeight: 800,
      letterSpacing: 0.5, fontFamily: A.font,
      background: isLong ? A.pnlGreenSoft : A.pnlRedSoft,
      color: isLong ? A.pnlGreen : A.pnlRed,
      border: '1.5px solid ' + (isLong ? A.pnlGreen : A.pnlRed),
    }}>
      <span>{isLong ? '↑' : '↓'}</span>{side}
    </span>
  );
}

// ─────────── Input ───────────
function Input({ label, value, placeholder, hint, secure, icon, error, monospace, dark = false, style }) {
  const [show, setShow] = React.useState(!secure);
  const v = secure && !show ? '••••••••••••••••' : value;
  return (
    <label style={{ display: 'block', ...style }}>
      {label && (
        <div style={{
          fontSize: 13, fontWeight: 700, color: dark ? A.darkMid : A.plumMid,
          letterSpacing: 0.4, textTransform: 'uppercase',
          marginBottom: 8, fontFamily: A.font,
        }}>{label}</div>
      )}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10,
        padding: '14px 16px',
        background: dark ? A.darkCard : '#fff',
        border: error ? '3px solid ' + A.pnlRed : (dark ? '2px solid ' + A.darkCard : A.ol2),
        borderRadius: A.rL,
        boxShadow: dark ? 'inset 0 2px 0 rgba(255,255,255,0.04)' : 'inset 0 2px 0 rgba(45,31,71,0.05)',
      }}>
        {icon && <span style={{ color: A.plumMid }}>{icon}</span>}
        <div style={{
          flex: 1, fontFamily: monospace ? 'ui-monospace, "SF Mono", Menlo, monospace' : A.font,
          fontSize: 16, fontWeight: 600, color: dark ? A.darkText : A.plum,
          letterSpacing: monospace ? 0.5 : 0,
        }}>{v || <span style={{ color: dark ? '#7A6A95' : A.plumSoft, fontWeight: 500 }}>{placeholder}</span>}</div>
        {secure && (
          <button onClick={() => setShow(s => !s)} style={{
            background: 'transparent', border: 'none', cursor: 'pointer',
            color: A.plumMid, fontSize: 18, padding: 4,
          }}>{show ? '◉' : '◎'}</button>
        )}
      </div>
      {hint && <div style={{
        fontSize: 12, color: error ? A.pnlRed : (dark ? A.darkMid : A.plumMid),
        marginTop: 6, fontFamily: A.font,
      }}>{hint}</div>}
    </label>
  );
}

// ─────────── Number — tabular, color-coded for PnL ───────────
function Money({ value, size = 40, weight = 800, prefix = '$', signed = true, dark = false }) {
  const v = Number(value);
  const isPos = v >= 0;
  const color = signed
    ? (isPos ? A.pnlGreen : A.pnlRed)
    : (dark ? A.darkText : A.plum);
  const sign = signed ? (isPos ? '+' : '−') : '';
  const abs = Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return (
    <span style={{
      fontFamily: A.num, fontSize: size, fontWeight: weight,
      color, fontVariantNumeric: 'tabular-nums', letterSpacing: -0.5,
    }}>{sign}{prefix}{abs}</span>
  );
}

// ─────────── Card ───────────
function Card({ children, color = '#fff', outlined = true, hard = true, padding = 20, radius = A.rL, dark = false, style }) {
  return (
    <div style={{
      background: color === '#fff' && dark ? A.darkPaper : color,
      border: outlined ? (dark ? '2px solid rgba(255,255,255,0.06)' : A.ol2) : 'none',
      borderRadius: radius, padding,
      boxShadow: outlined
        ? (hard ? `${A.shStickerHard(dark ? '#000' : A.plum)}, ${A.shStickerSoft}` : A.shStickerSoft)
        : A.shStickerSoft,
      ...style,
    }}>{children}</div>
  );
}

// ─────────── Sparkline (svg) ───────────
function Sparkline({ data, color, width = 240, height = 56, dark = false }) {
  const min = Math.min(...data), max = Math.max(...data);
  const span = (max - min) || 1;
  const stepX = width / (data.length - 1);
  const pts = data.map((v, i) => `${i * stepX},${height - 6 - ((v - min) / span) * (height - 14)}`).join(' ');
  const c = color || (data[data.length - 1] >= data[0] ? A.pnlGreen : A.pnlRed);
  const last = pts.split(' ').slice(-1)[0].split(',').map(Number);
  const areaPath = `M0,${height} L${pts.replace(/,/g, ',').split(' ').join(' L')} L${width},${height} Z`;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      <path d={areaPath} fill={c} opacity="0.12" />
      <polyline points={pts} fill="none" stroke={c} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={last[0]} cy={last[1]} r="5" fill={c} stroke={dark ? A.darkBg : A.cream} strokeWidth="2.5" />
    </svg>
  );
}

// ─────────── Position row ───────────
function PositionRow({ p, dense = false, dark = false }) {
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: '1fr auto', gap: 6,
      padding: dense ? '12px 0' : '14px 0',
      borderBottom: '1.5px dashed ' + (dark ? 'rgba(255,255,255,0.08)' : 'rgba(45,31,71,0.12)'),
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{
          fontFamily: A.num, fontSize: 17, fontWeight: 800,
          color: dark ? A.darkText : A.plum, letterSpacing: -0.2,
        }}>{p.symbol}</span>
        <SideChip side={p.side} />
      </div>
      <div style={{ textAlign: 'right' }}>
        <Money value={p.pnl} size={17} dark={dark} />
      </div>
      <div style={{
        fontSize: 12, color: dark ? A.darkMid : A.plumMid,
        fontFamily: A.num, fontVariantNumeric: 'tabular-nums',
      }}>{p.size} @ ${p.entry}</div>
      <div style={{
        fontSize: 12, color: dark ? A.darkMid : A.plumMid, textAlign: 'right',
        fontFamily: A.num, fontVariantNumeric: 'tabular-nums',
      }}>mark ${p.mark}</div>
    </div>
  );
}

// ─────────── Tab bar ───────────
function TabBar({ active = 'home', dark = false }) {
  const items = [
    { id: 'home',      label: 'Home',      icon: <Icon name="home"/> },
    { id: 'positions', label: 'Positions', icon: <Icon name="positions"/> },
    { id: 'history',   label: 'History',   icon: <Icon name="history"/> },
    { id: 'settings',  label: 'Settings',  icon: <Icon name="settings"/> },
  ];
  return (
    <div style={{
      position: 'absolute', left: 12, right: 12, bottom: 18,
      background: dark ? A.darkPaper : '#fff',
      border: dark ? '2px solid rgba(255,255,255,0.06)' : A.ol3,
      borderRadius: A.rXL, padding: '10px 8px',
      display: 'flex', justifyContent: 'space-around',
      boxShadow: A.shDual(dark ? '#000' : A.plum), zIndex: 5,
    }}>
      {items.map(it => {
        const on = it.id === active;
        return (
          <div key={it.id} style={{
            display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 3,
            padding: '6px 12px', borderRadius: A.rM,
            background: on ? A.coral : 'transparent',
            border: on ? '2px solid ' + A.plum : '2px solid transparent',
            color: on ? '#fff' : (dark ? A.darkMid : A.plumMid),
            fontSize: 11, fontWeight: 800, letterSpacing: 0.3,
            fontFamily: A.font,
            boxShadow: on ? '0 3px 0 0 ' + A.plum : 'none',
          }}>
            {it.icon}
            {it.label}
          </div>
        );
      })}
    </div>
  );
}

// ─────────── Icons (chunky, no library) ───────────
function Icon({ name, size = 22, color = 'currentColor' }) {
  const s = { width: size, height: size, fill: 'none', stroke: color, strokeWidth: 2.5, strokeLinecap: 'round', strokeLinejoin: 'round' };
  const paths = {
    home: <path d="M3 11 L12 3 L21 11 V20 a1 1 0 0 1-1 1 h-5 v-7 h-4 v7 H4 a1 1 0 0 1-1 -1 Z" />,
    positions: <g><rect x="3" y="4" width="18" height="6" rx="2"/><rect x="3" y="14" width="13" height="6" rx="2"/></g>,
    history: <g><circle cx="12" cy="12" r="9"/><path d="M12 7 v5 l3 2"/></g>,
    settings: <g><circle cx="12" cy="12" r="3"/><path d="M19 12 a7 7 0 0 0 -.2 -1.7 l2-1.5 -2-3.4 -2.3 1 a7 7 0 0 0 -2.9 -1.7 L13 2 h-2 l-.6 2.7 a7 7 0 0 0 -2.9 1.7 l-2.3-1 -2 3.4 2 1.5 A7 7 0 0 0 5 12 l-2 1.5 2 3.4 2.3-1 a7 7 0 0 0 2.9 1.7 L11 22 h2 l.6-2.4 a7 7 0 0 0 2.9-1.7 l2.3 1 2-3.4 -2-1.5z" strokeLinejoin="round"/></g>,
    lock: <g><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11 V7 a4 4 0 0 1 8 0 v4"/></g>,
    check: <path d="M5 12 l5 5 L20 7"/>,
    x: <path d="M6 6 l12 12 M18 6 l-12 12"/>,
    server: <g><rect x="4" y="3" width="16" height="7" rx="2"/><rect x="4" y="13" width="16" height="7" rx="2"/><circle cx="8" cy="6.5" r="0.8" fill={color}/><circle cx="8" cy="16.5" r="0.8" fill={color}/></g>,
    plug: <g><path d="M9 4 V8 M15 4 V8"/><path d="M6 8 h12 v4 a4 4 0 0 1-4 4 h-4 a4 4 0 0 1-4 -4 z"/><path d="M12 16 v4"/></g>,
    bolt: <path d="M13 2 L5 14 h6 l-2 8 8-12 h-6 l2-8z" strokeLinejoin="round"/>,
    refresh: <g><path d="M3 12 a9 9 0 0 1 15-6.7 L21 8"/><path d="M21 3 V8 H16"/><path d="M21 12 a9 9 0 0 1 -15 6.7 L3 16"/><path d="M3 21 V16 H8"/></g>,
    chart: <g><path d="M3 20 V4"/><path d="M3 20 H21"/><path d="M7 16 L11 11 L14 13 L19 7"/></g>,
    eye: <g><path d="M2 12 s4-7 10-7 10 7 10 7 -4 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></g>,
    chevron: <path d="M9 6 l6 6 -6 6"/>,
    bell: <g><path d="M6 8 a6 6 0 0 1 12 0 v5 l2 3 H4 l2-3 z"/><path d="M10 19 a2 2 0 0 0 4 0"/></g>,
  };
  return <svg viewBox="0 0 24 24" style={s}>{paths[name]}</svg>;
}

// ─────────── Toggle ───────────
function Toggle({ on, dark = false }) {
  return (
    <div style={{
      width: 56, height: 32, borderRadius: A.rPill, position: 'relative',
      background: on ? A.mint : (dark ? '#3F324F' : A.creamDeep),
      border: A.ol2, transition: 'background .2s',
    }}>
      <div style={{
        position: 'absolute', top: 1, left: on ? 24 : 1,
        width: 26, height: 26, borderRadius: '50%',
        background: '#fff', border: A.ol2,
        boxShadow: A.shStickerHard(A.plum),
        transition: 'left .2s',
      }}/>
    </div>
  );
}

// ─────────── Segmented control ───────────
function Segmented({ options, value, dark = false, style }) {
  return (
    <div style={{
      display: 'inline-flex', padding: 4,
      background: dark ? A.darkCard : A.creamDeep,
      border: A.ol2, borderRadius: A.rPill,
      ...style,
    }}>
      {options.map(o => {
        const on = o === value;
        return (
          <div key={o} style={{
            padding: '8px 18px', borderRadius: A.rPill,
            fontSize: 14, fontWeight: 800, letterSpacing: 0.3,
            fontFamily: A.font, cursor: 'pointer',
            background: on ? (dark ? A.darkText : '#fff') : 'transparent',
            color: on ? A.plum : (dark ? A.darkMid : A.plumMid),
            border: on ? '2px solid ' + A.plum : '2px solid transparent',
            boxShadow: on ? '0 2px 0 ' + A.plum : 'none',
          }}>{o}</div>
        );
      })}
    </div>
  );
}

Object.assign(window, {
  Btn, StatusPill, ModeChip, SideChip, Input, Money, Card, Sparkline,
  PositionRow, TabBar, Icon, Toggle, Segmented,
});
