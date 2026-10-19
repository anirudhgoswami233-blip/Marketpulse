// Mirrors the backend's Pydantic schemas. Decimals arrive as strings to keep full precision;
// timestamps are ISO-8601 UTC strings.

export type DecimalString = string;
export type IsoDateTime = string;

/** Every data endpoint wraps its payload with freshness metadata. */
export interface Envelope<T> {
  data: T;
  as_of: IsoDateTime;
  source: string;
  stale: boolean;
}

export type ApiErrorCode = "not_found" | "no_data" | "unavailable" | "rate_limited" | "provider_error";

export interface Quote {
  symbol: string;
  price: DecimalString;
  change: DecimalString | null;
  change_pct: DecimalString | null;
  open: DecimalString | null;
  high: DecimalString | null;
  low: DecimalString | null;
  prev_close: DecimalString | null;
  timestamp: IsoDateTime | null;
  currency: string | null;
}

export type MarketSession = "pre_market" | "regular" | "post_market" | "closed";

export interface MarketStatus {
  exchange: string;
  name: string;
  region: string;
  timezone: string;
  local_time: IsoDateTime;
  is_open: boolean;
  session: MarketSession;
  holiday: string | null;
  next_change_at: IsoDateTime | null;
  status_source: "provider" | "schedule";
}

export interface IndexCard {
  symbol: string;
  name: string;
  tracks: string;
  is_etf_proxy: boolean;
  quote: Quote | null;
}

export interface RegionOverview {
  region: string;
  markets: MarketStatus[];
  indices: IndexCard[];
}

export interface SectorTile {
  symbol: string;
  sector: string;
  price: DecimalString | null;
  change_pct: DecimalString | null;
}

export interface Mover {
  symbol: string;
  price: DecimalString;
  change: DecimalString | null;
  change_pct: DecimalString;
  currency: string | null;
}

export interface MarketOverview {
  regions: RegionOverview[];
  sectors: SectorTile[];
  gainers: Mover[];
  losers: Mover[];
  movers_universe_size: number;
  as_of: IsoDateTime | null;
  stale: boolean;
  pending_symbols: number;
}

export interface SymbolInfo {
  symbol: string;
  display_symbol: string;
  description: string;
  exchange: string;
  type: string;
  currency: string | null;
  price_available: boolean;
  streamable: boolean;
}

export interface SearchResults {
  query: string;
  results: SymbolInfo[];
}

export interface CompanyProfile {
  symbol: string;
  name: string;
  country: string | null;
  currency: string | null;
  exchange: string | null;
  industry: string | null;
  ipo_date: string | null;
  logo_url: string | null;
  website: string | null;
  market_cap: DecimalString | null;
  shares_outstanding: DecimalString | null;
}

export interface KeyMetrics {
  symbol: string;
  week52_high: DecimalString | null;
  week52_high_date: string | null;
  week52_low: DecimalString | null;
  week52_low_date: string | null;
  pe_ttm: DecimalString | null;
  eps_ttm: DecimalString | null;
  pb: DecimalString | null;
  ps_ttm: DecimalString | null;
  beta: DecimalString | null;
  dividend_yield_pct: DecimalString | null;
  roe_ttm_pct: DecimalString | null;
  net_margin_ttm_pct: DecimalString | null;
  revenue_growth_ttm_yoy_pct: DecimalString | null;
  avg_volume_10d: DecimalString | null;
  avg_volume_3m: DecimalString | null;
}

export interface NewsItem {
  id: string;
  headline: string;
  summary: string;
  source: string;
  url: string;
  image_url: string | null;
  published_at: IsoDateTime;
  category: string | null;
  related_symbols: string[];
}

export type ChartRange = "1D" | "1W" | "1M" | "1Y" | "5Y";

export interface Bar {
  timestamp: IsoDateTime;
  open: DecimalString;
  high: DecimalString;
  low: DecimalString;
  close: DecimalString;
  volume: number | null;
}

export interface Chart {
  symbol: string;
  range: ChartRange;
  interval: string;
  currency: string | null;
  timezone: string | null;
  bars: Bar[];
}

/** One live trade pushed over the backend's SSE stream. */
export interface LiveTrade {
  symbol: string;
  price: DecimalString;
  timestamp: IsoDateTime;
  volume: DecimalString | null;
}

export interface StreamReady {
  live: string[];
  unavailable: string[];
  streaming_enabled: boolean;
}

// --- accounts, watchlists, paper trading -------------------------------------------------------------

export interface User {
  id: number;
  email: string;
  display_name: string;
  timezone: string;
  base_currency: string;
  brief_time: string;
  brief_email_enabled: boolean;
  created_at: IsoDateTime;
}

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_at: IsoDateTime;
  user: User;
}

export interface Watchlist {
  id: number;
  name: string;
  created_at: IsoDateTime;
  symbols: SymbolInfo[];
}

export interface QuoteResult {
  symbol: string;
  quote: Envelope<Quote> | null;
  error: "unavailable" | "not_found" | "provider_error" | null;
}

export interface BulkQuotes {
  results: QuoteResult[];
}

export type OrderSide = "buy" | "sell";

export interface Trade {
  id: number;
  symbol: string;
  display_symbol: string;
  side: OrderSide;
  quantity: DecimalString;
  price: DecimalString;
  currency: string;
  notional: DecimalString;
  realized_pnl: DecimalString | null;
  executed_at: IsoDateTime;
  price_as_of: IsoDateTime;
}

export interface Position {
  symbol: string;
  display_symbol: string;
  description: string;
  quantity: DecimalString;
  avg_cost: DecimalString;
  currency: string;
  last_price: DecimalString | null;
  price_as_of: IsoDateTime | null;
  price_stale: boolean;
  market_value: DecimalString | null;
  cost_basis: DecimalString;
  unrealized_pnl: DecimalString | null;
  unrealized_pnl_pct: DecimalString | null;
}

export interface Portfolio {
  id: number;
  name: string;
  base_currency: string;
  starting_cash: DecimalString;
  cash: DecimalString;
  market_value: DecimalString;
  equity: DecimalString;
  total_return: DecimalString;
  total_return_pct: DecimalString | null;
  realized_pnl: DecimalString;
  positions: Position[];
  incomplete: boolean;
  as_of: IsoDateTime;
}
