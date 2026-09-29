// Types for the AgriVarsha API — mirrors docs/contracts/api.md.

export type Severity = "info" | "watch" | "warning";
export type HazardType =
  | "onset" | "false_onset" | "active_phase" | "dry_spell" | "heavy_rain" | "revival";
export type Confidence = "High" | "Medium" | "Low";
export type Source = "mock" | "real";
export type AdvisoryStatus = "draft" | "approved" | "rejected" | "superseded" | "sent";
export type Channel = "app" | "sms" | "whatsapp" | "ivr";

export interface Context {
  issue_date: string;
  forecast_source: Source;
  scenario: string;
  forecast_issue_date: string;
  model_version: string;
  observed_through: string | null;
  note: string | null;
  hazard_run_id: number;
}

export interface Health {
  status: string;
  demo_mode: boolean;
  forecast_source: Source;
  scenario: string | null;
  llm_enabled: boolean;
  today: string;
  default_date: string;
}

export interface ForecastRow {
  lead_week: number;
  week_start: string;
  week_end: string;
  p_below: number;
  p_normal: number;
  p_above: number;
  q10_mm: number;
  q50_mm: number;
  q90_mm: number;
  p_heavy: number;
  p_dry_week: number;
  confidence: Confidence;
  model_version: string;
  region_id?: number;
  district?: string;
  issue_date?: string;
}

export interface Hazard {
  id: number;
  region_id: number;
  district: string;
  hazard_type: HazardType;
  subtype: string | null;
  severity: Severity;
  probability: number;
  lead_week: number;
  window_start: string | null;
  window_end: string | null;
  confidence: Confidence;
  basis: "observed" | "forecast" | "observed+forecast";
  why: string;
  evidence: Record<string, unknown>;
}

export interface Risk {
  severity: Severity | "none";
  top_hazard: HazardType | null;
  top_probability: number | null;
  hazard_types: HazardType[];
}

export interface DistrictFeature {
  type: "Feature";
  id: number;
  geometry: GeoJSON.Geometry;
  properties: {
    id: number;
    code: string;
    slug: string;
    name: string;
    area_km2: number;
    centroid: [number, number];
    coastal: boolean;
    risk: Risk;
  };
}

export interface DistrictsResponse {
  type: "FeatureCollection";
  features: DistrictFeature[];
  context: Context;
}

export interface CropStage {
  crop: string;
  season: string;
  stage: string;
  stage_group: string;
  days_after_sowing: number | null;
  typical_sowing_date: string;
  sowing_window: [string, string];
  calendar_district: string;
  is_sample: boolean;
}

export interface DistrictInfo {
  id: number;
  code: string;
  slug: string;
  name: string;
  area_km2: number;
  lon: number;
  lat: number;
  coastal: boolean;
}

export interface ForecastResponse {
  context: Context;
  district: DistrictInfo;
  forecast: ForecastRow[];
  hazards: Hazard[];
  crop_stages: CropStage[];
  observed: {
    through: string | null;
    last_7_days_mm: number | null;
    last_30_days_mm: number | null;
    source: string;
  };
}

export interface HazardsResponse {
  context: Context;
  count: number;
  hazards: Hazard[];
}

export interface Overview {
  context: Context;
  districts: { total: number; with_alerts: number; warning: number; watch: number; info_only: number };
  hazards: {
    total: number;
    by_type: Record<string, { districts: number; info: number; watch: number; warning: number }>;
  };
  advisories: {
    by_status: Record<AdvisoryStatus, number>;
    pending_review: number;
    by_severity: Record<string, number>;
    farmers_covered_by_sent: number;
  };
  farmers: { registered_total: number; in_alert_districts: number; source: string };
  delivery: {
    broadcasts: number;
    recipients: number;
    sent: number;
    delivered: number;
    read: number;
    delivery_rate: number | null;
    read_rate: number | null;
    mode: string;
  };
  feedback: { total: number; positive_rate: number | null };
  forecast_week1: {
    mean_q50_mm: number | null;
    districts_above_normal_favoured: number;
    districts_below_normal_favoured: number;
    confidence_counts: Record<string, number>;
  };
  data_freshness: {
    last_rainfall_date: string | null;
    rainfall_lag_days: number | null;
    observed_through: string | null;
  };
  top_risk_districts: (Risk & { region_id: number; district: string })[];
}

export interface RainfallPoint {
  date: string;
  rain_mm: number | null;
  source: string | null;
  rain_sum_7d: number | null;
  anomaly_7d_pct: number | null;
  consecutive_dry_days: number | null;
  normal_mm: number | null;
}

export interface RainfallResponse {
  district: { id: number; name: string; slug: string };
  days: number;
  start: string;
  end: string;
  total_mm: number;
  normal_mm: number;
  percent_of_normal: number | null;
  wet_days: number;
  max_day_mm: number;
  source: string;
  series: RainfallPoint[];
}

export interface CropCalendarResponse {
  calendar: {
    crop: string;
    season: string;
    district: string;
    sowing_start_doy: number;
    sowing_end_doy: number;
    stage_name: string;
    stage_start_day: number;
    stage_end_day: number;
    is_sample: boolean;
  }[];
  stages?: CropStage[];
  issue_date?: string;
}

export interface AdvisoryEvent {
  action: string;
  actor: string | null;
  note: string | null;
  payload: Record<string, unknown>;
  at: string;
}

export interface Advisory {
  id: number;
  issue_date: string;
  forecast_source: Source;
  scenario: string;
  region_id: number;
  district: string;
  crop: string;
  season: string;
  stage: string;
  stage_group: string;
  hazard_type: HazardType;
  hazard_subtype: string | null;
  hazard_probability: number | null;
  hazard_lead_week: number | null;
  hazard_confidence: Confidence | null;
  hazard_why: string | null;
  rule_id: string;
  severity: Severity;
  title_en: string;
  title_ta: string;
  text_en: string;
  text_ta: string;
  action_en: string;
  action_ta: string;
  simple_text_en: string | null;
  rephrased_by: string;
  tamil_reviewed: boolean;
  source_note: string;
  farmers_targeted: number;
  status: AdvisoryStatus;
  edited: boolean;
  reviewer: string | null;
  review_note: string | null;
  created_at: string;
  updated_at: string;
  approved_at: string | null;
}

export interface ChannelPreview {
  en: string;
  ta: string;
  chars_en: number;
  chars_ta: number;
  segments_en?: number;
  segments_ta?: number;
}

export interface AdvisoryDetail extends Advisory {
  events: AdvisoryEvent[];
  channel_preview: Record<Channel, ChannelPreview>;
  broadcasts: {
    broadcast_id: number;
    status: string;
    channels: Channel[];
    total_recipients: number;
    created_at: string;
    completed_at: string | null;
  }[];
}

export interface AdvisoriesResponse {
  context: Context | null;
  total: number;
  limit: number;
  offset: number;
  status_counts: Partial<Record<AdvisoryStatus, number>>;
  advisories: Advisory[];
}

export interface BroadcastChannel {
  channel: Channel;
  status: "queued" | "sending" | "delivering" | "reading" | "completed";
  recipients: number;
  sent: number;
  delivered: number;
  read: number;
  failed: number;
  delivery_rate: number;
  read_rate: number;
  content_en: string;
  content_ta: string;
  chars_en: number;
  chars_ta: number;
  sms_segments_en?: number;
  sms_segments_ta?: number;
}

export interface BroadcastStatus {
  broadcast_id: number;
  advisory_id: number;
  status: "in_progress" | "completed";
  delivery_mode: string;
  created_at: string;
  completed_at: string | null;
  progress: number;
  duration_s: number;
  total_recipients: number;
  totals: { queued: number; sent: number; delivered: number; read: number; failed: number };
  channels: BroadcastChannel[];
  as_of: string;
}

export interface BroadcastListItem {
  broadcast_id: number;
  advisory_id: number;
  status: string;
  channels: Channel[];
  total_recipients: number;
  created_at: string;
  completed_at: string | null;
  district: string;
  crop: string;
  title_en: string;
  severity: Severity;
}

export interface FeedbackAgg {
  key: string | number;
  total: number;
  up: number;
  down: number;
  positive_rate: number | null;
}

export interface FeedbackSummary {
  totals: {
    total: number;
    up: number;
    down: number;
    simulated: number;
    real: number;
    with_comment: number;
    positive_rate: number | null;
  };
  by_hazard_type: FeedbackAgg[];
  by_district: FeedbackAgg[];
  by_channel: FeedbackAgg[];
  by_advisory: FeedbackAgg[];
  recent_comments: {
    id: number;
    advisory_id: number;
    district: string;
    crop: string;
    hazard_type: string;
    channel: string | null;
    rating: 1 | -1;
    comment: string | null;
    simulated: boolean;
    created_at: string;
  }[];
}

export interface PipelineRun {
  id: number;
  stage: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  rows_written: number;
  message: string | null;
  duration_s: number | null;
}

export interface PipelineHealth {
  status: "ok" | "ok_with_warnings" | "degraded";
  table_counts: Record<string, number>;
  rainfall: { last_date: string | null; lag_days: number | null };
  forecasts: { issue_dates: string[]; latest_issue_date: string | null };
  recent_runs: PipelineRun[];
  quality: {
    report_generated: string | null;
    report_path: string;
    summary: { pass: number; warn: number; fail: number };
    checks: { check: string; status: "PASS" | "WARN" | "FAIL"; detail: string }[];
    latest_quality_run: unknown;
  };
}

export interface SkillRow {
  target: string;
  lead_week: number;
  season: string;
  metric: string;
  model: string;
  value: number | null;
  ci_low: number | null;
  ci_high: number | null;
  n_samples: number | null;
  n_years: number | null;
}

export interface ModelSkill {
  model_version: string;
  meta: {
    model_version?: string;
    trained?: string;
    train_years?: [number, number];
    final_data_end?: string;
    n_features?: number;
  };
  model_card: string | null;
  note: string;
  headline: {
    target: string;
    lead_week: number;
    season: string;
    value: number | null;
    ci_low: number | null;
    ci_high: number | null;
    metric: string;
    skillful: boolean;
  }[];
  count: number;
  rows: SkillRow[];
}

export interface SourceInfo {
  source: Source;
  available: Source[];
  env_default: Source;
  scenario: string | null;
  real_issue_dates: string[];
  demo_mode: boolean;
}

export interface Scenario {
  name: string;
  title: string;
  description: string;
  demo_date: string;
  focus_districts: string[];
}

export interface ScenariosResponse {
  active: string | null;
  scenarios: Scenario[];
}
