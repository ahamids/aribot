"use server";

import { cookies } from "next/headers";
import { revalidatePath } from "next/cache";
import { THEME_COOKIE, THEME_COOKIE_MAX_AGE, type Theme } from "@/lib/theme";

export async function setTheme(theme: Theme): Promise<void> {
  const store = await cookies();
  store.set(THEME_COOKIE, theme, {
    maxAge: THEME_COOKIE_MAX_AGE,
    path: "/",
    httpOnly: false,
    sameSite: "lax",
  });
  // Revalidate every route so the next navigation paints with the new
  // theme. The Server Component layout reads the cookie on render to
  // set <html data-theme="...">.
  revalidatePath("/", "layout");
}
