# Aribot iOS — implementation passes

Generated from `app/docs/reality-check/2026-05-13-design-audit.md`. Five passes,
each self-contained. Pass 5 is optional (internal reference docs).

---

## How Claude Code should use this file

**Before starting any pass:**
1. Read the **whole pass section** (Goal → Items → Acceptance → Verification → Risk → Boundaries).
2. **Stop and confirm with the user** which items in that pass to implement.
   The list is exhaustive — the user may want to do all of it, a slice of it,
   or reorder against the audit's classification. Don't assume.
3. If anything is ambiguous (a design file says one thing, the repo says
   another, the audit and the design disagree on a detail), **ask the user
   to clarify before writing code.** It is much cheaper to clarify scope up
   front than to build the wrong thing.

**During the pass:**
- Use the `Risk callouts` section to know what NOT to touch beyond the items.
- Use the `Boundaries — do NOT do` section to prevent scope creep.
- Honor the "implemented but worse" notes in the audit — those are not bugs
  to fix unless they're explicitly listed as items.

**Before declaring the pass done:**
- Run every verification command in the `Verification` section.
- If a verification fails, fix it; don't mark the pass complete.
- Update this file: change the pass header from `## Pass N` to `## Pass N (DONE YYYY-MM-DD)` and tick off items inline.

**Locked-in scope decisions (apply to every pass):**

1. The LIVE confirm sheet's `KV` summary card (MARKET / MAX RISK / LEVERAGE /
   DAILY CAP from the design) is **out of scope** until the sidecar has a
   `/config` endpoint. The typed-LIVE-to-confirm gate stays.
2. Kill switch uses **new sidecar endpoints `POST /kill` (trip) and
   `DELETE /kill` (clear)**. `POST /stop` keeps its existing "stop cleanly at
   next cycle" semantics.
3. Empty/error states are **mascot cards inside each screen**, not full-
   screen takeovers. Each screen renders its own data when it can, falls
   back to a mascot card when it can't.

---

## Pass 1 (DONE 2026-05-13) — Trust & safety: kill switch + the visible-on-bad-days mascot states

**MUST tier. Highest leverage. Do this first.**

### Goal

The design's load-bearing safety affordance is the kill switch, and its
load-bearing brand affordance is the mascot showing up on bad days. Neither
is in the app today. This pass fixes both. After this pass, a trader can
stop the bot from their phone with a deliberate gesture, and the app feels
on-brand when something is wrong.

### Items

| # | Item | Tier | Status | Design source | Impl target |
|---|---|---|---|---|---|
| 1.1 | Add sidecar endpoints `POST /kill` (write kill_switch.flag with intent) and `DELETE /kill` (remove the flag) | MUST | ✅ | locked-in decision #2 | `status_server.py` |
| 1.2 | `KillButton` component — hold-to-activate 1.5s gesture with `scaleX` progress fill, sticker pill, plum hard shadow | MUST | ✅ | `components.jsx` section `KillButton` lines 226–240; `screens-main.jsx:184-192` | `app/src/components/KillButton.tsx` |
| 1.3 | Add **Safety** section to Settings with the `KillButton` and a "clear kill switch" affordance when it's already tripped | MUST | ✅ | `screens-main.jsx:183-192` | `app/app/(app)/settings.tsx` |
| 1.4 | Wire `tripKill` and `clearKill` into `botApi.ts` (mandatory bearer like the rest) | MUST | ✅ | follows existing pattern of `startBot`/`stopBot` | `app/src/lib/botApi.ts` |
| 1.5 | Standalone **host-down** mascot card: `panicked` pose + `cable` MProp + body + **Retry** CTA. Renders on Dashboard, Positions, History when their fetch errors are network errors | MUST | ✅ | `screens-states.jsx` (`kind="host-down"`) + `mascot.jsx MProp:cable` | `app/src/components/states/HostDownCard.tsx` |
| 1.6 | Standalone **kill-active** mascot card: `serious` pose + `flag` MProp + body + **Open Settings** CTA. Renders on Positions and History when `status === 'killed'`; the Dashboard's status card already handles the killed state so the standalone card isn't shown there to avoid double-rendering | MUST | ✅ | `screens-states.jsx` (`kind="kill-active"`) + `mascot.jsx MProp:flag` | `app/src/components/states/KillActiveCard.tsx` |
| 1.7 | Standalone **no-positions** mascot card: `napping` pose + cream tone + optional "Wake the bot" CTA (Dashboard omits it because the start button is right above; Positions shows it) | MUST | ✅ | `screens-states.jsx` (`kind="no-positions"`) | `app/src/components/states/EmptyPositionsCard.tsx`, replaces inline `EmptyOpen` in `positions.tsx` |
| 1.8 | Dashboard's flat `pnlRedSoft` "Can't reach the bot" toast replaced with the new `HostDownCard`; transport vs. HTTP errors classified via `isHostDownError` so HTTP-level failures still get an inline card | MUST | ✅ | follows item 1.5 | `app/app/(app)/dashboard.tsx`, `app/src/lib/botApi.ts` |

### Acceptance criteria

- Tripping the kill switch from the iOS app:
  1. Requires holding the kill button for **1.5 seconds**, not a tap.
  2. Shows progress visually (button fills left-to-right).
  3. Releasing early **cancels** without firing.
  4. Returns the user to a state where `kill-active` mascot card renders.
- Clearing the kill switch from the iOS app:
  1. Visible only when the kill switch is currently tripped.
  2. Removes `kill_switch.flag` server-side.
  3. Status flips back to `stopped` within one poll cycle.
- The three new state cards each appear on **all three relevant tabs**
  (Dashboard, Positions, History) when their condition holds, not just on
  Dashboard.
- `kill-active` mascot card uses `MProp.flag` (already shipped, currently
  unused).
- `host-down` mascot card uses `MProp.cable` (already shipped, currently
  unused).

### Verification

```powershell
# Typecheck the app
cd C:\git\aribot-og\app; npx tsc --noEmit

# Bundler smoke (catches runtime import errors)
cd C:\git\aribot-og\app; npx expo export --platform web --output-dir .expo-smoke
Remove-Item -Recurse -Force .expo-smoke

# Sidecar python syntax
python -c "import ast; ast.parse(open(r'C:\git\aribot-og\status_server.py','r',encoding='utf-8').read()); print('parse OK')"

# Sidecar smoke — exercise the new endpoints
$env:ARIBOT_API_TOKEN = "smoketest"
python C:\git\aribot-og\status_server.py --host 127.0.0.1 --port 8787 &
# in another shell:
$tok = "smoketest"
Invoke-WebRequest -Uri http://127.0.0.1:8787/kill -Method POST -Headers @{Authorization="Bearer $tok"} -UseBasicParsing
Test-Path C:\git\aribot-og\kill_switch.flag   # should be True
Invoke-WebRequest -Uri http://127.0.0.1:8787/kill -Method DELETE -Headers @{Authorization="Bearer $tok"} -UseBasicParsing
Test-Path C:\git\aribot-og\kill_switch.flag   # should be False
```

The KillButton hold gesture itself can only be eyeballed on a real device
or simulator — Claude Code should call out in the final report that visual
verification needs to happen on the user's iPhone via Expo Go.

### Risk callouts

- **The bot already reads `kill_switch.flag`** on startup and during every
  cycle. Don't change that behavior — both new endpoints are additive
  wrappers around the same flag file. If the bot's behavior on flag-present
  changes, the iOS UX is suddenly off the rails.
- **`stopBot` (existing `POST /stop`) is now a sibling of `tripKill`, not a
  rename of it.** Both write the flag, but the sidecar's intent strings in
  the flag content differ for forensic clarity. Don't delete `POST /stop`.
- **`MProp.flag` and `MProp.cable` already exist in `app/src/mascot/MProp.tsx`.**
  Do not re-implement them. Import.
- **The hold-1.5s gesture interacts with `react-native-gesture-handler`.**
  That package is already installed; if a different gesture lib is
  introduced, it'll fight RN Reanimated's worklet runner.
- **Polling races.** The dashboard polls every 5s. After tripping the kill
  switch, the user might see a 5s window of stale status. Don't refactor
  the polling architecture in this pass — call `reload()` after the trip
  succeeds and accept one stale frame.

### Boundaries — do NOT

- Do NOT add the mode switcher to Settings in this pass (Pass 2).
- Do NOT add notifications toggles (Pass 4).
- Do NOT add dark mode (Pass 3).
- Do NOT refactor the existing `Alert.alert('Stop the bot?', …)` flow on
  the dashboard's STOP button — the kill switch is a separate, more severe
  affordance. Both should coexist.
- Do NOT extract `SideChip` here (Pass 2). It's tempting because the new
  cards use it, but the audit groups primitive extraction in Pass 2.
- Do NOT touch the dashboard gradients, the LIVE confirm sheet, the magic-
  link handler, or any Settings section other than the new Safety section.

---

## Pass 2 (DONE 2026-05-13) — Daily-use polish: mode switcher, missing primitives, LIVE sheet

**MUST tier (mostly). Brings the app's daily controls in line with the design.**

### Goal

After Pass 1 the trader can trust the app. After Pass 2 they can use it
without leaving the phone for ops tasks. Mode switching, magic-link sign
in, and the LIVE sheet's title fix all land. The two open-coded primitives
(`SideChip`, `Toggle`) get extracted so Pass 4's Notifications work has
something to reach for.

### Items

| # | Item | Tier | Status | Design source | Impl target |
|---|---|---|---|---|---|
| 2.1 | Extract `SideChip` as a primitive — props `side: 'LONG' \| 'SHORT'`. Replace three inline copies with the import | MUST | ✅ | `components.jsx:90-104` | `app/src/components/SideChip.tsx`, plus `PositionRow.tsx`, `positions.tsx`, `history.tsx` |
| 2.2 | Create `Toggle` primitive — props `value: bool`, `onValueChange`. 56×32 sticker pill, plum border, mint when on, dual shadow | MUST | ✅ | `components.jsx Toggle:291-307` | `app/src/components/Toggle.tsx` |
| 2.3 | Add **Mode** section to Settings: three `ModeChip` buttons, active one wins, LIVE selection triggers a red warning card and (re)opens the existing `LiveConfirmSheet` with the typed-LIVE gate | MUST | ✅ | `screens-main.jsx:168-181` | `app/app/(app)/settings.tsx` |
| 2.4 | Add sidecar `POST /mode` endpoint that writes the requested mode to `.env` atomically, preserving other keys and comments. Refuses with 409 if the bot is currently running (per scope decision) | MUST | ✅ | follows existing endpoint patterns | `status_server.py` |
| 2.5 | Wire `setBotMode(mode)` into `botApi.ts`, surface from the Settings mode chips | MUST | ✅ | follows `startBot`/`stopBot` pattern | `app/src/lib/botApi.ts` |
| 2.6 | Magic-link sign-in handler — `supabase.auth.signInWithOtp({email})` sends a 6-digit code. New `(auth)/verify-code.tsx` screen accepts the code and calls `verifyOtp` to complete the session. Includes 60s resend cooldown | MUST | `screens-onboarding.jsx SignIn:94`, `SignUp:60-63` | ✅ | `(auth)/sign-in.tsx`, `(auth)/sign-up.tsx`, new `(auth)/verify-code.tsx`, `lib/auth.tsx` |
| 2.7 | LIVE confirm sheet title fix: "Start in LIVE mode?" (not "Real money mode") | MUST | ✅ | `screens-sheets.jsx:259-261` | `app/src/components/LiveConfirmSheet.tsx` |
| 2.8 | Standalone **no-trades** mascot card with `mint` tone | SHOULD | ✅ | `screens-states.jsx` (`kind="no-trades"`) | `app/src/components/states/EmptyTradesCard.tsx`, wired into `history.tsx` |

### Acceptance criteria

- Settings → Mode → tapping `PAPER` (when on SHADOW) succeeds, the dashboard's
  mode chip updates within one poll cycle, and a fresh bot start uses PAPER.
- Settings → Mode → tapping `LIVE` opens the `LiveConfirmSheet`. Typing
  "LIVE" and confirming sets mode to LIVE. Cancel returns to the previous mode.
- `SideChip` is imported, not open-coded, anywhere in the app.
  `grep -r "isLong" app/app app/src/components | grep -v SideChip.tsx`
  should return zero hits in shipped code.
- Magic-link button on sign-in: tap → success state ("Check your email"),
  failure state surfaces the Supabase error.
- LIVE confirm sheet title reads "Start in LIVE mode?".

### Verification

```powershell
cd C:\git\aribot-og\app; npx tsc --noEmit
cd C:\git\aribot-og\app; npx expo export --platform web --output-dir .expo-smoke
Remove-Item -Recurse -Force .expo-smoke
python -c "import ast; ast.parse(open(r'C:\git\aribot-og\status_server.py','r',encoding='utf-8').read()); print('parse OK')"

# Sidecar: exercise /mode
$env:ARIBOT_API_TOKEN = "smoketest"
python C:\git\aribot-og\status_server.py --host 127.0.0.1 --port 8787 &
$tok = "smoketest"
Invoke-WebRequest -Uri http://127.0.0.1:8787/mode -Method POST `
  -Body '{"mode":"PAPER"}' `
  -Headers @{Authorization="Bearer $tok"; "Content-Type"="application/json"} `
  -UseBasicParsing
```

### Risk callouts

- **`POST /mode` writes to `.env`** which is sensitive. The write must be
  atomic (tmp + rename), must preserve comments and other keys, and must
  refuse to write anything but `paper`/`shadow`/`live` (case-normalized).
- **Changing `BOT_MODE` while the bot is running** is dangerous — the bot
  reads it once at startup. The endpoint should require the bot to be
  stopped first, or write a `pending_mode` value that the bot picks up at
  next restart. Don't let the iOS app switch a running LIVE bot to PAPER
  silently — confirm and warn.
- **Magic-link rate limits.** Supabase rate-limits OTP requests aggressively
  (one per 60 seconds per email). The button must show a disabled
  countdown after a successful request to avoid double-firing.
- **`SideChip` extraction is a refactor that touches three files.** Run the
  typecheck after each replacement, not all at once.
- **`Toggle` shows up in Pass 4's notifications.** Don't add `useState` for
  notification preferences here; Pass 4 owns persistence.

### Boundaries — do NOT

- Do NOT add notifications toggles to Settings (Pass 4).
- Do NOT add the Account section's Plan row or red Sign-out row pattern
  (Pass 4).
- Do NOT touch dark mode (Pass 3).
- Do NOT re-add the LIVE sheet KV summary that was explicitly dropped from
  scope.
- Do NOT change the existing dashboard `Alert.alert` STOP flow.
- Do NOT touch the kill switch — that's Pass 1.
- Do NOT extract `SectionLabel` / `Row` patterns into primitives yet (Pass 4).

---

## Pass 3 (DONE 2026-05-13) — Dark mode + dashboard visual polish

**SHOULD tier. Visual fidelity to design.**

### Goal

The design ships dark variants of Dashboard, Positions, and History. None
exist in the app today. Tokens are ready (`darkBg / darkPaper / darkCard /
darkText / darkMid` in `tokens.ts`). This pass wires `useColorScheme`
through the affected screens and fixes the dashboard's flat backgrounds to
match the design's vertical gradients.

### Items

| # | Item | Tier | Status | Design source | Impl target |
|---|---|---|---|---|---|
| 3.1 | `useTheme` hook (`useColorScheme()`-driven). Returns a semantic `Theme` object with surface colors, text/outline, and `shadowHard` that flips per mode. PnL/accent hues stay literal. | SHOULD | ✅ | tokens already in `tokens.ts:27-31, 34-38` | `app/src/theme/useTheme.ts` |
| 3.2 | Dashboard dark mode + status card gradient | SHOULD | ✅ | `app.jsx:68` (`dark-dash`) | `app/app/(app)/dashboard.tsx` |
| 3.3 | Positions dark mode (full screen + 4 helper subcomponents themed via own `useTheme()` calls) | SHOULD | ✅ | `app.jsx:69` (`dark-pos`) | `app/app/(app)/positions.tsx` |
| 3.4 | History dark mode (Trades + Equity views + helpers) | SHOULD | ✅ | `app.jsx:70` (`dark-hist`) | `app/app/(app)/history.tsx` |
| 3.5 | Status card vertical gradient via react-native-svg `LinearGradient`. New `GradientFill` component honoring the design's 70%-stop recipe. | SHOULD | ✅ | `screens-dashboard.jsx:31-33` | new `app/src/components/GradientFill.tsx` + dashboard |
| 3.6 | Dynamic Type XXL | SHOULD | ⏸ DEFERRED | `dash-large-text` artboard | (out of scope per Pass 3 scope decision) |
| 3.7 | Primitives accept theme: Btn, Card, Input, Money, Sparkline, StatusPill, ModeChip, Segmented, KV, PositionRow, Toggle, KillButton, Screen, MascotSlot, TabBar, plus root layout. State cards (HostDown, KillActive, EmptyPositions, EmptyTrades), EquityChart, LiveConfirmSheet, Settings. | SHOULD | ✅ | every primitive | `app/src/components/**`, `app/src/mascot/MascotSlot.tsx`, `app/app/_layout.tsx`, `app/app/(app)/_layout.tsx`, `app/app/(app)/settings.tsx` |
| 3.8 | MascotSlot hard shadow uses `theme.shadowHard` (plum in light, `#000` in dark) per the design pattern. | SHOULD | ✅ | `components.jsx:51, 173, 243`, `tokens.jsx:40-42` | `app/src/mascot/MascotSlot.tsx` |

### Acceptance criteria

- iPhone toggled to dark mode shows the dark variant of Dashboard, Positions,
  History. Settings/Onboarding can stay light-only in this pass.
- Status pill's color contrast meets WCAG AA in dark mode against
  `darkPaper`.
- PnL red/green stays identical in dark mode (the design's reservation rule
  — pure red/green for PnL only).
- Dashboard status card has a visible top-to-bottom gradient on running
  (mint→paper), error/killed (pnlRedSoft→paper), stopped (creamDeep→paper).
- Dynamic Type at the largest accessibility size doesn't truncate the PnL
  number or break the layout.

### Verification

```powershell
cd C:\git\aribot-og\app; npx tsc --noEmit
cd C:\git\aribot-og\app; npx expo export --platform web --output-dir .expo-smoke
Remove-Item -Recurse -Force .expo-smoke
```

Visual verification on iPhone: toggle iOS Settings → Display & Brightness →
Dark, reopen the app, walk through Dashboard / Positions / History. Then
toggle Display Zoom + Accessibility → Display & Text Size → Larger Text →
move to max. Eyeball each screen.

### Risk callouts

- **The light/dark fork can double the surface area** if you're not careful.
  The cleanest approach: every component accepts a `theme` object (or uses
  `useTheme()` internally), no `if (dark) {...} else {...}` branches in
  screen code. Pick one pattern and stay with it.
- **`expo-linear-gradient` is not currently installed.** Either add it
  (`npx expo install expo-linear-gradient`) or implement gradients via
  `react-native-svg`'s `LinearGradient` which IS installed. The SVG path
  is preferable — no new dep, no new native module to align with the SDK.
- **`useColorScheme()` can return `null`** on cold start before the system
  resolves. Default to light, don't crash.
- **The mascot's color palette** (the bear's own fur colors) is hardcoded
  in `Bear.tsx`. Don't touch it — the mascot is meant to read the same
  in light and dark, and the slot's tone wraps it.
- **Hard shadows on dark mode.** The plum `0 4px 0 0 plum` shadow becomes
  invisible against the dark background — `tokens.ts` already exports
  `shStickerHard(color)` which defaults to plum; in dark mode pass `#000`.

### Boundaries — do NOT

- Do NOT add an in-app dark-mode override toggle yet (later pass; Pass 4
  could pick it up under Account settings).
- Do NOT touch Settings or Onboarding screens (light-only is fine).
- Do NOT change the design's pure-red / pure-green PnL colors in dark mode.
  They're literal hex values reserved by the design.
- Do NOT refactor the polling architecture or `botApi.ts` here.
- Do NOT add new screens.

---

## Pass 4 (PARTIAL DONE 2026-05-14) — Settings completion + recovery + remaining empties

**SHOULD tier (mostly). Closes the design's most-incomplete screen + the recovery story.**

Items 4.1–4.7 shipped. Item 4.8 (vault recovery passphrase) is **deferred**
to a follow-up pass — the user opted to verify the Settings/empty-state work
on its own first.

### Goal

Settings becomes a real screen, not a placeholder. The two remaining
standalone empty states ship. The vault gets a recovery story so a lost
phone doesn't permanently lock the user out.

### Items

| # | Item | Tier | Status | Design source | Impl target |
|---|---|---|---|---|---|
| 4.1 | Extract `SectionLabel` + `Row` primitives — used pervasively by Settings | SHOULD | ✅ | `screens-main.jsx:208-224` | new `app/src/components/SectionLabel.tsx`, `app/src/components/Row.tsx` |
| 4.2 | **Bot** section in Settings: Host URL (masked), Bearer token (masked, eye toggle), Test connection row with green ✓ OK / red error display. Reuses `pingStatus` from `botApi.ts` | SHOULD | ✅ | `screens-main.jsx:161-166` | `app/app/(app)/settings.tsx` |
| 4.3 | **Account** section: Email (read-only), Plan (read-only placeholder "Personal"), red Sign-out row (replace current Btn-on-card pattern) | SHOULD | ✅ | `screens-main.jsx:154-159` | `app/app/(app)/settings.tsx` |
| 4.4 | **Notifications** section: three Toggle rows (Fill alerts / Error alerts / Daily summary) with prefs persisted to `AsyncStorage`. No push plumbing yet (Pass 4 ships UI + storage; APNs registration is a future pass) | SHOULD | ✅ | `screens-main.jsx:194-199` | `app/app/(app)/settings.tsx`, new `app/src/lib/notificationPrefs.ts` |
| 4.5 | Version footer "Aribot · vX · build Y" pulled from `expo-constants` | NICE | ✅ | `screens-main.jsx:201-203` | `app/app/(app)/settings.tsx` |
| 4.6 | Standalone **auth-error** mascot card: `questioning` pose + `yellow` tone + Try-again CTA. Replaces inline red `Text` under password field in sign-in | SHOULD | ✅ | `screens-states.jsx` (`kind="auth-error"`) | new `app/src/components/states/AuthErrorCard.tsx`, wire into `(auth)/sign-in.tsx` and `(auth)/sign-up.tsx` |
| 4.7 | Standalone **chart-empty** mascot card: `alert` pose + `yellow` tone + `chart` MProp + a quiet "warming up" copy. Replaces `LoadingCard()` in History/Equity initial load | SHOULD | ✅ | `screens-states.jsx` (`kind="chart-empty"`) + `MProp.chart` | new `app/src/components/states/ChartEmptyCard.tsx`, wire into `history.tsx` |
| 4.8 | Vault recovery passphrase — UX + crypto: on first vault save, ask user for a passphrase, derive a wrapper key (Argon2id if available, scrypt fallback), encrypt the vault SK with the wrapper key, store the wrapped blob in Supabase as a sibling column. Recovery flow on a new device: enter passphrase → fetch wrapped blob → unwrap → restore SK to Keychain | SHOULD | ⏸ DEFERRED | not designed visually; comes from `app/README.md:97-100` admitting the gap | new `app/src/lib/recovery.ts`, edits to `vault.tsx`, new `(onboarding)/recovery.tsx` |

### Acceptance criteria

- Settings → Bot section: hitting Test connection actually pings the bot
  and updates the row's right side with ✓ OK or ✗ error.
- Settings → Notifications: toggles persist across app restarts (the
  prefs are stored, even if APNs delivery isn't wired).
- Settings → Account → Sign out: red row, hold-pattern OR confirm dialog,
  signs out cleanly.
- Vault recovery: on a fresh device, signing in then entering the
  passphrase rehydrates the SK in Keychain and the API key blob decrypts
  correctly. Without the passphrase, the user sees the "Reconnect bot"
  empty state from Pass 1's items.

### Verification

```powershell
cd C:\git\aribot-og\app; npx tsc --noEmit
cd C:\git\aribot-og\app; npx expo export --platform web --output-dir .expo-smoke
Remove-Item -Recurse -Force .expo-smoke
```

Manual: install on a second test device (or sign out + clear app data on
the primary), enter the recovery passphrase, confirm the vault rehydrates.

### Risk callouts

- **Argon2id is not in pure JS** — `tweetnacl` doesn't include it. Options:
  (a) use `argon2-browser` if it works in RN (it doesn't reliably);
  (b) use `scrypt` from `noble-hashes` (pure JS, works in RN). Pick scrypt
  with high-but-reasonable parameters (N=2^14, r=8, p=1).
- **Don't store the passphrase anywhere.** Only the wrapped SK lives in
  Supabase. The passphrase is user-memory-only.
- **Recovery UX must be unambiguous** — the user MUST understand "lose this
  passphrase = lose your keys forever, but not your real money on Bybit."
- **Settings refactor is large.** Don't try to make every section
  pixel-perfect to the design in the same commit. Land them one section at
  a time, typecheck between.
- **`expo-constants`** is already a dep; `Constants.expoConfig?.version`
  and `Constants.nativeBuildVersion` give you the footer values.
- **Notifications without APNs delivery** is a half-measure. Clearly mark
  this in the audit's next update — toggles persist, but they don't actually
  receive pushes yet.

### Boundaries — do NOT

- Do NOT implement APNs registration here. Pass 5 or beyond.
- Do NOT add the LIVE sheet KV summary (out of scope per locked-in decision).
- Do NOT touch Pass 1's kill switch or Pass 2's mode switcher except via
  the new `Row` primitive if it naturally fits.
- Do NOT add a `/config` endpoint here. Stays out of scope.
- Do NOT introduce a new crypto dep beyond `noble-hashes` (or whichever
  pure-JS scrypt you settle on).
- Do NOT change the dashboard.

---

## Pass 5 — Internal reference docs (OPTIONAL)

**NICE tier. Optional. Skip if the team doesn't want internal docs in-app.**

### Goal

The design package ships six reference deliverables (mascot sheet,
component sheet, palette swatch, type scale, two flow diagrams) intended
to communicate the design system to engineers. They're not user-facing
screens, but having them rendered in-app gives the team a live source of
truth that can't drift away from the actual code (because it imports the
actual components).

This pass adds a hidden `(dev)` route group with one screen per
deliverable, gated behind a dev-only entry on the Settings → About row.

### Items

| # | Item | Tier | Design source | Impl target |
|---|---|---|---|---|
| 5.1 | Dev-only entry point: long-press the Settings version footer 5 times to unlock a `(dev)` route | NICE | — | `app/app/(app)/settings.tsx` |
| 5.2 | **Mascot sheet** — renders the 11 poses in a grid with labels, plus the MascotSlot in all 6 tones, plus the 4 MProps | NICE | `mascot.jsx`, `design-canvas.jsx MascotSheet` | new `app/app/(dev)/mascot.tsx` |
| 5.3 | **Component sheet** — every primitive (`Btn`, `StatusPill`, `ModeChip`, `SideChip`, `Input`, `Money`, `Card`, `Sparkline`, `PositionRow`, `Icon`, `Toggle`, `Segmented`, `KillButton`, `KV`, `Row`, `SectionLabel`) rendered with all variants | NICE | `design-canvas.jsx ComponentSheet` | new `app/app/(dev)/components.tsx` |
| 5.4 | **Palette sheet** — every color in `tokens.ts` as a labeled swatch grid, with the "PnL reservation rule" called out | NICE | `design-canvas.jsx PaletteSheet` | new `app/app/(dev)/palette.tsx` |
| 5.5 | **Type scale** — every text size in `TYPE` from `tokens.ts` with sample text | NICE | `design-canvas.jsx TypeSheet` | new `app/app/(dev)/typography.tsx` |
| 5.6 | **Flow diagrams** — two static SVGs ported from the design's `FlowDiagram` component, one for onboarding, one for start-bot | NICE | `design-canvas.jsx FlowDiagram` | new `app/app/(dev)/flow-onboarding.tsx`, `app/app/(dev)/flow-start-bot.tsx` |
| 5.7 | **Trust-moment annotated** — the API vault screen with the design's `TrustAnnotations` overlay | NICE | `screens-onboarding.jsx TrustAnnotations:289-307` | new `app/app/(dev)/trust-moment.tsx` |

### Acceptance criteria

- Long-press Settings version footer 5 times → a hidden "Dev tools" row
  appears for the current session.
- Each (dev) screen renders without errors and is navigable.
- The mascot sheet uses the **real** `Bear` component, not a re-drawn one.
  If the bear changes, the sheet updates automatically.
- The palette and type sheets import directly from `tokens.ts` — if a token
  is added or removed, the sheet reflects it.

### Verification

```powershell
cd C:\git\aribot-og\app; npx tsc --noEmit
cd C:\git\aribot-og\app; npx expo export --platform web --output-dir .expo-smoke
Remove-Item -Recurse -Force .expo-smoke
```

### Risk callouts

- **Dev routes must NOT leak into production builds** without being gated.
  Even with the long-press unlock, the bundle includes them. That's
  acceptable for an internal app; if you ever ship to TestFlight publicly,
  add an `__DEV__` guard so the (dev) group is tree-shaken out.
- **The flow diagrams in the design are 1100×420 / 1100×580 px.** They
  won't fit on a phone in portrait. Either shrink-to-fit or pan/zoom.
- **The trust-moment annotated screen overlays callouts on a real
  `ApiVault` instance.** Don't duplicate the vault component — wrap it.
- **Importing every primitive in one screen** stresses the bundler; the
  component sheet might be the biggest single file in the app. That's fine.

### Boundaries — do NOT

- Do NOT make any (dev) screen do real I/O — no actual Supabase calls,
  no real `/start`, no bot connection writes.
- Do NOT ship this pass without the long-press unlock. Visible "Dev tools"
  entry in Settings clutters the user-facing screen.
- Do NOT use this pass as an excuse to refactor primitives. The reference
  sheets exist to display what's there, not to drive design changes.

---

## Pass ordering rationale

1. **Pass 1 first** because the kill switch is the design's load-bearing
   safety affordance and "host-down / kill-active" are the states where the
   absence of the mascot most damages the brand.
2. **Pass 2 next** because mode switching is the only ops task users
   currently can't do from the app, and the missing primitives unblock
   Pass 4.
3. **Pass 3** for visual fidelity once the functional gaps are closed.
4. **Pass 4** for the long-tail Settings completion + the recovery story.
5. **Pass 5** is optional and not on the critical path.

If a pass is skipped or only partially done, **the next pass should still
work** — each pass is self-contained. Pass 4 in particular references
primitives Pass 2 extracts, so if Pass 2 is skipped, Pass 4 will need to
extract them itself or be reordered.
