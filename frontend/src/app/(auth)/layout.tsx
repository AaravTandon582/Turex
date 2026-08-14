import Link from "next/link";
import type { ReactNode } from "react";

import { AtlasMark } from "@/components/brand/atlas-mark";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col bg-canvas">
      <header className="p-6">
        <Link
          href="/"
          className="inline-flex items-center gap-2.5 rounded-md text-[15px] font-semibold tracking-[-0.01em] text-ink"
        >
          <AtlasMark className="size-6" />
          Atlas
        </Link>
      </header>

      <main id="main" className="flex flex-1 items-center justify-center px-5 pb-20">
        <div className="w-full max-w-sm animate-[var(--animate-rise)]">{children}</div>
      </main>
    </div>
  );
}
