import {
  BookOpen,
  FlaskConical,
  Home,
  Library,
  MessagesSquare,
  Search,
  GraduationCap,
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
 * The whole product, in eight destinations.
 *
 * Ordered along the research loop — read, organise, investigate, write, connect, learn, ask — so the
 * sidebar reflects how the work actually flows rather than grouping by feature area.
 */
export const NAV_ITEMS: readonly NavItem[] = [
  { href: "/dashboard", label: "Home", icon: Home, shortcut: "h" },
  { href: "/library", label: "Library", icon: Library, shortcut: "l" },
  { href: "/search", label: "Search", icon: Search, shortcut: "s" },
  { href: "/projects", label: "Projects", icon: FlaskConical, shortcut: "p" },
  { href: "/notebook", label: "Notebook", icon: BookOpen, shortcut: "n" },
  { href: "/graph", label: "Graph", icon: Share2, shortcut: "g" },
  { href: "/study", label: "Study", icon: GraduationCap, shortcut: "t" },
  { href: "/assistant", label: "Assistant", icon: MessagesSquare, shortcut: "a" },
] as const;
