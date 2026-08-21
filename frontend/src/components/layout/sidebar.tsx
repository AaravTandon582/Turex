"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { TurexMark } from "@/components/brand/turex-mark";
import { NAV_ITEMS } from "@/components/layout/navigation";
import { UserMenu } from "@/components/layout/user-menu";
import { cn } from "@/lib/cn";

export function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-14 items-center gap-2.5 px-4">
        <TurexMark className="size-6" />
        <span className="text-[15px] font-semibold tracking-[-0.01em] text-ink">Turex</span>
      </div>

      <nav aria-label="Main" className="flex-1 space-y-0.5 px-2 py-2">
        {NAV_ITEMS.map(({ href, label, icon: Icon, shortcut }) => {
          const active = pathname === href || pathname.startsWith(`${href}/`);
          return (
            <Link
              key={href}
              href={href}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              className={cn(
                "group flex h-9 items-center gap-2.5 rounded-md px-2.5 text-sm transition-colors duration-150",
                active
                  ? "bg-surface-hover font-medium text-ink"
                  : "text-ink-muted hover:bg-surface-hover hover:text-ink",
              )}
            >
              <Icon
                className={cn("size-4 shrink-0", active ? "text-accent" : "text-ink-subtle")}
                aria-hidden
              />
              <span className="flex-1">{label}</span>
              <kbd
                aria-hidden
                className="hidden font-mono text-[10px] text-ink-subtle opacity-0 transition-opacity group-hover:opacity-100 lg:block"
              >
                g {shortcut}
              </kbd>
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-border p-2">
        <UserMenu />
      </div>
    </div>
  );
}

export function Sidebar() {
  return (
    <aside className="hidden w-60 shrink-0 border-r border-border bg-surface-sunken md:block">
      <div className="sticky top-0 h-dvh">
        <SidebarContent />
      </div>
    </aside>
  );
}
