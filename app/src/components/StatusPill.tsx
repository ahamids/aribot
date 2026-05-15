// StatusPill — running/stopped/error/killed. Color is paired with an icon AND
// label, never used alone (the rule from the design guardrails).

import React from 'react';
import { StyleProp, Text, View, ViewStyle } from 'react-native';
import { AT, stickerShadow } from '@/theme/tokens';
import { useTheme } from '@/theme/useTheme';

export type Status = 'running' | 'stopped' | 'error' | 'killed';

const CFG: Record<
  Status,
  { bg: string; label: string; dot: string; glyph: string }
> = {
  running: { bg: AT.mint,        label: 'RUNNING', dot: AT.pnlGreen, glyph: '▶' },
  stopped: { bg: AT.creamDeep,   label: 'STOPPED', dot: AT.plumMid,  glyph: '■' },
  error:   { bg: AT.pnlRedSoft,  label: 'ERROR',   dot: AT.pnlRed,   glyph: '!' },
  killed:  { bg: AT.pnlRedSoft,  label: 'KILLED',  dot: AT.pnlRed,   glyph: '⚑' },
};

export function StatusPill({
  status = 'running' as Status,
  mode,
  style,
}: {
  status?: Status;
  mode?: 'PAPER' | 'SHADOW' | 'LIVE';
  style?: StyleProp<ViewStyle>;
}) {
  const cfg = CFG[status];
  const theme = useTheme();
  // The pill's outer bg (mint/cream/pnlRedSoft) is always a light hue per
  // the design — it's MEANT to pop on dark surfaces. So the inner text +
  // dot-outline color stays AT.plum (the design's dark text), not the
  // theme text. Only the outer outline + sticker shadow + the inner mode
  // badge flip.
  return (
    <View
      style={[
        {
          flexDirection: 'row',
          alignItems: 'center',
          gap: 8,
          paddingVertical: 8,
          paddingLeft: 10,
          paddingRight: 14,
          backgroundColor: cfg.bg,
          borderRadius: AT.rPill,
          borderWidth: AT.ol2,
          borderColor: AT.plum,
          alignSelf: 'flex-start',
        },
        stickerShadow(theme.shadowHard),
        style,
      ]}
      accessibilityLabel={`Bot status: ${cfg.label}${mode ? `, mode ${mode}` : ''}`}
    >
      <View
        style={{
          width: 18,
          height: 18,
          borderRadius: 9,
          backgroundColor: cfg.dot,
          borderWidth: 2,
          borderColor: AT.plum,
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Text style={{ color: '#fff', fontSize: 10, fontWeight: '900' }}>{cfg.glyph}</Text>
      </View>
      <Text
        style={{
          color: AT.plum,
          fontWeight: '800',
          fontSize: 13,
          letterSpacing: 0.6,
        }}
      >
        {cfg.label}
      </Text>
      {mode ? (
        <View
          style={{
            backgroundColor: AT.plum,
            borderRadius: AT.rPill,
            paddingHorizontal: 8,
            paddingVertical: 2,
            marginLeft: 4,
          }}
        >
          <Text style={{ color: AT.cream, fontSize: 11, fontWeight: '800', letterSpacing: 0.6 }}>
            {mode}
          </Text>
        </View>
      ) : null}
    </View>
  );
}
