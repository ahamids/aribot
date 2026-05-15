// Aribot — design tokens. Cartoon-meets-trust palette, sticker shadows, SF Rounded.
window.AT = {
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
  plum: '#2D1F47',          // text + outlines (softer than black)
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

  // Type stack
  font: '"SF Pro Rounded", -apple-system, BlinkMacSystemFont, "SF Pro Display", system-ui, sans-serif',
  num:  '"SF Pro Rounded", "SF Pro Display", -apple-system, system-ui, sans-serif',

  // Shadows — the "puzzle piece" recipe
  shStickerSoft: '0 10px 22px rgba(45,31,71,0.14)',
  shStickerHard: (color = '#2D1F47') => `0 4px 0 0 ${color}`,
  shDual: (hard = '#2D1F47') => `0 4px 0 0 ${hard}, 0 10px 22px rgba(45,31,71,0.14)`,
  shInset: 'inset 0 2px 0 rgba(255,255,255,0.55)',  // glossy-plastic highlight
  shCard: '0 1px 0 rgba(255,255,255,0.7) inset, 0 6px 18px rgba(45,31,71,0.10)',

  // Radii
  rXL: 32, rL: 24, rM: 18, rS: 12, rPill: 999,

  // Outlines
  ol2: '2px solid #2D1F47',
  ol3: '3px solid #2D1F47',
  ol4: '4px solid #2D1F47',
};
