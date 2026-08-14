import { AlertCircle } from "lucide-react";

import type { ApiError } from "@/lib/api";

/**
 * Form-level error banner.
 *
 * Skipped when every problem the API reported is already shown beside its own field —
 * repeating "Email is invalid" at the top and again under the input is noise, not clarity.
 */
export function FormError({
  error,
  ignoreFields = [],
}: {
  error: ApiError | null;
  /** Field names the form renders inline. */
  ignoreFields?: string[];
}) {
  if (!error) return null;

  const unhandled = error.fields.filter((field) => !ignoreFields.includes(field.field));
  if (error.fields.length > 0 && unhandled.length === 0) return null;

  const message = unhandled.length > 0 ? unhandled[0].message : error.message;

  return (
    <div
      role="alert"
      className="flex items-start gap-2.5 rounded-md border border-danger/25 bg-danger-soft px-3 py-2.5 text-[13px] text-danger"
    >
      <AlertCircle className="mt-px size-4 shrink-0" aria-hidden />
      <span>{message}</span>
    </div>
  );
}
