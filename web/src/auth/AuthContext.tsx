/** Who is logged in, app-wide. SPEC.md §2.5.
 *
 * The JWT in localStorage is the whole session — there is no server-side session to sync with. On
 * boot we call /api/auth/me to turn a stored token into a user (and to discover it has expired, in
 * which case we drop it silently rather than showing a scary error to someone who just arrived).
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api, clearToken, getToken, setToken } from "@/api/client";
import type { User } from "@/types";

interface AuthState {
  user: User | null;
  /** True until the initial /me check settles, so routes don't flash "logged out" on reload. */
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  signup: (email: string, password: string, accessCode: string) => Promise<void>;
  logout: () => void;
  /** Re-read the user, e.g. after an upload spends part of the grant. */
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!getToken()) {
      setLoading(false);
      return;
    }
    api
      .me()
      .then(setUser)
      .catch(() => {
        // Expired or revoked. Not an error worth showing — just not logged in any more.
        clearToken();
        setUser(null);
      })
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const res = await api.login(email, password);
    setToken(res.access_token);
    setUser(res.user);
  }, []);

  const signup = useCallback(async (email: string, password: string, accessCode: string) => {
    const res = await api.signup(email, password, accessCode);
    setToken(res.access_token); // signup logs you straight in
    setUser(res.user);
  }, []);

  const logout = useCallback(() => {
    clearToken();
    setUser(null);
  }, []);

  const refresh = useCallback(async () => {
    if (!getToken()) return;
    try {
      setUser(await api.me());
    } catch {
      clearToken();
      setUser(null);
    }
  }, []);

  const value = useMemo(
    () => ({ user, loading, login, signup, logout, refresh }),
    [user, loading, login, signup, logout, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
