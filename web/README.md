# Aribot web

Next.js 16 web app for `aribot.app`. Talks to `https://api.aribot.app`
(the multi-tenant FastAPI sidecar) and uses Supabase for auth.

## Stack

- **Framework:** Next.js 16 (App Router, "Proxy" file convention)
- **UI:** Tailwind v4 + Aribot design tokens (ported from `app/src/theme/tokens.ts`)
- **Auth:** Supabase via `@supabase/ssr` (cookie-based sessions, refreshed
  in `src/proxy.ts` on every request)
- **Validation:** Zod
- **Forms:** Server Actions + `useActionState`
- **Crypto (M3+):** WebCrypto SubtleCrypto (X25519 + AES-GCM)

## Milestones

| Milestone | Scope | Status |
|---|---|---|
| **M1** | Landing + sign-up + sign-in + auth-gated dashboard placeholder | shipped |
| M2 | Bot connection setup (host URL + bearer token, stored in Supabase) | pending |
| M3 | Encrypted Bybit API key vault (browser-native WebCrypto) | pending |
| M4 | Live dashboard (positions, equity, today's PnL) | pending |
| M5 | Start / stop / kill switch | pending |
| M6 | History + settings | pending |
| M7 | Polish (loading skeletons, mobile, dark mode) | pending |

## First-time setup

```powershell
# From the repo root, on branch feat/web-frontend
cd web
npm install                       # already done by scaffolder
copy .env.example .env.local
notepad .env.local                # fill in Supabase URL + anon key
npm run dev                       # http://localhost:3000
```

Get your Supabase values from:
- **Project Settings -> API**:
  - `NEXT_PUBLIC_SUPABASE_URL` <- Project URL
  - `NEXT_PUBLIC_SUPABASE_ANON_KEY` <- anon public key

Use the **same Supabase project** the backend validates against, so JWTs
issued here are accepted by `https://api.aribot.app` in later milestones.

## File layout

```
web/
  src/
    app/
      layout.tsx              # root layout
      page.tsx                # / -- landing page
      globals.css             # Tailwind v4 + Aribot tokens
      actions/
        auth.ts               # signUp, signIn, signOut server actions
      (auth)/                 # route group -- unauthenticated
        sign-up/{page,form}.tsx
        sign-in/{page,form}.tsx
      (app)/                  # route group -- authenticated
        dashboard/page.tsx    # /dashboard -- protected
    lib/
      auth/
        schemas.ts            # Zod schemas
      supabase/
        client.ts             # browser client
        server.ts             # server client (cookies via next/headers)
        proxy.ts              # cookie-refresh helper for the proxy
    proxy.ts                  # Next.js 16 proxy (= old "middleware")
                              # Refreshes session, gates /dashboard
  .env.example                # copy to .env.local and fill in
  next.config.ts
  package.json
```

## Auth model

1. User signs up -> Supabase emails a confirmation link (depending on
   your project's email settings).
2. After confirm, they can sign in. Supabase sets `sb-*` cookies on
   `aribot.app`.
3. On every request, `src/proxy.ts` calls `getClaims()` to verify the JWT
   locally (or via the JWKS endpoint -- no Auth-server round trip per
   request) and refreshes the access token if needed.
4. Auth-gated routes (`/dashboard*`) get a server-side redirect to
   `/sign-in` for unauth'd users.
5. Auth-only routes (`/sign-in`, `/sign-up`) redirect to `/dashboard` for
   signed-in users.
6. Server Components do their own `getUser()` check before rendering
   sensitive data -- proxy is a fast filter, not the security boundary.

## What this milestone deliberately doesn't have

- **shadcn/ui:** raw Tailwind for now. Add later if component complexity
  warrants it.
- **Email confirmation UX:** Supabase's default email is used. M7 polish
  will add a custom template + a "check your email" landing state.
- **OAuth (Google, GitHub):** email/password only for M1.
- **Forgot password:** ships in M7.
- **Light/dark theme:** light-only for now.
- **Deployment:** local-only. Cloudflare Pages setup happens after M1
  review.
