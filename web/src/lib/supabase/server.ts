import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

/**
 * Supabase client for use in Server Components, Server Actions, and Route
 * Handlers. Reads/writes the session cookie via next/headers cookies().
 *
 * Note the try/catch around setAll: Server Components can call this but are
 * NOT allowed to mutate cookies. The proxy refreshes the session on each
 * request before any Server Component renders, so failing silently here is
 * fine — by the time a Server Component runs, the cookie is already fresh.
 */
export async function createClient() {
  const cookieStore = await cookies();

  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
          try {
            cookiesToSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options),
            );
          } catch {
            // Called from a Server Component (read-only context). Ignore;
            // proxy.ts handles refresh before render.
          }
        },
      },
    },
  );
}
