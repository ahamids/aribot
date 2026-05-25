import type { Metadata } from "next";
import "./globals.css";
import { readTheme } from "@/lib/theme";

export const metadata: Metadata = {
  title: "Aribot — Crypto trading bot",
  description:
    "Multi-tenant crypto trading bot. Bring your own Bybit keys, your bot, your rules.",
};

export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const theme = await readTheme();
  return (
    <html
      lang="en"
      data-theme={theme}
      className="h-full antialiased"
      // suppress hydration warnings on data-theme: it changes server-side
      // when the cookie flips, which is intentional. Without this, React
      // logs a hydration mismatch on the first paint after a theme switch.
      suppressHydrationWarning
    >
      <body className="min-h-full flex flex-col bg-cream text-plum">
        {children}
      </body>
    </html>
  );
}
