// useTheme — system-driven light/dark palette for Aribot.
//
// Returns a Theme object every primitive and screen can consume. Maps the
// raw tokens in tokens.ts onto a smaller set of semantic names that flip
// between light and dark.
//
// Design rules baked in:
//   - PnL colors (pnlRed / pnlGreen / pnlRedSoft / pnlGreenSoft) DO NOT
//     change between modes. They're the reservation rule's whole point.
//     Read them directly from `AT` in components, not through the theme.
//   - Accent hues (coral, yellow, mint, peri, plum text on chrome) also
//     stay constant — they're decorative paint on stickers, not surface
//     colors. Read directly from `AT`.
//   - "Sticker hard shadow" color flips: plum in light, near-black in dark.
//     The mascot rule (item 3.8) and the broader card-shadow rule both
//     consume this from theme.shadowHard.
//
// Trigger: useColorScheme() returns 'light' | 'dark' | null. We treat null
// as 'light' (cold-start before iOS resolves). No in-app override yet;
// the user can flip iOS Settings -> Display & Brightness -> Dark to change.

import { useColorScheme } from 'react-native';
import { AT } from './tokens';

export type ThemeKind = 'light' | 'dark';

export type Theme = {
  kind: ThemeKind;

  // Surfaces — three depth levels, plus the "input/card-on-cream" white.
  bg: string;        // root screen background
  paper: string;     // raised surface (slightly lighter than bg in dark mode)
  card: string;      // card background
  cardAlt: string;   // alternate card background (used for nested rows etc.)

  // Text + outline.
  text: string;      // primary text + outlines (was AT.plum)
  textMid: string;   // secondary text (was AT.plumMid)
  textSoft: string;  // tertiary / placeholder (was AT.plumSoft)
  outline: string;   // borders on sticker shapes (= text in both modes)

  // Dashed divider used between rows.
  divider: string;

  // Sticker hard shadow color — flips for visibility on dark bg.
  shadowHard: string;
};

const LIGHT: Theme = {
  kind: 'light',
  bg: AT.cream,
  paper: AT.paper,
  card: '#fff',
  cardAlt: AT.creamDeep,
  text: AT.plum,
  textMid: AT.plumMid,
  textSoft: AT.plumSoft,
  outline: AT.plum,
  divider: 'rgba(45,31,71,0.12)',
  shadowHard: AT.plum,
};

const DARK: Theme = {
  kind: 'dark',
  bg: AT.darkBg,
  paper: AT.darkPaper,
  card: AT.darkPaper,
  cardAlt: AT.darkCard,
  text: AT.darkText,
  textMid: AT.darkMid,
  textSoft: '#7A6A95',
  // In dark mode the "outline" still needs to be readable. The design uses
  // the same darkText color for outlines on dark cards — keeps the sticker
  // look without making outlines disappear into the bg.
  outline: AT.darkText,
  divider: 'rgba(255,255,255,0.10)',
  // Pure-black hard shadow in dark mode — plum disappears against darkBg.
  shadowHard: '#000',
};

export function useTheme(): Theme {
  const scheme = useColorScheme();
  return scheme === 'dark' ? DARK : LIGHT;
}

// Non-hook variant for module-level or imperative code paths. Always returns
// light; callers that need real theme awareness must use the hook.
export function getStaticLightTheme(): Theme {
  return LIGHT;
}
