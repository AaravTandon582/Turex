import type { Metadata, Viewport } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans, IBM_Plex_Serif } from "next/font/google";

import { ThemeProvider, themeInitScript } from "@/components/theme/theme-provider";

import "./globals.css";

const plexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-plex-sans",
  display: "swap",
});

const plexSerif = IBM_Plex_Serif({
  subsets: ["latin"],
  weight: ["400", "600"],
  variable: "--font-plex-serif",
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "Turex — Research, connected",
    template: "%s · Turex",
  },
  description:
    "Understand papers. Connect ideas. Test hypotheses. Discover what to investigate next.",
  applicationName: "Turex",
};

export const viewport: Viewport = {
  // Dark first, so a browser with no stated preference paints its chrome to match the theme
  // the app will actually render — see DEFAULT_THEME in the theme provider.
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fcfcfb" },
    { color: "#1c1e24" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${plexSans.variable} ${plexSerif.variable} ${plexMono.variable}`}
    >
      <head>
        {/*
          Runs before paint so the correct theme is applied on the first frame, which is the
          only way to avoid a flash of the wrong one.

          `dangerouslySetInnerHTML` is safe here and nowhere else in this app: the script is a
          module constant built at compile time from another constant, and no user input can
          reach it. Anything with a runtime value in it would not belong here.
        */}
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className="min-h-dvh antialiased">
        <a
          href="#main"
          className="sr-only rounded-md bg-accent px-4 py-2 text-sm font-medium text-ink-inverse focus:not-sr-only focus:absolute focus:top-3 focus:left-3 focus:z-50"
        >
          Skip to content
        </a>
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
