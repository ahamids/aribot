// Aribot design tokens. Ported 1:1 from the design package (tokens.jsx).
// Cartoon-meets-trust palette, sticker shadows, SF Rounded.
// Reserve pnlRed/pnlGreen exclusively for PnL, direction, kill switch, LIVE warnings.

import type { ViewStyle, TextStyle } from 'react-native';
import { Platform } from 'react-native';

export const AT = {
  // Backgrounds
  cream: '#FFF4E6',
  creamDeep: '#FFE9C9',
  paper: '#FFFAF1',

  // Hero accents — saturated candy
  coral: '#FF8B66',
  coralDeep: '#E66A45',
  yellow: '#FFC93C',
  yellowDeep: '#E8A91A',
  mint: '#7DD3AE',
  mintDeep: '#4DA67E',
  peri: '#8B9DFF',
  periDeep: '#6877D6',
  plum: '#2D1F47', // text + outlines (softer than black)
  plumMid: '#5B4880',
  plumSoft: '#9B8FB8',

  // PnL ONLY — never decorative
  pnlGreen: '#30A46C',
  pnlGreenSoft: '#C8EFD9',
  pnlRed: '#E5484D',
  pnlRedSoft: '#F9C9CA',

  // Dark mode (warm dark, not black)
  darkBg: '#241A2E',
  darkPaper: '#2F2440',
  darkCard: '#3A2C50',
  darkText: '#FFEBC7',
  darkMid: '#C4B0E0',

  // Radii
  rXL: 32,
  rL: 24,
  rM: 18,
  rS: 12,
  rPill: 999,

  // Outline widths (RN uses borderWidth + borderColor, not shorthand)
  ol2: 2,
  ol3: 3,
  ol4: 4,
} as const;

// SF Pro Rounded on iOS; system fallback elsewhere.
// RN doesn't natively expose tabular-nums via style — we rely on the rounded
// face which has tabular figures by default on iOS for digits.
export const FONT = {
  family: Platform.select({ ios: 'System', default: 'System' }) as string,
  // iOS-only: ask for the rounded design via fontFamily naming convention.
  // RN doesn't support fontVariant tabular on all platforms — keep widths
  // consistent by using digits-only contexts and right-alignment.
  rounded: Platform.OS === 'ios' ? ('SF Pro Rounded' as const) : ('System' as const),
};

// Sticker shadow recipe — RN can only do ONE shadow per view, so we layer it
// on a wrapper View (hard offset) + child View (ambient soft) when both are
// needed. The helpers below produce the closest single-shadow approximation.

export function stickerShadow(hardColor: string = AT.plum): ViewStyle {
  // Hard offset: 0 4px 0 0 plum  -> RN approximation via shadowOffset + 0 blur.
  return Platform.select<ViewStyle>({
    ios: {
      shadowColor: hardColor,
      shadowOffset: { width: 0, height: 4 },
      shadowOpacity: 1,
      shadowRadius: 0,
    },
    android: {
      // Android can't do colored hard shadows; fall back to elevation.
      elevation: 4,
    },
    default: {
      shadowColor: hardColor,
      shadowOffset: { width: 0, height: 4 },
      shadowOpacity: 1,
      shadowRadius: 0,
    },
  })!;
}

export function ambientShadow(): ViewStyle {
  return Platform.select<ViewStyle>({
    ios: {
      shadowColor: AT.plum,
      shadowOffset: { width: 0, height: 10 },
      shadowOpacity: 0.14,
      shadowRadius: 22,
    },
    android: { elevation: 6 },
    default: {
      shadowColor: AT.plum,
      shadowOffset: { width: 0, height: 10 },
      shadowOpacity: 0.14,
      shadowRadius: 22,
    },
  })!;
}

export const TYPE: Record<string, TextStyle> = {
  h1: { fontSize: 32, fontWeight: '900', letterSpacing: -0.6, color: AT.plum },
  h2: { fontSize: 28, fontWeight: '900', letterSpacing: -0.4, color: AT.plum },
  h3: { fontSize: 22, fontWeight: '800', letterSpacing: -0.2, color: AT.plum },
  body: { fontSize: 16, fontWeight: '500', color: AT.plum },
  bodyMid: { fontSize: 14, color: AT.plumMid, lineHeight: 20 },
  caption: { fontSize: 12, color: AT.plumMid },
  label: {
    fontSize: 13,
    fontWeight: '700',
    color: AT.plumMid,
    letterSpacing: 0.4,
    textTransform: 'uppercase',
  },
};
