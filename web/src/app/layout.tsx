import type { Metadata } from "next";
import "./globals.css";
import { readTheme } from "@/lib/theme";

export const metadata: Metadata = {
  title: "Aribot — Crypto trading bot",
  description:
    "Multi-tenant crypto trading bot. Bring your own Bybit keys, your bot, your rules.",
  icons: {
    // Browsers walk this list in order; SVG wins on modern browsers
    // (vector, theme-aware), the ICO is the universal fallback, and
    // the PNG sizes are what Chrome / Edge pick for specific contexts
    // (tab vs bookmark vs taskbar pinning).
    icon: [
      { url: "/icon.svg", type: "image/svg+xml" },
      { url: "/favicon.ico", type: "image/x-icon" },
      { url: "/favicon-16x16.png", type: "image/png", sizes: "16x16" },
      { url: "/favicon-32x32.png", type: "image/png", sizes: "32x32" },
      { url: "/favicon-48x48.png", type: "image/png", sizes: "48x48" },
    ],
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180" }],
  },
  manifest: "/site.webmanifest",
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
