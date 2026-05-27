import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { OnboardingCarousel } from "./carousel";

export const dynamic = "force-dynamic";

/**
 * First-run carousel — three slides walking the user through:
 *   1. What Aribot does
 *   2. Bring-your-own Bybit keys + the encryption pitch
 *   3. PAPER / SHADOW / LIVE mode safety
 *
 * Routes here right after sign-up via /auth/confirm (and as a link from
 * the dashboard the first time the user lands there with no vault).
 * Pattern from design-pkg/screens-onboarding.jsx:104-185.
 */
export default async function OnboardingPage() {
  const supabase = await createClient();
  const { data } = await supabase.auth.getUser();
  if (!data.user) redirect("/sign-in");

  return <OnboardingCarousel />;
}
