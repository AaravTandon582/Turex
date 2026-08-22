import type { ReactNode } from "react";

import { SessionProvider } from "@/components/auth/session-provider";
import { AppShell } from "@/components/layout/app-shell";
import { RouteProgress } from "@/components/layout/route-progress";

export default function AuthenticatedLayout({ children }: { children: ReactNode }) {
  return (
    <SessionProvider>
      <RouteProgress />
      <AppShell>{children}</AppShell>
    </SessionProvider>
  );
}
