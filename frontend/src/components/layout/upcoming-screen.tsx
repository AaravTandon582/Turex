import type { ReactNode } from "react";

import { PageContainer } from "@/components/layout/page-container";
import { Badge, PageHeader } from "@/components/ui/primitives";

/**
 * A destination that exists in the navigation but whose milestone has not shipped.
 *
 * Deliberately explicit rather than a convincing mock. A screen that looks finished but does
 * nothing is worse than an empty one — it costs the reader trust when they discover it.
 */
export function UpcomingScreen({
  title,
  description,
  milestone,
  capabilities,
  children,
}: {
  title: string;
  description: string;
  milestone: string;
  capabilities: string[];
  children?: ReactNode;
}) {
  return (
    <PageContainer>
      <PageHeader
        title={title}
        description={description}
        actions={<Badge tone="accent">{milestone}</Badge>}
      />

      <div className="mt-6 rounded-lg border border-dashed border-border p-6">
        <p className="text-[13px] font-medium text-ink">Not built yet. This screen will let you:</p>
        <ul className="measure mt-3 space-y-2">
          {capabilities.map((capability) => (
            <li key={capability} className="flex gap-2.5 text-sm text-ink-muted">
              <span aria-hidden className="mt-2 size-1 shrink-0 rounded-full bg-ink-subtle" />
              {capability}
            </li>
          ))}
        </ul>
        {children}
      </div>
    </PageContainer>
  );
}
