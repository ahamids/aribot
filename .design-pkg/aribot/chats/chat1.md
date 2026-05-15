# Chat

_Started 2026-05-11 17:23 UTC_

---

## User

<system-info comment="Only acknowledge these if relevant">
Project title is now "aribot"
Current date is now May 11, 2026
</system-info>

<default aesthetic>
If no references, art direction or design systems were provided, use this default professional modern, minimal aesthetic as a base. Declare your choice out loud so you stick to it. Guidance:
- Choose a type pairing from web-safe set or Google Fonts. Helvetica is a good choice. Avoid hard-to-read or overly stylized fonts. Use 1-3 fonts only.
- Foreground and background: choose a color tone (warm, cool, neutral, something in-between). Use subtly-toned whites and blacks; avoid saturations above 0.02 for whites.
- Accents: choose 0-2 additional accent colors using oklch. All accents should share same chroma and lightness; vary hue.
- NEVER write out an SVG yourself that's more complicated than a square, circle, diamond, etc.
- For imagery, never hand-draw SVGs; use subtly-striped SVG placeholders instead with monospace explainers for what should be dropped there (e.g. “product shot”)

CRITICAL: ignore default aesthetic entirely if given other aesthetic instructions like reference images, design systems or guidance, or if there are files in the project already.
</default aesthetic>

<pasted_text name="Pasted text (195 lines)">
Design an iOS app called "Aribot" — a playful cartoon-styled mobile companion for a
Bybit perpetuals crypto trading bot that the user runs on their own server. The
visual language is inspired by mobile puzzle games like Toon Blast: chunky rounded
shapes, thick outlines, saturated candy palette, soft drop shadows, a friendly
mascot character (use a placeholder bear — it will be replaced by a custom-designed
character later). The twist: it's a real-money trading control surface, so playful
chrome wraps trustworthy data. Bouncy frames, serious numbers.

═══════════════════════════════════════════════════════════════════════════════
PRODUCT CONTEXT (so you design the right thing, not a generic app)
═══════════════════════════════════════════════════════════════════════════════

The user already has a Python trading bot ("Aribot") running on their own VPS that
trades Bybit USDT perpetual swaps on a 4-hour strategy. The bot supports three
modes: `paper` (simulation), `shadow` (authenticated, dry-run orders), `live`
(real orders). It has a kill-switch mechanism. Today it's controlled from the
command line — this iOS app is the user-friendly front end.

Backend architecture (out of scope to design, but shapes the screens):
- Supabase handles auth (email + password, optional magic link) and stores per-user
  profile + an encrypted blob of their Bybit API keys (sealed-box ciphertext;
  Supabase cannot decrypt). The private decryption key lives in iOS Keychain.
- The bot itself exposes a small HTTPS API on the user's VPS: /start, /stop,
  /status, /positions, /trades. The iOS app talks to that API directly, bearer-
  authenticated with a token the user pastes during onboarding.

═══════════════════════════════════════════════════════════════════════════════
SCREENS TO DESIGN (Phase 1)
═══════════════════════════════════════════════════════════════════════════════

1.  SPLASH / WELCOME
    Mascot front and center, app name, "Sign in" / "Create account" buttons.
    Establishes the cartoon tone immediately.

2.  SIGN UP  +  3. SIGN IN
    Supabase email/password. Friendly form fields with chunky rounded inputs.
    Mascot reacts (waves on sign-up screen, peeks on sign-in).

3.  ONBOARDING CAROUSEL (3 cards)
    Card A — "Connect your bot": explain BYO-host, where to paste the bot's URL +
             bearer token. Show a labeled illustration of "your server <-> app".
    Card B — "Add your Bybit keys": explain that keys are encrypted on-device,
             stored as ciphertext, only the user can decrypt. Trust framing.
    Card C — "Pick a mode": paper / shadow / live, with one-line explanations
             and a clear warning on `live`.

4.  BOT CONNECTION SETUP
    Two fields: Host URL, Bearer Token. "Test connection" button that pings
    /status and shows a success state (mascot gives a thumbs up) or an error.

5.  API KEY VAULT
    Four fields: Read API key, Read secret, Trade API key, Trade secret.
    Show/hide eye toggles. Clear copy: "Encrypted on this device before upload.
    Even we can't see these." Save button. Show a locked-vault illustration.

6.  HOME / DASHBOARD  (the primary screen — most thought goes here)
    Top section — STATUS CARD
      - Mascot in a state matching the bot: sleeping (stopped), alert/eyes-open
        (running), panicked (kill-switch tripped or error).
      - Status pill: RUNNING / STOPPED / ERROR, with mode tag (PAPER/SHADOW/LIVE).
      - Last heartbeat timestamp ("Last cycle 2m ago"), small and quiet.
      - Big primary action button: START (when stopped) / STOP (when running).
        Bouncy press animation. Confirmation sheet for LIVE mode start.

    Middle section — TODAY'S PNL
      - One large tabular number (SF Pro Rounded, tabular figures).
      - Green if positive, red if negative — these are the only two reds/greens
        in the app; reserve them for PnL/direction only.
      - Small sparkline of equity over the last 24h beneath it.

    Bottom section — OPEN POSITIONS (preview, up to 3)
      - Each row: symbol, side chip (LONG green / SHORT red), size, entry,
        mark, unrealized PnL.
      - "See all" link to full Positions screen.

    Tab bar at the bottom: Home · Positions · History · Settings.

7.  POSITIONS (full screen)
    Scrollable list of open positions. Each card shows the same fields as the
    home preview but with more room: entry time, leverage, liquidation price,
    a small per-position PnL sparkline. Pull-to-refresh.

8.  HISTORY
    Two views toggle at the top — "Trades" (list of closed trades, most recent
    first, with realized PnL color-coded) and "Equity" (a 7-day equity curve
    chart, soft cartoon-styled axes but accurate data).

9.  SETTINGS
    - Account (email, sign out)
    - Bot connection (re-enter host URL / token, test connection)
    - API keys (re-enter, with explicit re-encryption flow)
    - Mode switcher (paper / shadow / live with the live-mode warning)
    - Kill switch (big red toggle, gated by a hold-to-confirm gesture so you
      can't trip it by accident)
    - Notifications (toggles for fill alerts, error alerts, daily summary)
    - About / version

10. EMPTY + ERROR STATES
    For each main screen, design at least one empty state and one error state,
    each featuring the mascot in a relevant pose:
      - No positions yet → mascot napping
      - No trades yet → mascot reading a chart upside down
      - Bot host unreachable → mascot holding a disconnected cable
      - Kill switch active → mascot waving a red flag
      - Auth error → mascot scratching head with a "?"

═══════════════════════════════════════════════════════════════════════════════
VISUAL & INTERACTION GUARDRAILS — READ THESE TWICE
═══════════════════════════════════════════════════════════════════════════════

Aesthetic targets:
- Chunky 24–32pt corner radii on cards and buttons.
- Thick 3–4pt outlines on hero elements (the start/stop button, the mascot frame,
  the status pill). Subtler on dense data rows so the screen doesn't get noisy.
- Layered drop shadows: a soft ambient shadow + a small offset hard shadow to give
  the "sticker" / "puzzle piece" feel.
- Soft inner highlights on buttons to suggest a glossy plastic-toy surface.
- Cream/peach background (#FFF4E6 or similar warm off-white), not pure white.
- Accent palette: warm coral, sunny yellow, mint, periwinkle, deep plum for text.
- Reserve PURE red (#E5484D-ish) and PURE green (#30A46C-ish) EXCLUSIVELY for PnL,
  direction, and the kill switch. Never use them decoratively. This is the rule
  that keeps the cartoon styling from undermining trust.

Typography:
- Display & UI: SF Pro Rounded.
- Numbers (PnL, prices, sizes, percentages): SF Pro Rounded with tabular figures
  enabled. Numbers must align vertically in lists. Generous size on hero numbers
  (≥40pt for today's PnL, ≥28pt for position PnL).

Mascot rules:
- Placeholder is a friendly cartoon bear, but design it as a SLOT — the character
  will be swapped later. Provide a reusable container/frame the new character
  will drop into.
- Expressions used: sleeping, alert, panicked, thumbs-up, scratching head,
  napping, holding a sign/flag. Show these poses on a sheet.
- Mascot never appears inside data-dense regions. It lives in headers, empty
  states, onboarding, and the dashboard status card.

Motion:
- Chrome (buttons, cards, mascot transitions): bouncy spring animations,
  scale-down-on-press, slight wobble.
- Data updates (price ticks, PnL changes, new positions): fade/crossfade or
  number-morph. NEVER bounce the digits. Bouncing money feels unsafe.

Safety affordances:
- Starting LIVE mode requires a confirmation sheet with the mascot looking
  serious, a summary of "what's about to happen", and a typed confirmation
  ("type LIVE to confirm") or a slide-to-confirm gesture.
- The kill switch is a hold-to-activate toggle (1.5s press), not a tap.

Accessibility:
- All text meets WCAG AA against the cream background.
- The cartoon aesthetic must NOT rely on color alone for status — pair every
  color signal with an icon, label, or shape change (e.g., the running/stopped
  pill changes both color AND text AND icon).
- Dynamic Type support — show how the dashboard reflows at the largest
  accessibility size.
- VoiceOver labels called out for non-obvious icons (mascot states, kill switch).

═══════════════════════════════════════════════════════════════════════════════
DELIVERABLES
═══════════════════════════════════════════════════════════════════════════════

1. Full-fidelity mockups of every screen listed above (mobile portrait, iPhone
   15/16 frame).
2. A component sheet: buttons (primary/secondary/destructive), input fields,
   status pills, position cards, trade row, mascot states, tab bar, segmented
   controls.
3. The mascot expression sheet (8+ poses) plus the reusable "mascot slot"
   container.
4. Color palette swatch with hex values and usage rules (especially the
   red/green reservation rule).
5. Type scale: every text size used in the app, with its weight and tabular-
   figure setting.
6. Two flow diagrams:
   a. Onboarding flow (Welcome → Sign up → Bot connection → API keys → Mode
      pick → Dashboard).
   b. Start-bot flow including the LIVE-mode confirmation gate.
7. One annotated "trust moment" screen — show, with callouts, how the API key
   vault screen visually communicates that keys are encrypted client-side and
   the server can't read them. This is the screen where the cartoon style most
   risks undermining trust; prove the design solves it.
8. Dark mode variants for Home, Positions, History (the cream/peach base
   becomes a warm dark base — not pure black; preserve the "warm" feel).

Do NOT design:
- The Supabase database schema or backend API (that's a separate engineering
  task; just respect the contract described above).
- A web/admin dashboard. iOS only.
- A multi-tenant host-management UI. BYO host only in Phase 1.

When you present, lead with the dashboard — that's the screen the user sees
every day, and it's where the "playful frame, serious numbers" thesis either
works or doesn't.

</pasted_text>

<!-- The user explicitly selected the following skills for this project, as attachments to their message. These are not optional context — they define how you work. Use them. -->
<attached-skill name="Hi-fi design">
Create a high-fidelity, polished design. Follow the instructions about design in your system prompt, particularly the 'How to do design work' section. Use the design_canvas starter component, or make a full-bleed prototype and offer options via Tweaks.
</attached-skill>

<attached-skill name="Interactive prototype">
Create a fully interactive prototype with realistic state management and transitions. Use React useState/useEffect for dynamic behavior. Include hover states, click interactions, form validation, animated transitions, and multi-step navigation flows. It should feel like a real working app, not a static mockup.
</attached-skill>


<system-reminder>Auto-injected reminder (ignore if not relevant): do not recreate copyrighted or branded UI unless the user's email domain matches that company. Create original designs instead.</system-reminder>

## Assistant

_[tool: update_todos]_

_[tool: copy_starter_component]_

_[tool: copy_starter_component]_

_[tool: read_file]_

_[tool: read_file]_

_[tool: snip]_

_[tool: write_file]_

I'll commit to the system up front, then build it out.

**Design system commitment:**
- **Palette**: cream base `#FFF4E6`, warm card `#FFE9C9`, dark plum text/outline `#2D1F47`, coral `#FF8B66`, sunny yellow `#FFC93C`, mint `#7DD3AE`, periwinkle `#8B9DFF`. PnL-only red `#E5484D` and green `#30A46C` — never decorative.
- **Type**: SF Pro Rounded throughout, tabular figures on numbers.
- **Sticker shadows**: ambient blur + hard offset shadow under everything that matters.
- **Mascot**: rounded bear placeholder with swappable expression slot.

Now writing the system as a set of small JSX modules.

_[tool: write_file]_

Now the mascot — placeholder bear with multiple poses, designed as a swappable slot.

_[tool: write_file]_

_[tool: snip]_

_[tool: write_file]_

_[tool: snip]_

_[tool: write_file]_

Now the dashboard — the lead screen.

_[tool: snip]_

_[tool: write_file]_

_[tool: snip]_

_[tool: write_file]_

_[tool: snip]_

_[tool: write_file]_

_[tool: snip]_

_[tool: write_file]_

_[tool: snip]_

_[tool: write_file]_

_[tool: write_file]_

_[tool: snip]_

_[tool: done]_

_[tool: fork_verifier_agent]_

Done. The Aribot iOS design is live at **Aribot iOS Design.html** — open the canvas to pan/zoom across all sections.

**What's included:**
- **Dashboard** (lead) — 6 states: running/PAPER, running/LIVE, stopped, error, kill-tripped, Dynamic Type XXL
- **Onboarding** — splash, sign-up, sign-in, 3-card carousel, bot connection (idle/✓/error), API key vault
- **Main app** — Positions, History (trades + equity views), Settings, LIVE-mode confirm sheet
- **Empty + error states** — 6 mascot-led variations
- **Dark mode** — Dashboard, Positions, History (warm dark, not black)
- **Trust moment** — annotated API vault with callouts
- **Design system** — mascot expression sheet (10 poses + slot + props), component sheet, palette with reserved-PnL rule, type scale, onboarding + start-bot flow diagrams

**System notes:**
- Cream/peach base `#FFF4E6`, plum `#2D1F47` for text/outlines, candy accents (coral / yellow / mint / periwinkle); pure red/green strictly reserved for PnL, direction, kill switch, and LIVE warnings
- All numbers are tabular SF Pro Rounded; outline + hard-offset shadow = "sticker" feel
- Mascot is a placeholder bear inside a reusable `MascotSlot` — swap the character art once and every screen picks it up

