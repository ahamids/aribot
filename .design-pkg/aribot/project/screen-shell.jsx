// Shared Screen shell — cream bg, status bar, content area, optional tab bar.

const SA = window.AT;

function Screen({ children, tab, title, dark = false, time = '9:41', noScroll = false, bgOverride, hideHomeIndicator }) {
  return (
    <div style={{
      width: '100%', height: '100%', position: 'relative',
      background: bgOverride || (dark ? SA.darkBg : SA.cream),
      fontFamily: SA.font, color: dark ? SA.darkText : SA.plum,
      overflow: 'hidden', display: 'flex', flexDirection: 'column',
    }}>
      {/* Status bar */}
      <div style={{
        height: 54, display: 'flex', alignItems: 'flex-end',
        padding: '0 30px 4px', justifyContent: 'space-between',
        flexShrink: 0, position: 'relative', zIndex: 2,
      }}>
        <span style={{ fontSize: 16, fontWeight: 700, color: dark ? SA.darkText : SA.plum }}>{time}</span>
        <span style={{ display: 'flex', gap: 6, alignItems: 'center', color: dark ? SA.darkText : SA.plum }}>
          <svg width="18" height="11" viewBox="0 0 18 11"><g fill="currentColor"><rect x="0" y="7" width="3" height="4" rx="0.6"/><rect x="5" y="5" width="3" height="6" rx="0.6"/><rect x="10" y="2" width="3" height="9" rx="0.6"/><rect x="15" y="0" width="3" height="11" rx="0.6"/></g></svg>
          <svg width="22" height="11" viewBox="0 0 22 11"><rect x="0.5" y="0.5" width="18" height="10" rx="2.5" stroke="currentColor" fill="none"/><rect x="2" y="2" width="15" height="7" rx="1.5" fill="currentColor"/><rect x="19.5" y="4" width="2" height="3" rx="0.5" fill="currentColor"/></svg>
        </span>
      </div>

      {/* Title */}
      {title && (
        <div style={{
          padding: '4px 24px 14px', flexShrink: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <h1 style={{
            margin: 0, fontSize: 32, fontWeight: 900, letterSpacing: -0.6,
            color: dark ? SA.darkText : SA.plum,
          }}>{title}</h1>
        </div>
      )}

      {/* Scrollable content */}
      <div style={{
        flex: 1, padding: tab ? '0 18px 110px' : '0 18px 30px',
        overflowY: noScroll ? 'hidden' : 'auto',
        position: 'relative',
      }}>
        {children}
      </div>

      {tab && <TabBar active={tab} dark={dark} />}

      {!hideHomeIndicator && (
        <div style={{
          position: 'absolute', bottom: 6, left: '50%', transform: 'translateX(-50%)',
          width: 134, height: 5, borderRadius: 100,
          background: dark ? 'rgba(255,255,255,0.45)' : 'rgba(45,31,71,0.45)', zIndex: 100,
        }}/>
      )}
    </div>
  );
}

Object.assign(window, { Screen });
