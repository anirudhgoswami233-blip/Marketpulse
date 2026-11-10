"use client";

import { useCallback, useEffect, useRef, useState } from "react";

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
 *
 * `initialData` seeds the first render from server-cached data (for public endpoints rendered on the
 * server): the data shows immediately and the initial client fetch is skipped, so a warm visit doesn't
 * touch the backend at all. `reload()` and a changed `path` still fetch.
 */
export function useAuthedQuery<T>(path: string | null, initialData?: T) {
  const { authRequest } = useAuth();
  const [version, setVersion] = useState(0);
  const requestKey = path ? `${path}#${version}` : null;
  const seeded = initialData !== undefined && path !== null;
  // Results are tagged with the request they answer, so a new request reads as "loading" without extra state.
  const [result, setResult] = useState<{ key: string; path: string; state: QueryState<T> } | null>(
    seeded ? { key: `${path}#0`, path: path as string, state: { kind: "ready", data: initialData as T } } : null,
  );
  // The seeded request is already satisfied; skip its fetch (but still fetch on reload or a path change).
  const skipFetchFor = useRef<string | null>(seeded ? `${path}#0` : null);

  useEffect(() => {
    if (!path || !requestKey) return;
    if (skipFetchFor.current === requestKey) {
      skipFetchFor.current = null;
      return;
    }
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
