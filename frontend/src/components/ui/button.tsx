import type { ButtonHTMLAttributes, ReactNode } from "react";

import { Slot } from "@/components/ui/slot";
import { cn } from "@/lib/cn";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

const VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-accent text-ink-inverse hover:bg-accent-hover shadow-[var(--shadow-sm)]",
  secondary:
    "bg-surface text-ink border border-border hover:bg-surface-hover hover:border-border-strong",
  ghost: "text-ink-muted hover:bg-surface-hover hover:text-ink",
  danger: "bg-danger text-white hover:brightness-95",
};

const SIZES: Record<ButtonSize, string> = {
  sm: "h-8 gap-1.5 px-3 text-[13px]",
  md: "h-9.5 gap-2 px-4 text-sm",
  lg: "h-11 gap-2 px-5 text-[15px]",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Render the child element instead of a <button> — for links that should look like buttons. */
  asChild?: boolean;
  loading?: boolean;
  children?: ReactNode;
}

export function Button({
  variant = "primary",
  size = "md",
  asChild = false,
  loading = false,
  disabled,
  className,
  children,
  ...props
}: ButtonProps) {
  const Component = asChild ? Slot : "button";

  return (
    <Component
      // `aria-busy` announces the working state. Relying on `disabled` alone would pull the
      // control out of the accessibility tree mid-action, which is disorienting.
      aria-busy={loading || undefined}
      disabled={asChild ? undefined : disabled || loading}
      className={cn(
        "relative inline-flex shrink-0 items-center justify-center rounded-md font-medium whitespace-nowrap",
        "transition-[background-color,border-color,color,opacity] duration-150 ease-[var(--ease-out-quart)]",
        "disabled:pointer-events-none disabled:opacity-50",
        "[&_svg]:size-4 [&_svg]:shrink-0",
        VARIANTS[variant],
        SIZES[size],
        // Hide the label rather than remove it, so the button keeps its width and the
        // surrounding layout does not jump while a request is in flight.
        loading && "text-transparent [&_svg]:opacity-0",
        className,
      )}
      {...props}
    >
      {loading && (
        <span
          aria-hidden
          className={cn(
            "absolute size-4 animate-spin rounded-full border-2 border-t-transparent",
            variant === "primary" || variant === "danger"
              ? "border-white/80 border-t-transparent"
              : "border-ink-muted border-t-transparent",
          )}
        />
      )}
      {children}
    </Component>
  );
}
