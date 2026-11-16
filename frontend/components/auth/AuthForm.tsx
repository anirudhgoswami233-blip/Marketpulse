"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { MIN_SIGNUP_AGE, ageOn, blockSignup, signupBlocked } from "@/lib/age";
import { toApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useHydrated } from "@/lib/hooks";

const inputClass = "input";

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
  const [refusedForAge, setRefusedForAge] = useState(false);
  const hydrated = useHydrated();
  const isLogin = mode === "login";
  // A refusal for age sticks in this browser, so re-entering a different date doesn't get through.
  const blocked = !isLogin && (refusedForAge || (hydrated && signupBlocked()));

  const refuseForAge = () => {
    blockSignup();
    setRefusedForAge(true);
    setSubmitting(false);
  };

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const email = String(form.get("email") ?? "");
    const password = String(form.get("password") ?? "");
    const birthDate = String(form.get("birthDate") ?? "");
    setError(null);
    if (!isLogin) {
      // Checked before anything is sent: an under-age visitor's email and password never leave the browser.
      const age = ageOn(birthDate, new Date());
      if (!Number.isFinite(age) || age < 0 || age > 120) {
        setError("Please enter your date of birth.");
        return;
      }
      if (age < MIN_SIGNUP_AGE) {
        refuseForAge();
        return;
      }
    }
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
          birthDate,
        });
      }
      router.push(safeNext(searchParams.get("next")));
    } catch (err) {
      const apiError = toApiError(err);
      if (apiError.code === "age_restricted") {
        refuseForAge();
        return;
      }
      setError(apiError.message);
      setSubmitting(false);
    }
  };

  if (blocked) {
    return (
      <div role="alert" className="space-y-2 text-[13px]">
        <p className="font-medium text-primary">We can&apos;t create an account for you.</p>
        <p className="text-secondary">
          You don&apos;t meet the requirements to sign up. You can still browse markets, charts and the screener without
          an account.
        </p>
        <Link href="/" className="text-accent hover:underline">
          Back to markets
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="space-y-3" noValidate>
      {!isLogin && (
        <label className="block space-y-1 text-[13px]">
          <span className="text-secondary">Display name (optional)</span>
          <input name="displayName" autoComplete="nickname" maxLength={80} className={inputClass} />
        </label>
      )}
      <label className="block space-y-1 text-[13px]">
        <span className="text-secondary">Email</span>
        <input name="email" type="email" required autoComplete="email" className={inputClass} />
      </label>
      <label className="block space-y-1 text-[13px]">
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
      {!isLogin && (
        <label className="block space-y-1 text-[13px]">
          <span className="text-secondary">Date of birth</span>
          <input
            name="birthDate"
            type="date"
            required
            autoComplete="bday"
            className={inputClass}
            aria-describedby="birth-date-hint"
          />
          <span id="birth-date-hint" className="text-xs text-muted">
            Used once to check eligibility. We don&apos;t store it.
          </span>
        </label>
      )}
      {error && (
        <p role="alert" className="notice text-down">
          {error}
        </p>
      )}
      <button
        type="submit"
        disabled={submitting}
        className="btn btn-md btn-primary w-full"
      >
        {submitting ? (isLogin ? "Signing in…" : "Creating account…") : isLogin ? "Sign in" : "Create account"}
      </button>
      <p className="text-center text-[13px] text-secondary">
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
