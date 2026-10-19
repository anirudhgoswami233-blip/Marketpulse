import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { vi } from "vitest";

import { AuthProvider } from "@/lib/auth";
import type { TokenResponse, User } from "@/types/api";

export const USER: User = {
  id: 1,
  email: "alice@example.com",
  display_name: "Alice",
  timezone: "UTC",
  base_currency: "USD",
  brief_time: "07:30:00",
  brief_email_enabled: false,
  created_at: "2026-10-19T10:00:00Z",
};

export const SESSION: TokenResponse = {
  access_token: "access-1",
  token_type: "bearer",
  expires_at: "2026-10-19T10:15:00Z",
  user: USER,
};

export function json(body: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

type Handler = (init: RequestInit | undefined, url: string) => Response | Promise<Response>;

/**
 * Route fetch calls by "METHOD path" (query string ignored) so tests read like an API contract.
 * Unmatched requests fail loudly.
 */
export function mockApi(routes: Record<string, Handler | Response>) {
  const calls: { method: string; path: string; init?: RequestInit }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const method = (init?.method ?? "GET").toUpperCase();
    calls.push({ method, path: url.pathname, init });
    const route = routes[`${method} ${url.pathname}`];
    if (!route) throw new Error(`Unexpected request: ${method} ${url.pathname}`);
    return typeof route === "function" ? route(init, url.toString()) : route.clone();
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

export function renderWithAuth(ui: ReactNode) {
  return render(<AuthProvider>{ui}</AuthProvider>);
}

export function authHeader(init: RequestInit | undefined): string | undefined {
  return (init?.headers as Record<string, string> | undefined)?.Authorization;
}
