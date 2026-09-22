export interface KeyInfo {
  prefix: string;
  created: string;
  last_used: string | null;
  used_today: number;
  daily_limit: number;
}

export interface Me {
  email: string;
  verified: boolean;
  key: KeyInfo | null;
}

export interface Options {
  dates: string[];
  gates: string[];
  spans: string[];
  targets: string[];
  runs: Record<string, Record<string, string[]>>;
}

export interface ForecastMeta {
  date: string;
  gate: string;
  span: string;
  target: string;
  model: string;
  rows: number;
  generated_at: string;
}

export interface ForecastData {
  meta: ForecastMeta;
  timestamps: string[];
  p50: (number | null)[];
  p10: (number | null)[] | null;
  p90: (number | null)[] | null;
  actual: (number | null)[];
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error((body as { detail?: string }).detail ?? "Something went wrong.");
  }
  return body as T;
}

export const getMe = () => request<Me>("/auth/me");
export const getOptions = () => request<Options>("/api/options");

export function login(email: string, password: string) {
  return request<Me>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function signup(email: string, password: string) {
  return request<{ detail: string }>("/auth/signup", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function logout() {
  return request<{ ok: boolean }>("/auth/logout", { method: "POST" });
}

export function resend() {
  return request<{ detail: string }>("/auth/resend", { method: "POST" });
}

export function verifyEmail(token: string) {
  return request<{ detail: string; api_key?: string; prefix?: string }>(
    `/auth/verify?token=${encodeURIComponent(token)}`,
  );
}

export function refreshKey() {
  return request<{ prefix: string; api_key: string; detail: string }>(
    "/v1/keys/refresh",
    { method: "POST" },
  );
}

export function deleteAccount(password: string) {
  return request<{ ok: boolean }>("/auth/account", {
    method: "DELETE",
    body: JSON.stringify({ password }),
  });
}

export interface ForecastParams {
  date: string;
  gate: string;
  span: string;
  target: string;
  kind: "point" | "probabilistic";
}

export function publicForecast(p: ForecastParams) {
  const q = new URLSearchParams({
    date: p.date,
    gate: p.gate,
    span: p.span,
    target: p.target,
    type: p.kind,
  });
  return request<ForecastData>(`/api/forecast?${q}`);
}

export function keyedForecast(p: ForecastParams, key: string) {
  const q = new URLSearchParams({
    date: p.date,
    gate: p.gate,
    span: p.span,
    target: p.target,
    type: p.kind,
  });
  return fetch(`/v1/forecast?${q}`, { headers: { "X-API-Key": key } });
}

export const TARGET_LABELS: Record<string, string> = {
  price_sdac_seq1_eur_mwh: "Day-ahead price",
  load_actual_mw: "Load",
  gen_actual_total_mwh: "Generation total",
  gen_actual_wind_onshore_mwh: "Wind onshore",
  gen_actual_wind_offshore_mwh: "Wind offshore",
  gen_actual_photovoltaics_mwh: "Solar",
};

export function targetLabel(target: string): string {
  return TARGET_LABELS[target] ?? target;
}

export function unitFor(target: string): string {
  if (target.includes("eur_mwh")) return "€/MWh";
  if (target.includes("mwh")) return "MWh";
  return "MW";
}

const berlinTime = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/Berlin",
  hour: "2-digit",
  minute: "2-digit",
});

const berlinFull = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/Berlin",
  weekday: "short",
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

const berlinDayFmt = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/Berlin",
  weekday: "short",
  day: "numeric",
});

export function berlinShort(iso: string): string {
  return berlinTime.format(new Date(iso));
}

export function berlinLong(iso: string): string {
  return berlinFull.format(new Date(iso));
}

export function berlinDay(iso: string): string {
  return berlinDayFmt.format(new Date(iso));
}
