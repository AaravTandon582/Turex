"use client";

import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

/**
 * A thin bar across the top while a route is changing.
 *
 * Clicking a sidebar link renders the new page's skeleton quickly, but between the click and
 * that first frame there is a gap with no acknowledgement at all — the old page just sits
 * there. On a fast machine it is imperceptible; on a slow connection it is long enough that
 * people click again.
 *
 * Deliberately delayed. A bar that flashes for 40ms on every navigation is worse than no bar:
 * it draws the eye to a wait that was not one. It appears only if the change takes longer than
 * a threshold nobody notices, which on this app means it stays hidden almost always — which is
 * the point.
 */

const APPEAR_AFTER_MS = 220;

export function RouteProgress() {
  const pathname = usePathname();
  const [visible, setVisible] = useState(false);
  const previous = useRef(pathname);

  useEffect(() => {
    if (previous.current === pathname) return;
    previous.current = pathname;

    // The route has already changed by the time this runs, so what is being waited for is the
    // new page's own data. It is hidden again once React has painted and the browser is idle,
    // which is the closest thing to "the page is ready" available from here.
    setVisible(true);

    const idle = window.requestAnimationFrame(() => {
      window.setTimeout(() => setVisible(false), 60);
    });
    return () => window.cancelAnimationFrame(idle);
  }, [pathname]);

  const [shown, setShown] = useState(false);
  useEffect(() => {
    if (!visible) {
      setShown(false);
      return;
    }
    const timer = window.setTimeout(() => setShown(true), APPEAR_AFTER_MS);
    return () => window.clearTimeout(timer);
  }, [visible]);

  if (!shown) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      aria-label="Loading the page"
      className="pointer-events-none fixed inset-x-0 top-0 z-50 h-0.5 overflow-hidden"
    >
      <div className="h-full w-1/3 animate-[var(--animate-indeterminate)] bg-accent" />
    </div>
  );
}
