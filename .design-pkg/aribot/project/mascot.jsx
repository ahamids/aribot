// Mascot — placeholder bear designed to be swapped later.
// <MascotSlot size pose tone /> wraps any character; <Bear /> is the placeholder.

const BEAR_FUR = '#E8A576';
const BEAR_FUR_DARK = '#C9824F';
const BEAR_INNER_EAR = '#FFD7B0';
const BEAR_SNOUT = '#FFEBD2';
const BEAR_OUTLINE = '#2D1F47';
const BEAR_BLUSH = '#FF8B66';

// Eye + mouth glyphs vary by pose; head/ears/snout are static.
function BearEyes({ pose }) {
  const O = BEAR_OUTLINE;
  switch (pose) {
    case 'sleeping':
    case 'napping':
      return (
        <g stroke={O} strokeWidth="4" strokeLinecap="round" fill="none">
          <path d="M68 96 Q78 102 88 96" />
          <path d="M112 96 Q122 102 132 96" />
        </g>
      );
    case 'panicked':
      return (
        <g stroke={O} strokeWidth="4" strokeLinecap="round" fill="none">
          <path d="M70 90 L86 102 M86 90 L70 102" />
          <path d="M114 90 L130 102 M130 90 L114 102" />
        </g>
      );
    case 'sad':
      return (
        <g fill={O}>
          <circle cx="78" cy="98" r="5" />
          <circle cx="122" cy="98" r="5" />
        </g>
      );
    case 'questioning':
      return (
        <g>
          <circle cx="78" cy="96" r="6" fill={O} />
          <circle cx="76" cy="94" r="2" fill="#fff" />
          <circle cx="122" cy="96" r="6" fill={O} />
          <circle cx="120" cy="94" r="2" fill="#fff" />
        </g>
      );
    case 'serious':
      return (
        <g>
          <ellipse cx="78" cy="96" rx="6" ry="4" fill={O} />
          <ellipse cx="122" cy="96" rx="6" ry="4" fill={O} />
        </g>
      );
    case 'wink':
      return (
        <g>
          <path d="M70 96 Q78 102 88 96" stroke={O} strokeWidth="4" strokeLinecap="round" fill="none" />
          <circle cx="122" cy="96" r="6" fill={O} />
          <circle cx="120" cy="94" r="2" fill="#fff" />
        </g>
      );
    case 'alert':
    case 'thumbsup':
    case 'waving':
    case 'happy':
    default:
      return (
        <g>
          <circle cx="78" cy="96" r="7" fill={O} />
          <circle cx="76" cy="94" r="2.5" fill="#fff" />
          <circle cx="122" cy="96" r="7" fill={O} />
          <circle cx="120" cy="94" r="2.5" fill="#fff" />
        </g>
      );
  }
}

function BearMouth({ pose }) {
  const O = BEAR_OUTLINE;
  switch (pose) {
    case 'sleeping':
    case 'napping':
      return <ellipse cx="100" cy="138" rx="6" ry="4" fill={O} />;
    case 'panicked':
      return <path d="M86 138 Q92 130 100 138 T114 138" stroke={O} strokeWidth="3.5" fill="none" strokeLinecap="round" />;
    case 'serious':
      return <path d="M86 138 L114 138" stroke={O} strokeWidth="4" strokeLinecap="round" />;
    case 'sad':
      return <path d="M86 142 Q100 132 114 142" stroke={O} strokeWidth="3.5" fill="none" strokeLinecap="round" />;
    case 'questioning':
      return <path d="M88 138 Q100 140 112 138" stroke={O} strokeWidth="3.5" fill="none" strokeLinecap="round" />;
    case 'thumbsup':
    case 'happy':
    case 'waving':
    case 'wink':
      return <path d="M84 132 Q100 150 116 132" stroke={O} strokeWidth="3.5" fill="none" strokeLinecap="round" />;
    case 'alert':
    default:
      return <path d="M88 134 Q100 144 112 134" stroke={O} strokeWidth="3.5" fill="none" strokeLinecap="round" />;
  }
}

function BearExtras({ pose }) {
  const O = BEAR_OUTLINE;
  // Things floating around the head: Zzz, ?, sweat, hearts
  if (pose === 'sleeping' || pose === 'napping') {
    return (
      <g fill={O} fontFamily={window.AT.font} fontWeight="800">
        <text x="148" y="56" fontSize="18">z</text>
        <text x="162" y="42" fontSize="22">Z</text>
        <text x="178" y="26" fontSize="26">Z</text>
      </g>
    );
  }
  if (pose === 'questioning') {
    return (
      <g fill={window.AT.yellow} stroke={O} strokeWidth="2.5">
        <circle cx="158" cy="48" r="14" />
        <text x="153" y="55" fontSize="18" fontWeight="900" fill={O} stroke="none" fontFamily={window.AT.font}>?</text>
      </g>
    );
  }
  if (pose === 'panicked') {
    return (
      <g>
        <ellipse cx="44" cy="78" rx="6" ry="9" fill={window.AT.peri} stroke={O} strokeWidth="2" />
        <ellipse cx="156" cy="78" rx="6" ry="9" fill={window.AT.peri} stroke={O} strokeWidth="2" />
      </g>
    );
  }
  return null;
}

function BearArms({ pose }) {
  const O = BEAR_OUTLINE;
  if (pose === 'thumbsup') {
    return (
      <g stroke={O} strokeWidth="3" strokeLinejoin="round">
        <path d="M156 130 L172 100 L168 88 L156 86 L150 100 Z" fill={BEAR_FUR} />
        <circle cx="170" cy="92" r="8" fill={BEAR_FUR} />
        <path d="M168 88 L172 80" strokeLinecap="round" />
      </g>
    );
  }
  if (pose === 'waving') {
    return (
      <g stroke={O} strokeWidth="3" strokeLinejoin="round">
        <path d="M156 122 L178 96 L168 84 L150 94 Z" fill={BEAR_FUR} />
        <circle cx="178" cy="92" r="10" fill={BEAR_FUR} />
        {/* motion lines */}
        <path d="M192 80 L198 76 M192 92 L200 92 M194 104 L200 108" strokeLinecap="round" strokeWidth="2.5" />
      </g>
    );
  }
  if (pose === 'questioning') {
    return (
      <g stroke={O} strokeWidth="3" strokeLinejoin="round">
        <path d="M138 64 L132 44 L120 38 L114 50 Z" fill={BEAR_FUR} />
        <circle cx="125" cy="40" r="8" fill={BEAR_FUR} />
      </g>
    );
  }
  return null;
}

function Bear({ pose = 'alert' }) {
  const O = BEAR_OUTLINE;
  return (
    <svg viewBox="0 0 200 200" width="100%" height="100%" style={{ overflow: 'visible' }}>
      {/* Ears */}
      <g stroke={O} strokeWidth="4">
        <circle cx="52" cy="52" r="22" fill={BEAR_FUR} />
        <circle cx="148" cy="52" r="22" fill={BEAR_FUR} />
        <circle cx="52" cy="52" r="11" fill={BEAR_INNER_EAR} stroke="none" />
        <circle cx="148" cy="52" r="11" fill={BEAR_INNER_EAR} stroke="none" />
      </g>
      {/* Head */}
      <ellipse cx="100" cy="105" rx="62" ry="58" fill={BEAR_FUR} stroke={O} strokeWidth="4" />
      {/* Snout */}
      <ellipse cx="100" cy="130" rx="34" ry="24" fill={BEAR_SNOUT} stroke={O} strokeWidth="3" />
      {/* Cheeks */}
      <ellipse cx="62" cy="124" rx="9" ry="5" fill={BEAR_BLUSH} opacity="0.55" />
      <ellipse cx="138" cy="124" rx="9" ry="5" fill={BEAR_BLUSH} opacity="0.55" />
      {/* Nose */}
      <ellipse cx="100" cy="116" rx="9" ry="6.5" fill={O} />
      <ellipse cx="97" cy="113" rx="2" ry="1.5" fill="#fff" opacity="0.8" />

      <BearEyes pose={pose} />
      <BearMouth pose={pose} />
      <BearArms pose={pose} />
      <BearExtras pose={pose} />
    </svg>
  );
}

// MascotSlot: reusable container/frame the character drops into.
// `frame` controls chrome (circle bg + thick outline). `flat` disables it.
function MascotSlot({ size = 120, pose = 'alert', tone = 'yellow', frame = true, prop, style }) {
  const t = window.AT;
  const toneBg = {
    yellow: t.yellow, mint: t.mint, peri: t.peri, coral: t.coral,
    cream: t.creamDeep, plum: t.plumMid,
  }[tone] || t.yellow;

  return (
    <div style={{
      position: 'relative', width: size, height: size,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      ...style,
    }}>
      {frame && (
        <div style={{
          position: 'absolute', inset: 0, borderRadius: '50%',
          background: toneBg,
          border: t.ol4,
          boxShadow: t.shDual(t.plum),
        }}/>
      )}
      <div style={{
        position: 'relative', width: size * 0.78, height: size * 0.78,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <Bear pose={pose} />
        {prop /* slot for props like flags/cables/signs */}
      </div>
    </div>
  );
}

// Optional accessories the mascot can hold — used by error/empty states.
function MProp({ kind }) {
  const O = '#2D1F47';
  const t = window.AT;
  if (kind === 'flag') return (
    <svg viewBox="0 0 200 200" style={{ position: 'absolute', inset: 0, overflow: 'visible' }} width="100%" height="100%">
      <rect x="175" y="20" width="5" height="110" rx="2" fill={O} />
      <path d="M180 24 L218 30 L210 50 L218 70 L180 76 Z" fill={t.pnlRed} stroke={O} strokeWidth="3" strokeLinejoin="round" />
    </svg>
  );
  if (kind === 'cable') return (
    <svg viewBox="0 0 200 200" style={{ position: 'absolute', inset: 0, overflow: 'visible' }} width="100%" height="100%">
      <path d="M30 150 Q10 130 22 110 Q34 90 18 70" fill="none" stroke={O} strokeWidth="6" strokeLinecap="round" />
      <rect x="12" y="60" width="14" height="18" rx="3" fill={t.peri} stroke={O} strokeWidth="3" />
      <path d="M170 150 Q190 130 178 110 Q166 90 182 70" fill="none" stroke={O} strokeWidth="6" strokeLinecap="round" />
      <rect x="174" y="60" width="14" height="18" rx="3" fill={t.coral} stroke={O} strokeWidth="3" />
      {/* spark */}
      <g fill={t.yellow} stroke={O} strokeWidth="2">
        <path d="M100 50 L95 38 L107 42 L102 30 L114 36" strokeLinejoin="round" />
      </g>
    </svg>
  );
  if (kind === 'chart') return (
    <svg viewBox="0 0 200 200" style={{ position: 'absolute', bottom: -20, left: 30, overflow: 'visible' }} width="60%" height="40%">
      <rect x="10" y="10" width="180" height="120" rx="14" fill={t.paper} stroke={O} strokeWidth="3.5" />
      <path d="M22 100 L60 80 L92 92 L130 50 L178 64" fill="none" stroke={t.coral} strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" transform="rotate(180 100 70)" />
    </svg>
  );
  if (kind === 'vault') return (
    <svg viewBox="0 0 200 200" style={{ position: 'absolute', inset: 0, overflow: 'visible' }} width="100%" height="100%">
      <rect x="18" y="148" width="32" height="42" rx="7" fill={t.yellow} stroke={O} strokeWidth="3" />
      <circle cx="34" cy="160" r="4" fill="none" stroke={O} strokeWidth="2.5" />
      <path d="M34 160 V172" stroke={O} strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  );
  return null;
}

Object.assign(window, { Bear, MascotSlot, MProp });
