"use client";

import { useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { auth, type User } from "@/lib/auth";

type SessionStatus = "loading" | "authenticated" | "anonymous";

interface SessionContextValue {
  user: User | null;
  status: SessionStatus;
  setUser: (user: User | null) => void;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

/**
 * Holds the signed-in user for the authenticated app.
 *
 * The session lives in an httpOnly cookie scoped to the API origin, so the Next server cannot
 * read it during rendering — the client resolves it once on mount instead. Screens render a
 * skeleton while `status` is "loading" rather than flashing a signed-out state.
 */
export function SessionProvider({
  children,
  initialUser = null,
}: {
  children: ReactNode;
  initialUser?: User | null;
}) {
  const [user, setUser] = useState<User | null>(initialUser);
  const [status, setStatus] = useState<SessionStatus>(initialUser ? "authenticated" : "loading");
  const router = useRouter();

  const refresh = useCallback(async () => {
    const current = await auth.currentUser();
    setUser(current);
    setStatus(current ? "authenticated" : "anonymous");
  }, []);

  useEffect(() => {
    if (initialUser) return;
    void refresh();
  }, [initialUser, refresh]);

  const signOut = useCallback(async () => {
    await auth.logout().catch(() => {
      // Sign-out is best effort; the local session is cleared regardless so the user is
      // never stuck looking at an app they believe they have left.
    });
    setUser(null);
    setStatus("anonymous");
    router.push("/login");
  }, [router]);

  const value = useMemo(
    () => ({ user, status, setUser, signOut, refresh }),
    [user, status, signOut, refresh],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const context = useContext(SessionContext);
  if (!context) throw new Error("useSession must be used inside a SessionProvider");
  return context;
}
