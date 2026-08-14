"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { NAV_ITEMS } from "@/components/layout/navigation";

const CHORD_TIMEOUT_MS = 1200;

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.isContentEditable ||
    ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) ||
    target.closest("[role='textbox']") !== null
  );
}

/**
 * "Go to" navigation chords: press `g`, then a destination key.
 *
 * A two-key chord rather than a bare single key, so typing in a page never triggers
 * navigation and the shortcuts do not collide with browser or OS bindings.
 */
export function useNavShortcuts(): void {
  const router = useRouter();

  useEffect(() => {
    let armed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const disarm = () => {
      armed = false;
      clearTimeout(timer);
    };

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (isTypingTarget(event.target)) return;

      if (!armed) {
        if (event.key === "g") {
          armed = true;
          timer = setTimeout(disarm, CHORD_TIMEOUT_MS);
        }
        return;
      }

      const match = NAV_ITEMS.find((item) => item.shortcut === event.key.toLowerCase());
      disarm();
      if (match) {
        event.preventDefault();
        router.push(match.href);
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      clearTimeout(timer);
    };
  }, [router]);
}
