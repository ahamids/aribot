"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { setTheme } from "@/app/actions/theme";
import type { Theme } from "@/lib/theme";

export function ThemeToggle({ initialTheme }: { initialTheme: Theme }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [theme, setLocalTheme] = useState<Theme>(initialTheme);

  function pick(next: Theme) {
    if (next === theme || pending) return;
    setLocalTheme(next); // optimistic
    startTransition(async () => {
      await setTheme(next);
      router.refresh();
    });
  }

  return (
    <div className="flex gap-2">
      <ThemeOption
        label="Light"
        emoji="☀️"
        selected={theme === "light"}
        disabled={pending}
        onClick={() => pick("light")}
      />
      <ThemeOption
        label="Dark"
        emoji="🌙"
        selected={theme === "dark"}
        disabled={pending}
        onClick={() => pick("dark")}
      />
    </div>
  );
}

function ThemeOption({
  label,
  emoji,
  selected,
  disabled,
  onClick,
}: {
  label: string;
  emoji: string;
  selected: boolean;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || selected}
      className={`outline-plum rounded-[10px] px-3 py-2 text-sm font-bold transition disabled:opacity-60 ${
        selected
          ? "sticker bg-coral text-plum cursor-default"
          : "bg-cream text-plum hover:bg-cream-deep"
      }`}
    >
      <span className="mr-1.5" aria-hidden>
        {emoji}
      </span>
      {label}
      {selected && (
        <span className="ml-1 text-xs font-bold uppercase tracking-wider text-plum-mid">
          ·current
        </span>
      )}
    </button>
  );
}
