import { api } from "@/lib/api";

export interface User {
  id: string;
  email: string;
  full_name: string;
  created_at: string;
}

interface SessionResponse {
  user: User;
  access_token_expires_at: string;
}

export const auth = {
  register: (input: { email: string; full_name: string; password: string }) =>
    api.post<SessionResponse>("/auth/register", input),

  login: (input: { email: string; password: string }) =>
    api.post<SessionResponse>("/auth/login", input),

  logout: () => api.post<void>("/auth/logout"),

  /** Resolve the signed-in user, or null when there is no valid session. */
  async currentUser(): Promise<User | null> {
    try {
      return await api.get<User>("/auth/me");
    } catch {
      return null;
    }
  },
};

/** Everyone's first name, for greetings. Falls back to the whole string. */
export function firstName(user: User): string {
  return user.full_name.trim().split(/\s+/)[0] || user.full_name;
}

export function initials(user: User): string {
  const parts = user.full_name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return user.email.slice(0, 2).toUpperCase();
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}
