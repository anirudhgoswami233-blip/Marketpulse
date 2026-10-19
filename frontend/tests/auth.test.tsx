import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AuthForm, safeNext } from "@/components/auth/AuthForm";
import { RequireAuth } from "@/components/auth/RequireAuth";
import { refreshSession, useAuth } from "@/lib/auth";
import { SESSION, authHeader, json, mockApi, renderWithAuth } from "./helpers";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh: vi.fn() }),
  usePathname: () => "/portfolio",
  useSearchParams: () => new URLSearchParams("next=/watchlists"),
}));

function Probe() {
  const { status, user, authRequest } = useAuth();
  return (
    <div>
      <p data-testid="status">{status}</p>
      <p>{user?.display_name}</p>
      <button type="button" onClick={() => void authRequest("/api/v1/watchlists")}>
        load
      </button>
    </div>
  );
}

describe("AuthProvider", () => {
  it("restores the session from the refresh cookie on load", async () => {
    const { calls } = mockApi({ "POST /api/v1/auth/refresh": json(SESSION) });
    renderWithAuth(<Probe />);
    expect(screen.getByTestId("status").textContent).toBe("loading");
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("authenticated"));
    expect(screen.getByText("Alice")).toBeTruthy();
    expect(calls[0].init?.credentials).toBe("include"); // the httpOnly cookie must be sent
  });

  it("is anonymous when there's no valid refresh cookie", async () => {
    mockApi({ "POST /api/v1/auth/refresh": json({ detail: "Please sign in", code: "not_authenticated" }, 401) });
    renderWithAuth(<Probe />);
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("anonymous"));
  });

  it("refreshes an expired access token once and retries the request", async () => {
    let refreshes = 0;
    let watchlistCalls = 0;
    const { calls } = mockApi({
      "POST /api/v1/auth/refresh": () => {
        refreshes += 1;
        return json({ ...SESSION, access_token: `access-${refreshes}` });
      },
      "GET /api/v1/watchlists": (init) => {
        watchlistCalls += 1;
        return authHeader(init) === "Bearer access-2"
          ? json([])
          : json({ detail: "Your session has expired.", code: "token_expired" }, 401);
      },
    });
    renderWithAuth(<Probe />);
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("authenticated"));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "load" }));
    });
    await waitFor(() => expect(watchlistCalls).toBe(2));
    expect(refreshes).toBe(2);
    expect(authHeader(calls.at(-1)?.init)).toBe("Bearer access-2");
  });

  it("shares one refresh between concurrent callers", async () => {
    const { fetchMock } = mockApi({ "POST /api/v1/auth/refresh": json(SESSION) });
    const [a, b] = await Promise.all([refreshSession(), refreshSession()]);
    expect(a).toEqual(b);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("retries once when another tab won a refresh race", async () => {
    let attempts = 0;
    mockApi({
      "POST /api/v1/auth/refresh": () => {
        attempts += 1;
        return attempts === 1 ? json({ detail: "retry", code: "refresh_race" }, 401) : json(SESSION);
      },
    });
    await expect(refreshSession()).resolves.toEqual(SESSION);
    expect(attempts).toBe(2);
  });
});

describe("AuthForm", () => {
  it("shows the server's message when sign-in fails", async () => {
    mockApi({
      "POST /api/v1/auth/refresh": json({ code: "not_authenticated" }, 401),
      "POST /api/v1/auth/login": json({ detail: "Incorrect email or password.", code: "invalid_credentials" }, 401),
    });
    renderWithAuth(<AuthForm mode="login" />);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "alice@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "nope-nope" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Incorrect email or password.");
    expect(push).not.toHaveBeenCalled();
  });

  it("registers with the browser's timezone and goes to ?next=", async () => {
    const { calls } = mockApi({
      "POST /api/v1/auth/refresh": json({ code: "not_authenticated" }, 401),
      "POST /api/v1/auth/register": json(SESSION, 201),
    });
    renderWithAuth(<AuthForm mode="register" />);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "alice@example.com" } });
    fireEvent.change(screen.getByLabelText(/^Password/), { target: { value: "long-enough-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/watchlists"));
    const body = JSON.parse(String(calls.find((c) => c.path === "/api/v1/auth/register")?.init?.body));
    expect(body.timezone).toBe(Intl.DateTimeFormat().resolvedOptions().timeZone);
  });

  it("only follows same-site relative next paths", () => {
    expect(safeNext("/watchlists")).toBe("/watchlists");
    expect(safeNext("//evil.example")).toBe("/portfolio");
    expect(safeNext("https://evil.example")).toBe("/portfolio");
    expect(safeNext(null)).toBe("/portfolio");
  });
});

describe("RequireAuth", () => {
  it("prompts anonymous visitors to sign in instead of rendering the page", async () => {
    mockApi({ "POST /api/v1/auth/refresh": json({ code: "not_authenticated" }, 401) });
    renderWithAuth(
      <RequireAuth what="portfolio">
        <p>secret</p>
      </RequireAuth>,
    );
    expect(await screen.findByText("Sign in to see your portfolio")).toBeTruthy();
    expect(screen.queryByText("secret")).toBeNull();
    expect(screen.getByRole("link", { name: "Sign in" }).getAttribute("href")).toBe("/login?next=%2Fportfolio");
  });
});

it("useAuth fails loudly outside <AuthProvider>", () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  expect(() => render(<Probe />)).toThrow(/AuthProvider/);
});
