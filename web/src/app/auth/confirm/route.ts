import { type NextRequest, NextResponse } from "next/server";
import { type EmailOtpType } from "@supabase/supabase-js";
import { createClient } from "@/lib/supabase/server";

/**
 * Email link confirmation handler.
 *
 * Supabase email templates point here (instead of the default
 * supabase.co URL) so the link the user clicks is on aribot.app — same
 * domain as the From: address, which avoids the spam signal Microsoft
 * flagged on the first test send.
 *
 * Flow:
 *   1. User clicks link in confirmation email -> /auth/confirm?token_hash=...&type=signup&next=/dashboard
 *   2. We verifyOtp -> Supabase sets the session cookie via the SSR client
 *   3. Redirect to ?next (or /dashboard) — proxy.ts will let them through
 *      because the session cookie is now set.
 *
 * On failure we redirect to /sign-in with an error code so the user
 * gets a real page, not a JSON blob.
 */
export async function GET(request: NextRequest) {
  const { searchParams, origin } = request.nextUrl;
  const token_hash = searchParams.get("token_hash");
  const type = searchParams.get("type") as EmailOtpType | null;
  const next = searchParams.get("next") ?? "/dashboard";

  if (!token_hash || !type) {
    return NextResponse.redirect(`${origin}/sign-in?error=invalid_link`);
  }

  const supabase = await createClient();
  const { error } = await supabase.auth.verifyOtp({ type, token_hash });

  if (error) {
    return NextResponse.redirect(
      `${origin}/sign-in?error=${encodeURIComponent(error.message)}`,
    );
  }

  // Only allow same-origin next paths — never redirect to an external
  // host even if it ends up in the query string somehow.
  const safeNext = next.startsWith("/") && !next.startsWith("//") ? next : "/dashboard";
  return NextResponse.redirect(`${origin}${safeNext}`);
}
