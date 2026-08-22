import {
  BookOpen,
  FlaskConical,
  Terminal,
  ClipboardCheck,
  Home,
  Compass,
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
 * The whole product, in eleven destinations.
 *
 * Ordered along the research loop — read, find, organise, investigate, write, connect, learn, ask — so
 * the sidebar reflects how the work actually flows rather than grouping by feature area.
 *
 * Discover sits beside Library because they are the two halves of the same idea: the papers you
 * have, and the papers you could have.
 */
export const NAV_ITEMS: readonly NavItem[] = [
  { href: "/dashboard", label: "Home", icon: Home, shortcut: "h" },
  { href: "/library", label: "Library", icon: Library, shortcut: "l" },
  { href: "/discover", label: "Discover", icon: Compass, shortcut: "d" },
  { href: "/search", label: "Search", icon: Search, shortcut: "s" },
  { href: "/projects", label: "Projects", icon: FlaskConical, shortcut: "p" },
  { href: "/workstation", label: "Workstation", icon: Terminal, shortcut: "w" },
  { href: "/notebook", label: "Notebook", icon: BookOpen, shortcut: "n" },
  { href: "/lab", label: "Lab", icon: ClipboardCheck, shortcut: "b" },
  { href: "/graph", label: "Graph", icon: Share2, shortcut: "g" },
  { href: "/study", label: "Study", icon: GraduationCap, shortcut: "t" },
  { href: "/assistant", label: "Assistant", icon: MessagesSquare, shortcut: "a" },
] as const;
