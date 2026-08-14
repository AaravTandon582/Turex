"use client";

import { LogOut } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useSession } from "@/components/auth/session-provider";
import { ThemeToggle } from "@/components/theme/theme-toggle";
import { Skeleton } from "@/components/ui/primitives";
import { initials } from "@/lib/auth";

export function UserMenu() {
  const { user, status, signOut } = useSession();
  const [open, setOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Close on outside click or Escape — the two things people try without thinking.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  if (status === "loading") {
    return (
      <div className="flex items-center gap-2.5 px-1.5 py-1.5">
        <Skeleton className="size-7 rounded-full" />
        <Skeleton className="h-3.5 flex-1" />
      </div>
    );
  }

  if (!user) return null;

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-2.5 rounded-md px-1.5 py-1.5 text-left transition-colors hover:bg-surface-hover"
      >
        <span
          aria-hidden
          className="flex size-7 shrink-0 items-center justify-center rounded-full bg-accent-soft text-[11px] font-semibold text-accent"
        >
          {initials(user)}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-medium text-ink">
            {user.full_name}
          </span>
          <span className="block truncate text-[11px] text-ink-subtle">{user.email}</span>
        </span>
      </button>

      {open && (
        <div
          role="menu"
          className="absolute bottom-[calc(100%+6px)] left-0 z-30 w-full animate-[var(--animate-rise)] rounded-lg border border-border bg-surface p-1.5 shadow-[var(--shadow-lg)]"
        >
          <div className="flex items-center justify-between gap-2 px-1.5 py-1">
            <span className="text-[12px] text-ink-muted">Theme</span>
            <ThemeToggle />
          </div>
          <div className="my-1 h-px bg-border" />
          <button
            type="button"
            role="menuitem"
            disabled={signingOut}
            onClick={() => {
              setSigningOut(true);
              void signOut();
            }}
            className="flex w-full items-center gap-2 rounded-sm px-1.5 py-1.5 text-[13px] text-ink-muted transition-colors hover:bg-surface-hover hover:text-ink disabled:opacity-60"
          >
            <LogOut className="size-3.5" aria-hidden />
            {signingOut ? "Signing out…" : "Sign out"}
          </button>
        </div>
      )}
    </div>
  );
}
