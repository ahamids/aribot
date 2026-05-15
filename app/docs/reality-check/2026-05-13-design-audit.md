# Aribot iOS — design-package vs. implementation audit

**Date:** 2026-05-13
**Auditor:** Reality Checker subagent (independent of prior implementation claims)
**Scope:** Full design package at `.design-pkg/aribot/project/*` against the implemented React Native app at `app/`.
**Posture:** Skeptical. Default to "NOT DONE" unless evidence proves otherwise.

This is a frozen snapshot. Subsequent audits should land beside this file as
`YYYY-MM-DD-design-audit.md` so the trail is preserved.

---

## Top-line

**Coverage: ~55–60% of designed surfaces shipped.**

Of the design's 24 in-app artboards:
- **9 fully implemented**
- **5 partially implemented** (functional but visually downgraded — flat fills where the design has gradients, wrong KV fields, inline cards where the design has full screens)
- **10 missing** (6 are dark-mode variants, 4 are standalone empty/error state screens)

Plus 6 design-time reference deliverables (mascot sheet / component sheet / palette / type scale / two flow diagrams / trust-moment annotation) which are out of the shipping app — see Pass 5 in `PASSES.md`.

**Total gaps: 28** — **9 MUST · 11 SHOULD · 8 NICE.**

---

## What was verified or refuted from prior claims

| Prior claim | Verified? | Notes |
|---|---|---|
| Splash + SignIn + SignUp wired to Supabase | ✅ True | `lib/auth.tsx`, `(auth)/sign-in.tsx`, `(auth)/sign-up.tsx` |
| Onboarding carousel (3 cards) | ✅ True | `(onboarding)/welcome.tsx` |
| Bot setup with /status ping | ✅ True | `pingStatus` in `botApi.ts` |
| API key vault with sealed-box encryption | ✅ True | `lib/crypto.ts` |
| Dashboard with live status, PnL, positions, start/stop, LIVE confirm | ✅ True (but **flat backgrounds vs design gradients**) | `(app)/dashboard.tsx` |
| Positions full screen (Open + Closed segmented) | ⚠️ True with caveats | `LIQ` swapped for `P&L %`, no round refresh button — see "Implemented but worse" |
| History (Trades + Equity) | ✅ True | `(app)/history.tsx` |
| Settings (partial — sign out + reconnect) | ✅ True — and "partial" is doing heavy lifting | `(app)/settings.tsx` |
| Tab bar with 4 tabs | ✅ True | `(app)/_layout.tsx` |
| Mascot with 11 poses | ✅ True — **highest fidelity in the codebase** | `src/mascot/Bear.tsx` |
| Settings mode/kill/notifs/account/about not done | ✅ Confirmed absent | — |
| Empty/error states are inline branches, not standalone | ✅ Confirmed | — |
| Dark mode not implemented | ✅ Confirmed | Grep for `useColorScheme`/`Appearance`/`dark` returns zero relevant hits |
| Magic-link button has no handler | ✅ Confirmed | `sign-in.tsx:92`, `sign-up.tsx:110` |
| Recovery passphrase missing | ✅ Confirmed | README admits it |
| Per-position sparklines from real price history | ✅ Confirmed (2-point entry→mark) | by design, not a regression |
| Real per-cycle equity persistence | ✅ Confirmed (stepped per closed trade) | `EquityChart.tsx:5-9` comments admit this |

The prior assistant's status reports were accurate. The audit's main delta is **classification:** several items the prior assistant called "done" are functionally done but visually downgraded.

---

## Section-by-section punch list

### A. Dashboard (`.design-pkg/aribot/project/screens-dashboard.jsx` → `app/app/(app)/dashboard.tsx`)

| Artboard | Status | Notes |
|---|---|---|
| `dash-running` (PAPER) | ✅ IMPLEMENTED | Status pill, mascot pose, sparkline, stop button — all present |
| `dash-running-live` | ⚠️ PARTIAL | Renders correctly with `mode: LIVE`. No extra-loud "you're in LIVE" affordance beyond chips. |
| `dash-stopped` | ✅ IMPLEMENTED | `creamDeep` gradient rendered as flat fill (see "Implemented but worse") |
| `dash-error` | ⚠️ PARTIAL | Pose flips to `panicked` and pill goes red; gradient is flat. Error reason appended to last-cycle text (design didn't specify that placement) |
| `dash-killed` | ⚠️ PARTIAL | Label "KILL SWITCH ACTIVE" matches; design has a stronger banner, impl just disables the button |
| `dash-large-text` | ❌ MISSING — **SHOULD** | No `dynamicType` opt-in; `bigSize: 64` and 32px greeting are hardcoded |

### B. Onboarding (`.design-pkg/aribot/project/screens-onboarding.jsx` → `app/app/(auth)/` + `app/app/(onboarding)/`)

| Artboard | Status | Notes |
|---|---|---|
| `splash` | ✅ IMPLEMENTED | `app/index.tsx` |
| `signup` | ✅ IMPLEMENTED (mostly) | `(auth)/sign-up.tsx`. Encryption-ack checkbox uses a `Btn` (design has a square coral checkbox). Magic-link text shown but **no handler** |
| `signin` | ✅ IMPLEMENTED | `(auth)/sign-in.tsx`. Magic-link button **does nothing** on press |
| `onb-a/b/c` (3-card carousel) | ✅ IMPLEMENTED | `(onboarding)/welcome.tsx`, paged ScrollView, all three SVG illustrations ported |
| `bot-idle` / `bot-ok` / `bot-err` | ✅ IMPLEMENTED | `(onboarding)/bot-setup.tsx`, all three states |
| `vault` | ✅ IMPLEMENTED | `(onboarding)/vault.tsx` + real Sealed-Box encryption in `crypto.ts` & `vault.ts` |

**Gaps:**
- Magic-link sign-in handler — **MUST** (2 buttons advertise it, both stubs)
- Vault recovery passphrase — **SHOULD** (README admits it; "private key lives in iOS Keychain" with no recovery)

### C. Main app (`.design-pkg/aribot/project/screens-main.jsx` → `app/app/(app)/`)

| Artboard | Status | Notes |
|---|---|---|
| `positions` | ⚠️ PARTIAL | Segmented works, per-card layout matches. **Gaps**: design KV grid has `LIQ` (liquidation price) — impl shows `P&L %`. Design has a round refresh button — impl uses pull-to-refresh only. Sparkline is 2 points (entry→mark) by design |
| `history-trades` | ✅ IMPLEMENTED | Grouped-by-day list, side chip, time, dashed dividers, mascot empty state |
| `history-equity` | ✅ IMPLEMENTED | `EquityChart.tsx` is a faithful port of the design's `<svg>`. Stats grid matches |
| `settings` | ❌ MOSTLY MISSING | **Biggest single gap** — see section K |
| `live-confirm` sheet | ⚠️ PARTIAL | Bottom sheet, serious mascot, type-LIVE-to-confirm, danger CTA all there. **Gap**: design's KV summary card (`MARKET / MAX RISK / LEVERAGE / DAILY CAP`) is replaced by a kill-switch advisory. Title copy drift: design "Start in LIVE mode?" → impl "Real money mode" |

### D. Empty + error states (`.design-pkg/aribot/project/screens-states.jsx`)

The design has **six standalone empty-state screens**, each with a distinct mascot pose, tone, body, and CTA. The implementation replaces all six with inline boilerplate cards.

| Artboard | Status | Notes |
|---|---|---|
| `empty-pos` (no positions) | ⚠️ PARTIAL — **MUST** | Inline `EmptyOpen()` in `positions.tsx:312`. Pose + tone match; no "Wake the bot" CTA; copy diverges |
| `empty-trades` (no trades) | ⚠️ PARTIAL — **SHOULD** | Inline `EmptyTrades()` in `history.tsx:319`. Tone mismatch: design uses `mint`, impl uses `yellow` |
| `err-host` (host unreachable) | ❌ MISSING — **MUST** | Design: `panicked` pose + `cable` MProp + "Retry" CTA. Impl: flat `pnlRedSoft` toast `Card` in `dashboard.tsx:314-339`. No mascot anywhere. Same issue on Positions/History |
| `err-kill` (kill switch active) | ❌ MISSING — **MUST** | Design: `serious` pose + `flag` MProp + "Open settings" CTA. Impl reuses the dashboard with a disabled button; flag MProp never shows |
| `err-auth` (auth error) | ❌ MISSING — **SHOULD** | Design: `questioning` + `yellow` + "Try again" CTA. Impl: inline red `Text` under the password field |
| `empty-chart` (chart loading) | ❌ MISSING — **SHOULD** | Design: `alert` + `yellow` + `chart` MProp. Impl: `ActivityIndicator` + "Loading…" text |

**Pattern:** the design treats these as screens with personality; the impl treats them as inline boilerplate. The mascot — the brand — disappears on every rough day.

### E. Dark mode (`.design-pkg/aribot/project/app.jsx:67-71`)

| Artboard | Status | Notes |
|---|---|---|
| `dark-dash` | ❌ MISSING — **SHOULD** | No `dark` prop, no `useColorScheme`, no `Appearance` |
| `dark-pos` | ❌ MISSING — **SHOULD** | Same |
| `dark-hist` | ❌ MISSING — **SHOULD** | Same |

Tokens **are** ready: `darkBg / darkPaper / darkCard / darkText / darkMid` exist in `app/src/theme/tokens.ts:34-38`. Every screen hardcodes the light palette anyway.

### F. Trust moment + design-system deliverables

| Artboard | Status | Notes |
|---|---|---|
| `trust-annot` (annotated API vault) | ❌ MISSING — **NICE** | Design-time annotation overlay; reasonable to skip in shipping app |
| `mascot-sheet` | ❌ MISSING — **NICE** | Design-time deliverable. Substance (11 poses) is shipped in `Bear.tsx` |
| `components` (component sheet) | ❌ MISSING — **NICE** | Design-time deliverable |
| `palette` (palette swatch) | ❌ MISSING — **NICE** | Design-time deliverable |
| `type` (type scale) | ❌ MISSING — **NICE** | Design-time deliverable |
| `flow-onboarding` & `flow-start-bot` | ❌ MISSING — **NICE** | Flow diagrams; design-time |

These are reference sheets, not shippable iOS screens. **Pass 5 in `PASSES.md` is the optional pass that turns them into in-app internal docs** if you want them.

### G. Components (`.design-pkg/aribot/project/components.jsx` → `app/src/components/`)

| Design primitive | Impl file | Status |
|---|---|---|
| `Btn` (6 kinds × 3 sizes) | `Btn.tsx` | ✅ All 18 combos. Adds press-bounce animation |
| `StatusPill` (4 statuses) | `StatusPill.tsx` | ✅ All four |
| `ModeChip` (3 modes) | `ModeChip.tsx` | ✅ |
| `SideChip` | — | ❌ MISSING as primitive — **MUST**. Open-coded inline in `PositionRow.tsx:48-64`, `positions.tsx:179-206`, `history.tsx:216-228` (three copies) |
| `Input` | `Input.tsx` | ✅ |
| `Money` | `Money.tsx` | ✅ |
| `Card` | `Card.tsx` | ✅ |
| `Sparkline` | `Sparkline.tsx` | ✅ |
| `PositionRow` | `PositionRow.tsx` | ✅ |
| `TabBar` | `(app)/_layout.tsx` (inline) | ✅ Integrated with Expo Router's `Tabs` — correct |
| `Icon` (15 names) | `Icon.tsx` | ✅ All 15 + `back` + `eyeOff` |
| `Toggle` | — | ❌ MISSING — **MUST**. Used by Settings → Notifications |
| `Segmented` | `Segmented.tsx` | ✅ |
| `KV` (helper) | `KV.tsx` | ✅ |
| `KillButton` (hold-1.5s pill) | — | ❌ MISSING — **MUST**. Design specifies 1.5s hold with `scaleX` progress fill. Impl ships `Alert.alert` confirm (tap), not a hold gesture |

### H. Mascot (`.design-pkg/aribot/project/mascot.jsx` → `app/src/mascot/Bear.tsx`)

Design defines **11 poses**: `sleeping, napping, panicked, sad, questioning, serious, wink, alert, thumbsup, waving, happy`.

`Bear.tsx` enumerates the same 11 via its `BearPose` union (`Bear.tsx:20-31`). Pose-by-pose SVG paths in `Eyes/Mouth/Arms/Extras` are **near byte-identical** to the JSX.

`MascotSlot` matches (`tone → bg color`, circle frame with `ol4` border, ambient + sticker shadows). `MProp` ports all four kinds (`flag/cable/chart/vault`).

✅ **No gap.** This is the prior implementation's biggest win — `MProp.flag` and `MProp.cable` are shipped even though no current screen uses them, because they belong to the missing empty-state screens.

### I. Screen shell

Design's `Screen` renders a fake iOS status bar and home indicator (because it's a design canvas). Impl `Screen.tsx` uses `SafeAreaView` and skips both — **correct** for a real device. ✅

### J. iPhone frame (`ios-frame.jsx`)

Design-canvas chrome (rounded bezel, Dynamic Island). Impl correctly does NOT render a frame. ✅ Nothing to do.

### K. Settings — special-case (this is the biggest gap)

Design's Settings (`screens-main.jsx:150-205`) has **five sections** in this exact order:

1. **ACCOUNT** — `Email`, `Plan`, `Sign out` (red row)
2. **BOT** — `Host URL`, `Bearer token` (masked), `Test connection` row with green ✓ OK
3. **MODE** — three `ModeChip` (PAPER active, SHADOW, LIVE) + red LIVE-warning card
4. **SAFETY** — `Kill switch` row with hold-1.5s `KillButton`
5. **NOTIFICATIONS** — `Fill alerts`, `Error alerts`, `Daily summary` toggles

Plus `SectionLabel` + `Row` primitives and a version footer "Aribot · v1.0.0 · build 24".

Impl `app/app/(app)/settings.tsx` has **three cards**:
1. ACCOUNT — email text only (no Plan, no red Sign-out row)
2. BOT CONNECTION — Reconnect button only (no host/token/test rows)
3. SESSION — Sign-out button

Plus an explicit footer that admits: *"Mode switcher · kill switch · notifications · about / all coming in a later pass"* (`settings.tsx:88-91`).

**Settings gaps:**
- Mode switcher (3-chip + warning card) — **MUST**
- Kill switch (hold-1.5s) — **MUST**
- Notifications (3 toggles + push plumbing) — **SHOULD**
- Account: Plan + red Sign-out row pattern — **SHOULD**
- About / version footer — **NICE**
- `SectionLabel` + `Row` primitives — **SHOULD**

---

## Implemented but worse than design

Things that *technically* ship but visually compromise the design:

1. **Dashboard status card backgrounds** — design uses `linear-gradient(180deg, <tone>, paper 70%)`. Impl uses flat `backgroundColor`. Card flattens against the screen.
2. **Positions card `LIQ` field** — design shows liquidation price; impl shows P&L % (the bot doesn't store liq price; upstream gap).
3. **LIVE confirm sheet title and KV summary** — see section C.
4. **Sign-up encryption-ack checkbox** — design uses a square coral checkbox; impl uses a `Btn`.
5. **Empty/error states** — design has 6 standalone screens with mascots; impl has 6 inline cards mostly without mascots.

---

## The single biggest gap

**The entire Settings tab.** Three of five design sections (Mode, Safety/Kill switch, Notifications) are completely absent. The two that exist are stubs that don't match the design's row-based pattern. And critically — **the kill switch is not implemented anywhere in the app at all**, despite being the design's single most-emphasized safety affordance. A trading app whose UI cannot kill the bot from the user's pocket is, in the design's own framing, undermining trust.

## The single most surprising thing the prior implementation got right

**The mascot.** All 11 poses ported at near byte-fidelity; `MascotSlot` is a real swappable abstraction; `MProp` ships all four accessories — even `flag` and `cable` which no current screen uses (because the screens that would use them aren't built yet). The dev did the components-tier work even when no screen demanded it. That's craftsmanship.

---

## MUST / SHOULD / NICE consolidated list

### MUST (9)

1. Settings → Mode switcher (3-chip + LIVE warning card)
2. Settings → Kill switch (hold-1.5s `KillButton` component)
3. Standalone host-down empty state with `panicked` mascot + `cable` MProp + Retry CTA
4. Standalone kill-active empty state with `serious` mascot + `flag` MProp + Open-Settings CTA
5. Standalone no-positions empty state with `napping` mascot + Wake-the-bot CTA (replaces inline `EmptyOpen`)
6. `SideChip` extracted as a primitive (currently inlined three times)
7. `Toggle` primitive (needed by Settings → Notifications)
8. Magic-link sign-in handler (button exists in two places, no handler)
9. LIVE confirm sheet title fix ("Start in LIVE mode?") — KV summary explicitly dropped per scope decision

### SHOULD (11)

10. Dark mode for Dashboard
11. Dark mode for Positions
12. Dark mode for History
13. Dashboard `dynamicType` Dynamic-Type XXL pass
14. Dashboard status-card vertical gradients (currently flat)
15. Settings → Notifications (3 toggles + push plumbing)
16. Settings → Account: Plan row + red Sign-out row pattern
17. Settings → `SectionLabel` + `Row` primitives
18. Standalone auth-error empty state with `questioning` mascot
19. Standalone chart-empty empty state with `alert` mascot + `chart` MProp
20. Vault recovery passphrase (or equivalent SK recovery)

### NICE (8)

21. Settings version footer
22. Positions round refresh button
23. Trust-moment annotated screen (design-time only)
24. Mascot reference sheet (design-time)
25. Component reference sheet (design-time)
26. Palette reference sheet (design-time)
27. Type-scale reference sheet (design-time)
28. Flow diagrams (onboarding + start-bot, design-time)

---

## Scope decisions captured during planning

During the planning conversation that turned this audit into `PASSES.md`, three concrete decisions were made:

1. **LIVE confirm sheet KV summary (MARKET / MAX RISK / LEVERAGE / DAILY CAP):** **dropped from this scope.** The bot doesn't have a `/config` endpoint to source the values truthfully; adding hardcoded copy would be aspirational. The type-LIVE-to-confirm gate remains. Re-add the KV summary when a `/config` endpoint exists.
2. **Kill-switch endpoints:** **add `POST /kill` + `DELETE /kill`** to the sidecar. Distinguishes "stop cleanly at next cycle" (existing `POST /stop`) from "kill switch tripped; refuses to start until cleared" (new `POST /kill`). The clear endpoint matches the design's "Open Settings to clear" CTA.
3. **Empty/error state composition:** **real mascot cards in each screen**, not full-screen takeovers. Each screen renders its own data when it can and falls back to a mascot card when it can't. Doesn't match the design's full-screen empty states but is operationally simpler and avoids losing context.

---

## Production readiness

**NEEDS WORK.** Two revision passes minimum to ship credibly:

- Pass 1 brings the kill switch + the host-down/kill-active mascot states — the gaps that materially affect trust.
- Pass 2 brings the mode switcher + missing primitives + LIVE sheet cleanup — the gaps that materially affect daily use.

Three more (Passes 3/4/5) are polish + completion + optional internal docs.

See `PASSES.md` at the repo root for the full plan.
