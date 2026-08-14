"use client";

import { Menu, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { useSession } from "@/components/auth/session-provider";
import { AtlasMark } from "@/components/brand/atlas-mark";
import { Sidebar, SidebarContent } from "@/components/layout/sidebar";
import { useNavShortcuts } from "@/components/layout/use-nav-shortcuts";
import { Skeleton } from "@/components/ui/primitives";

/**
 * The authenticated application frame.
 *
 * Desktop gets a persistent sidebar; below `md` it collapses into a drawer, because a
 * 240px rail on a phone leaves no room for a paper.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const { status } = useSession();
  const router = useRouter();
  const [drawerOpen, setDrawerOpen] = useState(false);

  useNavShortcuts();

  useEffect(() => {
    if (status === "anonymous") router.replace("/login");
  }, [status, router]);

  // Lock background scrolling while the drawer covers the page.
  useEffect(() => {
    if (!drawerOpen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [drawerOpen]);

  useEffect(() => {
    if (!drawerOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setDrawerOpen(false);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [drawerOpen]);

  if (status !== "authenticated") return <AppShellSkeleton />;

  return (
    <div className="flex min-h-dvh">
      <Sidebar />

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-border bg-canvas/85 px-4 backdrop-blur-sm md:hidden">
          <button
            type="button"
            onClick={() => setDrawerOpen(true)}
            aria-label="Open navigation"
            className="-ml-1.5 flex size-9 items-center justify-center rounded-md text-ink-muted transition-colors hover:bg-surface-hover hover:text-ink"
          >
            <Menu className="size-5" aria-hidden />
          </button>
          <AtlasMark className="size-5" />
          <span className="text-sm font-semibold text-ink">Atlas</span>
        </header>

        <main id="main" className="min-w-0 flex-1">
          {children}
        </main>
      </div>

      {drawerOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <button
            type="button"
            aria-label="Close navigation"
            onClick={() => setDrawerOpen(false)}
            className="absolute inset-0 animate-[var(--animate-fade-in)] bg-black/40"
          />
          <div className="absolute inset-y-0 left-0 w-64 animate-[var(--animate-fade-in)] border-r border-border bg-surface-sunken">
            <button
              type="button"
              onClick={() => setDrawerOpen(false)}
              aria-label="Close navigation"
              className="absolute top-3.5 right-3 flex size-8 items-center justify-center rounded-md text-ink-muted hover:bg-surface-hover"
            >
              <X className="size-4" aria-hidden />
            </button>
            <SidebarContent onNavigate={() => setDrawerOpen(false)} />
          </div>
        </div>
      )}
    </div>
  );
}

/** Matches the real frame's geometry so nothing shifts once the session resolves. */
function AppShellSkeleton() {
  return (
    <div className="flex min-h-dvh" aria-busy>
      <div className="hidden w-60 shrink-0 border-r border-border bg-surface-sunken p-4 md:block">
        <Skeleton className="h-6 w-24" />
        <div className="mt-6 space-y-2">
          {Array.from({ length: 6 }, (_, index) => (
            <Skeleton key={index} className="h-9 w-full rounded-md" />
          ))}
        </div>
      </div>
      <div className="flex-1 p-6 md:p-10">
        <Skeleton className="h-7 w-56" />
        <Skeleton className="mt-3 h-4 w-80" />
        <Skeleton className="mt-8 h-48 w-full rounded-lg" />
      </div>
      <span className="sr-only">Loading your workspace</span>
    </div>
  );
}
