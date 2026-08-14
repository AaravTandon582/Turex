import { Children, cloneElement, isValidElement, type ReactElement, type ReactNode } from "react";

import { cn } from "@/lib/cn";

interface SlotProps {
  children?: ReactNode;
  className?: string;
  [key: string]: unknown;
}

/**
 * Renders its single child, merging in the props given to the Slot.
 *
 * Lets a styled component like `<Button asChild>` wrap a `<Link>` so the link carries the
 * button's classes and attributes without nesting an interactive element inside another.
 */
export function Slot({ children, className, ...props }: SlotProps) {
  // Filter rather than `Children.only`: callers routinely interleave conditional siblings
  // such as `{loading && <Spinner />}`, which render as `false` and are not real children.
  const elements = Children.toArray(children).filter(isValidElement);
  if (elements.length !== 1) {
    throw new Error(
      `Slot expects exactly one element child, received ${elements.length}. ` +
        "Wrap the children in a single element.",
    );
  }

  const child = elements[0];
  const childProps = child.props as { className?: string };

  return cloneElement(child as ReactElement<Record<string, unknown>>, {
    ...props,
    className: cn(className, childProps.className),
  });
}
