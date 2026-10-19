"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { toApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const inputClass =
  "w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-primary focus:border-accent focus:outline-none";

/** Only follow same-site relative paths after sign-in (never an absolute URL from the query string). */
export function safeNext(raw: string | null): string {
  return raw && raw.startsWith("/") && !raw.startsWith("//") ? raw : "/portfolio";
}

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const { login, register } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const email = String(form.get("email") ?? "");
    const password = String(form.get("password") ?? "");
    setError(null);
    setSubmitting(true);
    try {
      if (mode === "login") {
        await login(email, password);
      } else {
        await register({
          email,
          password,
          displayName: String(form.get("displayName") ?? ""),
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
        });
      }
      router.push(safeNext(searchParams.get("next")));
    } catch (err) {
      setError(toApiError(err).message);
      setSubmitting(false);
    }
  };

  const isLogin = mode === "login";
  return (
    <form onSubmit={onSubmit} className="space-y-4" noValidate>
      {!isLogin && (
        <label className="block space-y-1 text-sm">
          <span className="text-secondary">Display name (optional)</span>
          <input name="displayName" autoComplete="nickname" maxLength={80} className={inputClass} />
        </label>
      )}
      <label className="block space-y-1 text-sm">
        <span className="text-secondary">Email</span>
        <input name="email" type="email" required autoComplete="email" className={inputClass} />
      </label>
      <label className="block space-y-1 text-sm">
        <span className="text-secondary">Password</span>
        <input
          name="password"
          type="password"
          required
          minLength={isLogin ? undefined : 8}
          autoComplete={isLogin ? "current-password" : "new-password"}
          className={inputClass}
          aria-describedby={isLogin ? undefined : "password-hint"}
        />
        {!isLogin && (
          <span id="password-hint" className="text-xs text-muted">
            At least 8 characters.
          </span>
        )}
      </label>
      {error && (
        <p role="alert" className="rounded-md bg-surface-2 px-3 py-2 text-sm text-down">
          {error}
        </p>
      )}
      <button
        type="submit"
        disabled={submitting}
        className="w-full rounded-lg bg-accent px-3 py-2 text-sm font-medium text-surface hover:opacity-90 disabled:opacity-60"
      >
        {submitting ? (isLogin ? "Signing in…" : "Creating account…") : isLogin ? "Sign in" : "Create account"}
      </button>
      <p className="text-center text-sm text-secondary">
        {isLogin ? "New to MarketPulse? " : "Already have an account? "}
        <Link
          href={`${isLogin ? "/register" : "/login"}${searchParams.get("next") ? `?next=${encodeURIComponent(safeNext(searchParams.get("next")))}` : ""}`}
          className="text-accent hover:underline"
        >
          {isLogin ? "Create an account" : "Sign in"}
        </Link>
      </p>
    </form>
  );
}
