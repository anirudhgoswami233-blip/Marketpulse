import type {
  ApiErrorCode,
  Chart,
  ChartRange,
  CompanyProfile,
  BulkQuotes,
  Envelope,
  KeyMetrics,
  MarketOverview,
  NewsItem,
  Quote,
  SearchResults,
  Signal,
  SignalLabel,
  SignalPerformance,
  SymbolInfo,
} from "@/types/api";

const PUBLIC_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/** Server-side rendering may reach the backend at a different address than the browser. */
export function apiBaseUrl(): string {
  if (typeof window === "undefined") {
    return process.env.API_BASE_URL || PUBLIC_BASE;
  }
  return PUBLIC_BASE;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    /** Backend error code (e.g. "unavailable", "insufficient_cash"), or "network" / "unknown". */
    readonly code: ApiErrorCode | (string & {}),
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** Errors worth a "Try again" button: network trouble and server-side failures, but not plan limits. */
  get retryable(): boolean {
    if (this.code === "unavailable") return false;
    return this.status === 0 || this.status === 429 || this.status >= 500;
  }
}

const FALLBACK_MESSAGE = "Something went wrong loading this data.";

export interface RequestOptions extends Omit<RequestInit, "body"> {
  /** Serialized as JSON. */
  json?: unknown;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { json, headers, ...init } = options;
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl()}${path}`, {
      ...init,
      body: json === undefined ? undefined : JSON.stringify(json),
      headers: {
        Accept: "application/json",
        ...(json === undefined ? {} : { "Content-Type": "application/json" }),
        ...headers,
      },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError("We couldn't reach the MarketPulse server. Check your connection.", 0, "network");
  }
  if (!response.ok) {
    let message = FALLBACK_MESSAGE;
    let code = "unknown";
    try {
      const body: unknown = await response.json();
      if (body && typeof body === "object") {
        const detail = (body as { detail?: unknown }).detail;
        const bodyCode = (body as { code?: unknown }).code;
        if (typeof detail === "string") message = detail;
        // FastAPI's own request validation returns a list of field errors.
        else if (Array.isArray(detail)) message = "Please check your input and try again.";
        if (typeof bodyCode === "string") code = bodyCode;
      }
    } catch {
      // Non-JSON error body: keep the generic message.
    }
    throw new ApiError(message, response.status, code);
  }
  // 202/204 responses (e.g. "generation started", "deleted") may have no body at all.
  const text = await response.text();
  if (!text) return undefined as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError("The server sent an unexpected response.", response.status, "malformed_response");
  }
}

export function apiGet<T>(path: string, init?: RequestInit): Promise<T> {
  return apiRequest<T>(path, init);
}

const enc = encodeURIComponent;

export const api = {
  overview: () => apiGet<MarketOverview>("/api/v1/markets/overview"),
  search: (q: string, limit = 10, init?: RequestInit) =>
    apiGet<SearchResults>(`/api/v1/search?q=${enc(q)}&limit=${limit}`, init),
  stock: (symbol: string) => apiGet<SymbolInfo>(`/api/v1/stocks/${enc(symbol)}`),
  quote: (symbol: string) => apiGet<Envelope<Quote>>(`/api/v1/stocks/${enc(symbol)}/quote`),
  profile: (symbol: string) => apiGet<Envelope<CompanyProfile>>(`/api/v1/stocks/${enc(symbol)}/profile`),
  metrics: (symbol: string) => apiGet<Envelope<KeyMetrics>>(`/api/v1/stocks/${enc(symbol)}/metrics`),
  news: (symbol: string) => apiGet<Envelope<NewsItem[]>>(`/api/v1/stocks/${enc(symbol)}/news`),
  quotes: (symbols: string[], init?: RequestInit) =>
    apiGet<BulkQuotes>(`/api/v1/quotes?symbols=${symbols.map(enc).join(",")}`, init),
  signal: (symbol: string) => apiGet<Signal>(`/api/v1/stocks/${enc(symbol)}/signal`),
  signalHistory: (params: { symbol?: string; label?: SignalLabel; limit?: number } = {}) => {
    const query = new URLSearchParams();
    if (params.symbol) query.set("symbol", params.symbol);
    if (params.label) query.set("label", params.label);
    query.set("limit", String(params.limit ?? 50));
    return apiGet<Signal[]>(`/api/v1/signals/history?${query}`);
  },
  signalPerformance: () => apiGet<SignalPerformance>("/api/v1/signals/performance"),
  chart: (symbol: string, range: ChartRange, init?: RequestInit) =>
    apiGet<Envelope<Chart>>(`/api/v1/stocks/${enc(symbol)}/chart?range=${range}`, init),
};

export function streamUrl(symbols: string[]): string {
  return `${apiBaseUrl()}/api/v1/stream?symbols=${symbols.map(enc).join(",")}`;
}

/** Turn any thrown value into an ApiError so UI components can render it consistently. */
export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  return new ApiError(FALLBACK_MESSAGE, 0, "unknown");
}
