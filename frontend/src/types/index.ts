// Kapanış — veri tipleri.
// Bu tipler botun gerçek JSON dosyalarıyla (alerts.json, positions.json, ...)
// alan alan aynıdır. Bota web API eklendiğinde /api/ingest/{collection} bu
// şekilleri gönderir ve panel doğrudan bağlanır.

export type Side = "long" | "short";

export interface Alert {
  id: string;
  symbol: string;
  side: Side;
  entry: number;
  stop: number;
  target: number;
  rr: number;
  status: "armed" | "triggered" | "cancelled" | "pending";
  note: string;
  created_at: string; // ISO
  queued?: boolean;
}

export interface Position {
  id: string;
  market?: "KRIPTO" | "BIST";
  currency?: "USD" | "TL";
  symbol: string;
  side: Side;
  entry: number;
  stop: number;
  target: number;
  current: number;
  size: number;
  rr: number;
  pnl: number;
  pnl_pct: number;
  opened_at: string;
  status: "open" | "closed";
  queued?: boolean;
}

export interface Decision {
  id: string;
  market?: "KRIPTO" | "BIST";
  currency?: "USD" | "TL";
  symbol: string;
  kind: "KARAR";
  verdict: "Aldım" | "Pas" | null;
  entry: number;
  stop: number;
  target: number;
  rr: number;
  chart_note: string;
  status: "pending" | "resolved";
  created_at: string;
  queued?: boolean;
}

export interface SignalPanel {
  key: string;
  title: string;
  value: string;
  detail: string;
}

export interface Signal {
  id: string;
  market?: "KRIPTO" | "BIST";
  currency?: "USD" | "TL";
  symbol: string;
  timeframe: string;
  type: string;
  score: number; // -5..+5
  summary: string;
  created_at: string;
  analysis: {
    panels: SignalPanel[];
    bot_decision: { verdict: string; confidence: number; reason: string };
  };
}

export interface Macro {
  id: string;
  regime_score: number; // -5..+5
  regime_label: string;
  dxy_alt: { label: string; value: number; score: number };
  stale: boolean;
  updated_at: string;
  components: { name: string; value: string; score: number }[];
  calendar: CalendarEvent[];
  note: string;
}

export interface CalendarEvent {
  time: string;
  title: string;
  country: string;
  importance: "high" | "medium" | "low";
  actual: string | null;
  forecast: string | null;
  previous: string | null;
}

export interface Derivative {
  id: string;
  symbol: string;
  funding_rate: number;
  open_interest: number;
  long_short_ratio: number;
  cot_percentile: number;
  basis: number;
  updated_at: string;
}

export interface Usage {
  id: string;
  date: string;
  total_cost: number;
  tokens_in: number;
  tokens_out: number;
  calls: number;
  hourly: { hour: number; cost: number; calls: number }[];
  tariff: { hour: number; rate: number; tier: "yüksek" | "düşük" }[];
}

export interface Candle {
  t: string;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

export interface Candles {
  id: string;
  symbol: string;
  timeframe: string;
  candles: Candle[];
  sma20: number;
  sma50: number;
  sma200: number;
}

export interface Command {
  id: string;
  type: string;
  payload: Record<string, unknown>;
  status: "pending" | "done";
  created_at: string;
}

// REST uç noktaları (JWT ile korumalı, X-Bot-Key not edilenler hariç):
//  POST   /api/auth/login | /auth/refresh | /auth/logout    GET /api/auth/me
//  GET    /api/overview
//  GET    /api/alerts        POST /api/alerts     DELETE /api/alerts/{id}
//  GET    /api/positions     PATCH /api/positions/{id}/stop   POST /api/positions/{id}/close
//  GET    /api/decisions     POST /api/decisions/{id}/action
//  GET    /api/signals       GET /api/signals/{id}
//  GET    /api/macro
//  GET    /api/derivatives
//  GET    /api/usage
//  GET    /api/report
//  GET    /api/backtest
//  GET    /api/settings
//  GET    /api/candles/{symbol}
//  GET    /api/commands
//  --- Bot (X-Bot-Key) ---
//  POST   /api/ingest/{collection}
//  GET    /api/commands/pending
//  POST   /api/commands/{id}/done
