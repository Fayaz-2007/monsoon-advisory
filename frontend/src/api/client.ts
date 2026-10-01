// Thin fetch wrapper around the AgriVarsha API (docs/contracts/api.md).
import type {
  AdvisoriesResponse, AdvisoryDetail, BlocksResponse, BroadcastListItem, BroadcastStatus, Channel,
  CropCalendarResponse, DistrictsResponse, FeedbackSummary, ForecastResponse, ForecastRow,
  Context, Health, HazardsResponse, ModelSkill, Overview, PipelineHealth, RainfallResponse,
  ScenariosResponse, Source, SourceInfo,
} from "./types";

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

export class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail);
  }
}

type Params = Record<string, string | number | boolean | null | undefined>;

function qs(params?: Params): string {
  if (!params) return "";
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

async function request<T>(method: string, path: string, params?: Params, body?: unknown,
                          signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${BASE}/api${path}${qs(params)}`, {
    method,
    signal,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch { /* not JSON */ }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

const get = <T,>(path: string, params?: Params, signal?: AbortSignal) =>
  request<T>("GET", path, params, undefined, signal);
const post = <T,>(path: string, body?: unknown, params?: Params) =>
  request<T>("POST", path, params, body ?? {});

export const api = {
  health: (signal?: AbortSignal) => get<Health>("/health", undefined, signal),
  context: (date?: string | null) => get<Context>("/context", { date }),
  districts: (date?: string | null, tolerance = 0.01) =>
    get<DistrictsResponse>("/districts", { date, tolerance }),
  forecast: (district: string, date?: string | null) =>
    get<ForecastResponse>(`/forecast/${encodeURIComponent(district)}`, { date }),
  blocks: (district = "madurai", date?: string | null) =>
    get<BlocksResponse>("/blocks", { district, date }),
  forecasts: (date?: string | null, lead_week?: number) =>
    get<{ context: Context; count: number; forecasts: ForecastRow[] }>("/forecasts", { date, lead_week }),
  hazards: (p: { date?: string | null; district?: string; type?: string; min_severity?: string }) =>
    get<HazardsResponse>("/hazards", p),
  overview: (date?: string | null) => get<Overview>("/overview", { date }),
  rainfall: (district: string, days = 30, end?: string | null) =>
    get<RainfallResponse>(`/rainfall/${encodeURIComponent(district)}`, { days, end }),
  cropCalendar: (district?: string, date?: string | null) =>
    get<CropCalendarResponse>("/crop-calendar", { district, date }),

  advisories: (p: {
    status?: string; date?: string | null; district?: string; crop?: string; severity?: string;
    hazard_type?: string; all_contexts?: boolean; limit?: number; offset?: number;
  }) => get<AdvisoriesResponse>("/advisories", p),
  advisory: (id: number) => get<AdvisoryDetail>(`/advisories/${id}`),
  approve: (id: number, reviewer?: string, note?: string) =>
    post<AdvisoryDetail>(`/advisories/${id}/approve`, { reviewer, note }),
  edit: (id: number, changes: Record<string, unknown>) =>
    post<AdvisoryDetail>(`/advisories/${id}/edit`, changes),
  reject: (id: number, reviewer?: string, reason?: string) =>
    post<AdvisoryDetail>(`/advisories/${id}/reject`, { reviewer, reason }),

  broadcast: (advisoryId: number, channels: Channel[], reviewer?: string) =>
    post<BroadcastStatus>(`/broadcast/${advisoryId}`, { channels, reviewer }),
  broadcastStatus: (id: number) => get<BroadcastStatus>(`/broadcast/${id}/status`),
  broadcasts: (limit = 50) => get<{ broadcasts: BroadcastListItem[] }>("/broadcasts", { limit }),
  feedback: (body: { advisory_id: number; rating: "up" | "down"; comment?: string; channel?: Channel }) =>
    post<unknown>("/feedback", body),
  feedbackSummary: (advisory_id?: number, include_simulated = true) =>
    get<FeedbackSummary>("/feedback/summary", { advisory_id, include_simulated }),

  pipelineHealth: () => get<PipelineHealth>("/pipeline/health"),
  modelSkill: (p?: { target?: string; season?: string; model?: string; lead_week?: number }) =>
    get<ModelSkill>("/model/skill", p),

  sourceInfo: () => get<SourceInfo>("/settings/forecast-source"),
  setSource: (source: Source, date?: string | null) =>
    post<SourceInfo & { context: Context }>("/settings/forecast-source", { source }, { date }),

  scenarios: () => get<ScenariosResponse>("/demo/scenarios"),
  activateScenario: (name: string) => post<{ context: Context }>(`/demo/scenario/${name}`),
  reset: (purge = false) => post<unknown>("/demo/reset", undefined, { purge }),
};

/** Streams /api/chat (Server-Sent Events over a POST). */
export async function streamChat(
  body: { message: string; district?: string; date?: string | null },
  on: {
    meta?: (m: { mode: string; district: string | null; sources: string[]; context: Context }) => void;
    token: (text: string) => void;
    done?: (d: { mode: string; answer?: string }) => void;
    error?: (detail: string) => void;
  },
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...body, date: body.date ?? undefined }),
    signal,
  });
  if (!res.ok || !res.body) throw new ApiError(res.status, res.statusText);
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += value;
    let i: number;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, i);
      buf = buf.slice(i + 2);
      const ev = /event: (.*)/.exec(block)?.[1];
      const raw = /data: (.*)/.exec(block)?.[1];
      if (!ev || raw === undefined) continue;
      const data = JSON.parse(raw);
      if (ev === "token") on.token(data.text);
      else if (ev === "meta") on.meta?.(data);
      else if (ev === "done") on.done?.(data);
      else if (ev === "error") on.error?.(data.detail);
    }
  }
}
