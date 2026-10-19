"use client";

import { useCallback, useEffect, useState } from "react";

import { toApiError, type ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export type QueryState<T> =
  | { kind: "loading" }
  | { kind: "ready"; data: T }
  | { kind: "error"; error: ApiError };

/**
 * Loads `path` for the signed-in user. Pass `null` to skip (e.g. while auth is loading).
 * `reload()` refetches in the background: the current data stays on screen until the new response arrives
 * (no skeleton flash when polling or after saving). A different `path` shows a fresh loading state.
 * `mutate()` replaces the data locally after a successful write.
 */
export function useAuthedQuery<T>(path: string | null) {
  const { authRequest } = useAuth();
  const [version, setVersion] = useState(0);
  const requestKey = path ? `${path}#${version}` : null;
  // Results are tagged with the request they answer, so a new request reads as "loading" without extra state.
  const [result, setResult] = useState<{ key: string; path: string; state: QueryState<T> } | null>(null);

  useEffect(() => {
    if (!path || !requestKey) return;
    let cancelled = false;
    authRequest<T>(path)
      .then((data) => !cancelled && setResult({ key: requestKey, path, state: { kind: "ready", data } }))
      .catch((error: unknown) => {
        if (!cancelled) setResult({ key: requestKey, path, state: { kind: "error", error: toApiError(error) } });
      });
    return () => {
      cancelled = true;
    };
  }, [authRequest, path, requestKey]);

  let state: QueryState<T> = { kind: "loading" };
  if (result && result.key === requestKey) state = result.state;
  else if (result && result.path === path && result.state.kind === "ready") state = result.state; // revalidating

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  const mutate = useCallback(
    (data: T) => {
      if (requestKey && path) setResult({ key: requestKey, path, state: { kind: "ready", data } });
    },
    [requestKey, path],
  );
  return { state, reload, mutate };
}
