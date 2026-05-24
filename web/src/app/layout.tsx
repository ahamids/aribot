import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Aribot — Crypto trading bot",
  description:
    "Multi-tenant crypto trading bot. Bring your own Bybit keys, your bot, your rules.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col bg-cream text-plum">
        {children}
      </body>
    </html>
  );
}
