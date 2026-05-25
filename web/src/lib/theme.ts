import { cookies } from "next/headers";

export type Theme = "light" | "dark";
export const THEME_COOKIE = "aribot-theme";
export const THEME_COOKIE_MAX_AGE = 60 * 60 * 24 * 365; // 1y

/**
 * Server-side: read the theme cookie. Defaults to "light" if absent or
 * malformed. Called from the root layout to set <html data-theme="...">,
 * so the first paint matches the user's persisted choice (no flash of
 * unstyled content on navigation).
 */
export async function readTheme(): Promise<Theme> {
  const store = await cookies();
  const raw = store.get(THEME_COOKIE)?.value;
  return raw === "dark" ? "dark" : "light";
}
