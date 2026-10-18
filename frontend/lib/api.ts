import type {
  ApiErrorCode,
  Chart,
  ChartRange,
  CompanyProfile,
  Envelope,
  KeyMetrics,
  MarketOverview,
  NewsItem,
  Quote,
  SearchResults,
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
    readonly code: ApiErrorCode | "network" | "unknown",
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** Errors worth a "Try again" button; "not on our data plan" or "not found" won't change on retry. */
  get retryable(): boolean {
    return this.code !== "unavailable" && this.code !== "not_found" && this.code !== "no_data";
  }
}

const FALLBACK_MESSAGE = "Something went wrong loading this data.";

export async function apiGet<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl()}${path}`, {
      ...init,
      headers: { Accept: "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError("We couldn't reach the MarketPulse server. Check your connection.", 0, "network");
  }
  if (!response.ok) {
    let message = FALLBACK_MESSAGE;
    let code: ApiError["code"] = "unknown";
    try {
      const body: unknown = await response.json();
      if (body && typeof body === "object") {
        const detail = (body as { detail?: unknown }).detail;
        const bodyCode = (body as { code?: unknown }).code;
        if (typeof detail === "string") message = detail;
        if (typeof bodyCode === "string") code = bodyCode as ApiErrorCode;
      }
    } catch {
      // Non-JSON error body: keep the generic message.
    }
    throw new ApiError(message, response.status, code);
  }
  return (await response.json()) as T;
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
