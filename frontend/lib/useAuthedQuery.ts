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
 * `reload()` refetches; `mutate()` replaces the data locally after a successful write.
 */
export function useAuthedQuery<T>(path: string | null) {
  const { authRequest } = useAuth();
  const [version, setVersion] = useState(0);
  const requestKey = path ? `${path}#${version}` : null;
  // Results are tagged with the request they answer, so a new request reads as "loading" without extra state.
  const [result, setResult] = useState<{ key: string; state: QueryState<T> } | null>(null);

  useEffect(() => {
    if (!path || !requestKey) return;
    let cancelled = false;
    authRequest<T>(path)
      .then((data) => !cancelled && setResult({ key: requestKey, state: { kind: "ready", data } }))
      .catch((error: unknown) => {
        if (!cancelled) setResult({ key: requestKey, state: { kind: "error", error: toApiError(error) } });
      });
    return () => {
      cancelled = true;
    };
  }, [authRequest, path, requestKey]);

  const state: QueryState<T> = result && result.key === requestKey ? result.state : { kind: "loading" };
  const reload = useCallback(() => setVersion((v) => v + 1), []);
  const mutate = useCallback(
    (data: T) => {
      if (requestKey) setResult({ key: requestKey, state: { kind: "ready", data } });
    },
    [requestKey],
  );
  return { state, reload, mutate };
}
