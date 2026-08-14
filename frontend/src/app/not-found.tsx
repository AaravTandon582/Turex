import Link from "next/link";

import { AtlasMark } from "@/components/brand/atlas-mark";
import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-5 px-5 text-center">
      <AtlasMark className="size-8" />
      <div>
        <h1 className="text-xl font-semibold tracking-[-0.01em] text-ink">
          That page doesn&rsquo;t exist
        </h1>
        <p className="measure mt-1.5 text-sm text-ink-muted">
          The link may be out of date, or the item may have been deleted.
        </p>
      </div>
      <Button asChild variant="secondary">
        <Link href="/dashboard">Back to Atlas</Link>
      </Button>
    </div>
  );
}
