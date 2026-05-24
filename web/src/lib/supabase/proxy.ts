import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

/**
 * Used by /src/proxy.ts on every request to:
 *  1. Refresh the Supabase session (so server reads see a fresh access token)
 *  2. Decide whether the user is authenticated, for auth-gated routes
 *
 * Returns { response, user } so the caller can layer redirect logic on top.
 * IMPORTANT: always return the `response` produced here — it carries the
 * refreshed cookies. Building a new NextResponse from scratch will drop them.
 */
export async function updateSession(request: NextRequest) {
  let response = NextResponse.next({
    request: { headers: request.headers },
  });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value }) =>
            request.cookies.set(name, value),
          );
          response = NextResponse.next({ request });
          cookiesToSet.forEach(({ name, value, options }) =>
            response.cookies.set(name, value, options),
          );
        },
      },
    },
  );

  // getClaims() validates the JWT locally (or via the JWKS endpoint) and
  // returns verified claims without an Auth-server round trip on every
  // request. Safer than getSession() for auth decisions, faster than
  // getUser() for proxy hot-path.
  const { data } = await supabase.auth.getClaims();

  return { response, user: data?.claims ?? null };
}
