"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { ApiError, apiRequest, type RequestOptions } from "@/lib/api";
import type { TokenResponse, User } from "@/types/api";

/*
 * Session model: the short-lived access token lives only in memory (never localStorage). The refresh token
 * is an httpOnly cookie the backend sets on /api/v1/auth, so JavaScript can't read it. On page load we
 * exchange the cookie for an access token; when an API call says the token expired we refresh once and retry.
 */

export type AuthStatus = "loading" | "authenticated" | "anonymous";

export interface RegisterInput {
  email: string;
  password: string;
  displayName?: string;
  timezone: string;
}

interface AuthContextValue {
  status: AuthStatus;
  user: User | null;
  login: (email: string, password: string) => Promise<void>;
  register: (input: RegisterInput) => Promise<void>;
  logout: () => Promise<void>;
  /** An API request with the access token attached, refreshing it once if it has expired. */
  authRequest: <T>(path: string, options?: RequestOptions) => Promise<T>;
  /** Replace the cached profile after the user edits it (e.g. brief settings). */
  updateUser: (user: User) => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const REFRESH_RACE_RETRY_MS = 300;

// One refresh at a time per page: concurrent callers (StrictMode, parallel requests) share it, because each
// refresh rotates the cookie and a second concurrent refresh would present an already-used token.
let refreshInFlight: Promise<TokenResponse> | null = null;

async function requestRefresh(): Promise<TokenResponse> {
  const attempt = () => apiRequest<TokenResponse>("/api/v1/auth/refresh", { method: "POST", credentials: "include" });
  try {
    return await attempt();
  } catch (error) {
    // Another tab rotated the cookie a moment ago; the browser already holds the new one.
    if (error instanceof ApiError && error.code === "refresh_race") {
      await new Promise((resolve) => setTimeout(resolve, REFRESH_RACE_RETRY_MS));
      return attempt();
    }
    throw error;
  }
}

export function refreshSession(): Promise<TokenResponse> {
  refreshInFlight ??= requestRefresh().finally(() => {
    refreshInFlight = null;
  });
  return refreshInFlight;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [user, setUser] = useState<User | null>(null);
  const tokenRef = useRef<string | null>(null);

  const applySession = useCallback((session: TokenResponse | null) => {
    tokenRef.current = session?.access_token ?? null;
    setUser(session?.user ?? null);
    setStatus(session ? "authenticated" : "anonymous");
  }, []);

  useEffect(() => {
    let cancelled = false;
    refreshSession()
      .then((session) => !cancelled && applySession(session))
      .catch(() => !cancelled && applySession(null));
    return () => {
      cancelled = true;
    };
  }, [applySession]);

  const login = useCallback(
    async (email: string, password: string) => {
      const session = await apiRequest<TokenResponse>("/api/v1/auth/login", {
        method: "POST",
        credentials: "include",
        json: { email, password },
      });
      applySession(session);
    },
    [applySession],
  );

  const register = useCallback(
    async (input: RegisterInput) => {
      const session = await apiRequest<TokenResponse>("/api/v1/auth/register", {
        method: "POST",
        credentials: "include",
        json: {
          email: input.email,
          password: input.password,
          display_name: input.displayName || null,
          timezone: input.timezone,
        },
      });
      applySession(session);
    },
    [applySession],
  );

  const logout = useCallback(async () => {
    try {
      await apiRequest<void>("/api/v1/auth/logout", { method: "POST", credentials: "include" });
    } finally {
      applySession(null);
    }
  }, [applySession]);

  const authRequest = useCallback(
    async <T,>(path: string, options: RequestOptions = {}): Promise<T> => {
      const send = (token: string | null) =>
        apiRequest<T>(path, {
          ...options,
          headers: { ...options.headers, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        });
      try {
        return await send(tokenRef.current);
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 401) throw error;
        let session: TokenResponse;
        try {
          session = await refreshSession();
        } catch {
          applySession(null);
          throw error;
        }
        applySession(session);
        return send(session.access_token);
      }
    },
    [applySession],
  );

  const updateUser = useCallback((next: User) => setUser(next), []);

  const value = useMemo(
    () => ({ status, user, login, register, logout, authRequest, updateUser }),
    [status, user, login, register, logout, authRequest, updateUser],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}
