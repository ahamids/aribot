"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * Re-fetches the Server Component on a timer. Pauses when the tab is
 * hidden (visibilitychange) — no point polling for a screen the user
 * isn't looking at, and it also stops accidental DDoS of the backend
 * if a tab is left open overnight.
 *
 * router.refresh() triggers a server-side re-render of the current
 * route, so all the Server Components (StatusCard, PositionsCard,
 * etc.) get fresh data without a full page navigation.
 */
export function AutoRefresh({ intervalMs }: { intervalMs: number }) {
  const router = useRouter();

  useEffect(() => {
    let id: ReturnType<typeof setInterval> | null = null;

    const start = () => {
      if (id !== null) return;
      id = setInterval(() => router.refresh(), intervalMs);
    };
    const stop = () => {
      if (id === null) return;
      clearInterval(id);
      id = null;
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") {
        // Refresh immediately when the tab regains focus, then poll.
        router.refresh();
        start();
      } else {
        stop();
      }
    };

    if (document.visibilityState === "visible") start();
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [intervalMs, router]);

  return null;
}
