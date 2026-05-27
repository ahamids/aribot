import Link from "next/link";
import { signOut } from "@/app/actions/auth";

interface NavProps {
  email: string;
  /**
   * Slug of the currently-active tab. Used to highlight the right link.
   * Pass the route's path segment, e.g. "dashboard", "history", "settings".
   */
  active: "dashboard" | "positions" | "history" | "settings";
}

/**
 * Shared header for all /(app) routes. Centralizes the brand, the
 * dashboard/history/settings nav, the user's email, and the sign-out
 * form so each page doesn't duplicate the boilerplate.
 */
export function AppNav({ email, active }: NavProps) {
  return (
    <header className="px-4 py-4 sm:px-12 sm:py-6 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
      {/* Row 1 on mobile / left on desktop: brand + (mobile-only) sign-out */}
      <div className="flex items-center justify-between sm:justify-start gap-4 sm:gap-6">
        <Link
          href="/dashboard"
          className="text-2xl font-black tracking-tight text-plum"
        >
          aribot
        </Link>
        <form action={signOut} className="sm:hidden">
          <button
            type="submit"
            className="outline-plum rounded-[10px] bg-paper text-plum px-3 py-1.5 text-xs font-bold hover:bg-cream-deep"
          >
            Sign out
          </button>
        </form>
      </div>

      {/* Tabs — wrap to their own row on mobile, inline on desktop. Horizontal
          scroll if they ever overflow on a very narrow screen. */}
      <nav className="flex items-center gap-1 -mx-1 overflow-x-auto sm:overflow-visible">
        <NavLink href="/dashboard" label="Dashboard" active={active === "dashboard"} />
        <NavLink href="/positions" label="Positions" active={active === "positions"} />
        <NavLink href="/history" label="History" active={active === "history"} />
        <NavLink href="/settings" label="Settings" active={active === "settings"} />
      </nav>

      {/* Right side on desktop only: email + sign-out */}
      <div className="hidden sm:flex items-center gap-3">
        <span className="text-sm text-plum-mid truncate max-w-[200px]">
          {email}
        </span>
        <form action={signOut}>
          <button
            type="submit"
            className="outline-plum rounded-[12px] bg-paper text-plum px-4 py-2 text-sm font-bold hover:bg-cream-deep"
          >
            Sign out
          </button>
        </form>
      </div>
    </header>
  );
}

function NavLink({
  href,
  label,
  active,
}: {
  href: string;
  label: string;
  active: boolean;
}) {
  return (
    <Link
      href={href}
      className={`px-3 py-1.5 rounded-[10px] text-sm font-bold transition whitespace-nowrap ${
        active
          ? "outline-plum bg-coral text-plum sticker"
          : "text-plum-mid hover:bg-cream-deep hover:text-plum"
      }`}
    >
      {label}
    </Link>
  );
}
