import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Compose class names, letting later Tailwind utilities win over earlier ones.
 *
 * Without the merge step, `cn("px-3", "px-6")` emits both and the winner depends on
 * stylesheet order — which makes component props like `className` unreliable.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
