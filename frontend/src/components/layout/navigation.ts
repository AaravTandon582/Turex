import {
  BookOpen,
  FlaskConical,
  Home,
  Library,
  MessagesSquare,
  Share2,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Single-key shortcut, pressed after `g` (as in "go to"). */
  shortcut: string;
}

/**
 * The whole product, in seven destinations.
 *
 * Ordered along the research loop — read, organise, investigate, write, connect, ask — so the
 * sidebar reflects how the work actually flows rather than grouping by feature area.
 */
export const NAV_ITEMS: readonly NavItem[] = [
  { href: "/dashboard", label: "Home", icon: Home, shortcut: "h" },
  { href: "/library", label: "Library", icon: Library, shortcut: "l" },
  { href: "/projects", label: "Projects", icon: FlaskConical, shortcut: "p" },
  { href: "/notebook", label: "Notebook", icon: BookOpen, shortcut: "n" },
  { href: "/graph", label: "Graph", icon: Share2, shortcut: "g" },
  { href: "/assistant", label: "Assistant", icon: MessagesSquare, shortcut: "a" },
] as const;
