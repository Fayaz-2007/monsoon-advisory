import type { HazardType, Severity } from "../api/types";

export const pct = (p: number | null | undefined, digits = 0) =>
  p === null || p === undefined ? "—" : `${(p * 100).toFixed(digits)}%`;

export const num = (n: number | null | undefined, digits = 0) =>
  n === null || n === undefined ? "—" : n.toLocaleString("en-IN", { maximumFractionDigits: digits, minimumFractionDigits: digits });

export const compact = (n: number) =>
  n >= 1e7 ? `${(n / 1e7).toFixed(1)} Cr` : n >= 1e5 ? `${(n / 1e5).toFixed(1)} L` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : `${n}`;

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function parseDate(s: string): Date {
  const [y, m, d] = s.slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function isoDate(d: Date): string {
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

export function addDays(s: string, n: number): string {
  const d = parseDate(s);
  d.setDate(d.getDate() + n);
  return isoDate(d);
}

export const day = (s: string | null | undefined) => {
  if (!s) return "—";
  const d = parseDate(s);
  return `${d.getDate()} ${MONTHS[d.getMonth()]}`;
};

export const longDate = (s: string | null | undefined) => {
  if (!s) return "—";
  const d = parseDate(s);
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
};

export const range = (a: string | null, b: string | null) => (a && b ? `${day(a)} – ${day(b)}` : "");

export function timeAgo(iso: string): string {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

export const HAZARD_LABEL: Record<HazardType, string> = {
  onset: "Monsoon onset",
  false_onset: "False onset",
  active_phase: "Active phase",
  dry_spell: "Dry spell",
  heavy_rain: "Heavy rain",
  revival: "Rain revival",
};

export const HAZARD_LABEL_TA: Record<HazardType, string> = {
  onset: "பருவமழை தொடக்கம்",
  false_onset: "தவறான தொடக்கம்",
  active_phase: "தீவிர மழைக் காலம்",
  dry_spell: "வறட்சி",
  heavy_rain: "கனமழை",
  revival: "மழை மீண்டும்",
};

export const SEVERITY_STYLE: Record<Severity | "none", { dot: string; chip: string; fill: string; label: string }> = {
  warning: { dot: "bg-red-500", chip: "bg-red-50 text-red-700 ring-red-200 dark:bg-red-500/10 dark:text-red-300 dark:ring-red-500/30", fill: "#ef4444", label: "Warning" },
  watch: { dot: "bg-amber-500", chip: "bg-amber-50 text-amber-800 ring-amber-200 dark:bg-amber-500/10 dark:text-amber-300 dark:ring-amber-500/30", fill: "#f59e0b", label: "Watch" },
  info: { dot: "bg-sky-500", chip: "bg-sky-50 text-sky-700 ring-sky-200 dark:bg-sky-500/10 dark:text-sky-300 dark:ring-sky-500/30", fill: "#38bdf8", label: "Info" },
  none: { dot: "bg-zinc-300", chip: "bg-subtle text-muted ring-line", fill: "#d4d4d8", label: "Calm" },
};

export const CROP_EMOJI: Record<string, string> = {
  paddy: "🌾", groundnut: "🥜", cotton: "☁️", millets: "🌿", pulses: "🫘",
};

export const CROP_TA: Record<string, string> = {
  paddy: "நெல்", groundnut: "நிலக்கடலை", cotton: "பருத்தி", millets: "சிறுதானியங்கள்", pulses: "பயறு வகைகள்",
};

export const titleCase = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export const isObserved = (basis: string) => basis === "observed" || basis === "observed+forecast";
