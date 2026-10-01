import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowLeft, CheckCircle2, CloudDrizzle, CloudLightning, CloudRain, CloudSun, MapPin, Square, SunMedium, ThumbsDown,
  ThumbsUp, Volume2,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Advisory, ForecastRow } from "../api/types";
import { Logo } from "../components/Logo";
import { BlockDemoBadge, cx, RetryState, Skeleton } from "../components/ui";
import { useAppState } from "../lib/appState";
import { CROP_EMOJI, CROP_TA, day, HAZARD_LABEL, HAZARD_LABEL_TA, parseDate, pct } from "../lib/format";

type Lang = "ta" | "en";
const CROPS = ["paddy", "groundnut", "cotton", "millets", "pulses"];
const TA_MONTHS = ["ஜன.", "பிப்.", "மார்ச்", "ஏப்.", "மே", "ஜூன்", "ஜூலை", "ஆக.", "செப்.", "அக்.", "நவ.", "டிச."];

const T = {
  title: { en: "My farm weather", ta: "என் வயல் வானிலை" },
  district: { en: "District", ta: "மாவட்டம்" },
  crop: { en: "Crop", ta: "பயிர்" },
  advice: { en: "Today's advice", ta: "இன்றைய ஆலோசனை" },
  todo: { en: "What to do", ta: "செய்ய வேண்டியது" },
  weeks: { en: "Next 4 weeks", ta: "அடுத்த 4 வாரங்கள்" },
  week: { en: "Week", ta: "வாரம்" },
  listen: { en: "Listen", ta: "கேளுங்கள்" },
  stop: { en: "Stop", ta: "நிறுத்து" },
  useful: { en: "Was this useful?", ta: "இது பயனுள்ளதா?" },
  thanks: { en: "Thank you! Your answer was sent to the agriculture office.", ta: "நன்றி! உங்கள் பதில் வேளாண் அலுவலகத்திற்கு அனுப்பப்பட்டது." },
  none: { en: "No special advice for your crop right now. Keep following normal practice.", ta: "இப்போது உங்கள் பயிருக்கு சிறப்பு ஆலோசனை இல்லை. வழக்கமான முறையைத் தொடரவும்." },
  pending: { en: "Preview: awaiting officer approval", ta: "முன்னோட்டம்: அலுவலர் ஒப்புதலுக்காகக் காத்திருக்கிறது" },
  comment: { en: "Add a comment (optional)", ta: "கருத்து (விருப்பம்)" },
  send: { en: "Send", ta: "அனுப்பு" },
  mm: { en: "mm rain", ta: "மி.மீ மழை" },
  heavy: { en: "Heavy rain", ta: "கனமழை" },
  dry: { en: "Dry week", ta: "வறண்ட வாரம்" },
  noVoice: { en: "Tamil voice not available on this device — reading in English.", ta: "இந்தச் சாதனத்தில் தமிழ் குரல் இல்லை — ஆங்கிலத்தில் படிக்கப்படுகிறது." },
};
const t = (k: keyof typeof T, l: Lang) => T[k][l];

function taDay(s: string) {
  const d = parseDate(s);
  return `${d.getDate()} ${TA_MONTHS[d.getMonth()]}`;
}

function weekIcon(w: ForecastRow) {
  if (w.p_heavy >= 0.3) return { Icon: CloudLightning, label: "heavy" as const, tone: "text-red-500" };
  if (w.p_dry_week >= 0.4 || w.q50_mm < 5) return { Icon: SunMedium, label: "dry" as const, tone: "text-amber-500" };
  if (w.q50_mm < 20) return { Icon: CloudSun, label: null, tone: "text-sky-500" };
  if (w.q50_mm < 50) return { Icon: CloudDrizzle, label: null, tone: "text-sky-600" };
  return { Icon: CloudRain, label: null, tone: "text-sky-700" };
}

/** Pick what the farmer sees: sent/approved first; a draft only as a labelled preview. */
function pickAdvisory(list: Advisory[], crop: string): Advisory | null {
  const mine = list.filter((a) => a.crop === crop);
  const rank = (a: Advisory) => ({ sent: 0, approved: 1, draft: 2 } as Record<string, number>)[a.status] ?? 9;
  const sev = (a: Advisory) => ({ warning: 0, watch: 1, info: 2 })[a.severity];
  return mine.filter((a) => rank(a) < 9).sort((a, b) => rank(a) - rank(b) || sev(a) - sev(b))[0] ?? null;
}

export default function Farmer() {
  const { date } = useAppState();
  const [lang, setLang] = useState<Lang>(() => (localStorage.getItem("av-farmer-lang") as Lang) || "ta");
  const [district, setDistrict] = useState(() => localStorage.getItem("av-farmer-district") || "madurai");
  const [crop, setCrop] = useState(() => localStorage.getItem("av-farmer-crop") || "millets");
  // MOCK block-level demo: Madurai farmers can pick their block ("" = whole district).
  const [block, setBlock] = useState(() => { try { return localStorage.getItem("av-farmer-block") || ""; } catch { return ""; } });
  useEffect(() => {
    try {
      localStorage.setItem("av-farmer-lang", lang);
      localStorage.setItem("av-farmer-district", district);
      localStorage.setItem("av-farmer-crop", crop);
      localStorage.setItem("av-farmer-block", block);
    } catch { /* ignore */ }
  }, [lang, district, crop, block]);
  const blocks = useQuery({
    queryKey: ["blocks", "madurai", date], queryFn: () => api.blocks("madurai", date),
    enabled: district === "madurai", retry: 0,
  });
  const blockList = district === "madurai" ? blocks.data?.blocks ?? [] : [];
  const activeBlock = blockList.find((b) => b.slug === block);
  const region = activeBlock ? activeBlock.slug : district;

  const districts = useQuery({ queryKey: ["districts-list"], queryFn: () => api.districts(null, 0.1), staleTime: Infinity });
  const fc = useQuery({ queryKey: ["forecast", region, date], queryFn: () => api.forecast(region, date) });
  const adv = useQuery({
    queryKey: ["advisories", "farmer", region, date],
    queryFn: () => api.advisories({ district: region, date, limit: 50 }),
    refetchInterval: 10_000,
  });
  const names = useMemo(() => (districts.data?.features ?? [])
    .map((f) => ({ slug: f.properties.slug, name: f.properties.name }))
    .sort((a, b) => a.name.localeCompare(b.name)), [districts.data]);
  const advisory = adv.data ? pickAdvisory(adv.data.advisories, crop) : null;
  const inField = fc.data?.crop_stages.map((s) => s.crop) ?? [];

  return (
    <div className="min-h-full bg-subtle md:flex md:items-center md:justify-center md:py-8">
      <Link to="/" className="fixed left-6 top-6 hidden items-center gap-1.5 text-[13px] text-muted hover:text-fg md:inline-flex">
        <ArrowLeft className="h-3.5 w-3.5" /> AgriVarsha
      </Link>
      {/* Phone frame on desktop, full screen on mobile */}
      <div className="md:w-[390px] md:rounded-[2.6rem] md:border md:border-line md:bg-zinc-900 md:p-2.5 md:shadow-sm">
        <div className="relative flex min-h-screen flex-col bg-bg md:h-[800px] md:min-h-0 md:overflow-hidden md:rounded-[2.1rem]">
          <div className="absolute left-1/2 top-2.5 z-20 hidden h-5 w-24 -translate-x-1/2 rounded-full bg-black md:block" />
          <div className="flex-1 overflow-y-auto px-4 pb-8 pt-4 md:pt-10" lang={lang}>
            <header className="flex items-center gap-2">
              <Logo className="h-8 w-8" />
              <h1 className="text-lg font-semibold tracking-tight">{t("title", lang)}</h1>
              <div className="ml-auto flex rounded-full bg-subtle p-0.5 text-[13px] font-medium">
                {(["ta", "en"] as const).map((l) => (
                  <button key={l} onClick={() => setLang(l)}
                    className={cx("rounded-full px-3 py-1", lang === l ? "bg-accent-800 text-white" : "text-muted")}>
                    {l === "ta" ? "தமிழ்" : "EN"}
                  </button>
                ))}
              </div>
            </header>

            <div className="mt-4 grid grid-cols-2 gap-2">
              <label className="rounded-2xl border border-line bg-surface px-3 py-2">
                <span className="flex items-center gap-1 text-[11px] text-muted"><MapPin className="h-3 w-3" />{t("district", lang)}</span>
                <select value={district} onChange={(e) => { setDistrict(e.target.value); setBlock(""); }}
                  className="mt-0.5 w-full bg-transparent text-[15px] font-medium outline-none">
                  {(names.length ? names : [{ slug: district, name: district }]).map((d) => <option key={d.slug} value={d.slug}>{d.name}</option>)}
                </select>
              </label>
              <label className="rounded-2xl border border-line bg-surface px-3 py-2">
                <span className="text-[11px] text-muted">{t("crop", lang)}</span>
                <select value={crop} onChange={(e) => setCrop(e.target.value)}
                  className="mt-0.5 w-full bg-transparent text-[15px] font-medium outline-none">
                  {CROPS.map((c) => (
                    <option key={c} value={c}>{CROP_EMOJI[c]} {lang === "ta" ? CROP_TA[c] : c[0].toUpperCase() + c.slice(1)}{inField.length && !inField.includes(c) ? " ·" : ""}</option>
                  ))}
                </select>
              </label>
            </div>

            {blockList.length > 0 && (
              <label className="mt-2 block rounded-2xl border border-line bg-surface px-3 py-2">
                <span className="flex items-center gap-2 text-[11px] text-muted">
                  <MapPin className="h-3 w-3" />{lang === "ta" ? "உங்கள் வட்டாரம்" : "Your block"}
                  <BlockDemoBadge className="ml-auto" />
                </span>
                <select value={activeBlock ? block : ""} onChange={(e) => setBlock(e.target.value)}
                  className="mt-0.5 w-full bg-transparent text-[15px] font-medium outline-none">
                  <option value="">{lang === "ta" ? "முழு மாவட்டம்" : "Whole district"}</option>
                  {[...blockList].sort((a, b) => a.name.localeCompare(b.name)).map((b) => (
                    <option key={b.slug} value={b.slug}>{lang === "ta" ? b.name_ta : b.name}</option>
                  ))}
                </select>
              </label>
            )}

            <section className="mt-5">
              <h2 className="mb-2 text-[13px] font-semibold uppercase tracking-wide text-faint">{t("advice", lang)}</h2>
              {adv.isError ? <RetryState onRetry={() => adv.refetch()} />
                : !adv.data ? <Skeleton className="h-48 rounded-3xl" />
                  : <AdviceCard key={`${region}-${crop}-${advisory?.id}`} a={advisory} lang={lang} />}
            </section>

            <section className="mt-6">
              <h2 className="mb-2 text-[13px] font-semibold uppercase tracking-wide text-faint">{t("weeks", lang)}</h2>
              {fc.isError ? <RetryState onRetry={() => fc.refetch()} /> : (
                <div className="grid grid-cols-2 gap-2.5">
                  {fc.data ? fc.data.forecast.map((w, i) => <WeekTile key={w.lead_week} w={w} lang={lang} i={i} />)
                    : Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-36 rounded-3xl" />)}
                </div>
              )}
            </section>
            <p className="mt-6 text-center text-[11px] text-faint">
              {fc.data?.context.forecast_source === "real" ? `Model ${fc.data.context.model_version}` : "Demo forecast"} · IMD rain to {day(fc.data?.context.observed_through)}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

function WeekTile({ w, lang, i }: { w: ForecastRow; lang: Lang; i: number }) {
  const { Icon, label, tone } = weekIcon(w);
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05, duration: 0.25 }}
      className="rounded-3xl border border-line bg-surface p-4">
      <p className="text-[12px] text-muted">{t("week", lang)} {w.lead_week} · {lang === "ta" ? taDay(w.week_start) : day(w.week_start)}</p>
      <Icon className={cx("mt-2 h-10 w-10", tone)} strokeWidth={1.5} />
      <p className="mt-2 text-2xl font-semibold tabular-nums">{Math.round(w.q50_mm)}<span className="ml-1 text-[13px] font-normal text-muted">{t("mm", lang)}</span></p>
      {label && (
        <p className={cx("mt-1 inline-block rounded-full px-2 py-0.5 text-[11px] font-medium",
          label === "heavy" ? "bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-300" : "bg-amber-50 text-amber-800 dark:bg-amber-500/10 dark:text-amber-300")}>
          {t(label, lang)} · {pct(label === "heavy" ? w.p_heavy : w.p_dry_week)}
        </p>
      )}
    </motion.div>
  );
}

function AdviceCard({ a, lang }: { a: Advisory | null; lang: Lang }) {
  const [speaking, setSpeaking] = useState(false);
  const [voiceNote, setVoiceNote] = useState(false);
  const [vote, setVote] = useState<"up" | "down" | null>(null);
  const [comment, setComment] = useState("");
  const [sent, setSent] = useState(false);
  const feedback = useMutation({
    mutationFn: (rating: "up" | "down") => api.feedback({ advisory_id: a!.id, rating, channel: "app", comment: comment || undefined }),
    onSuccess: () => setSent(true),
  });
  useEffect(() => () => window.speechSynthesis?.cancel(), []);

  if (!a) {
    return (
      <div className="rounded-3xl border border-line bg-surface p-5 text-[15px] leading-relaxed text-muted">
        <CheckCircle2 className="mb-2 h-6 w-6 text-accent-600" />{t("none", lang)}
      </div>
    );
  }
  const title = lang === "ta" ? a.title_ta : a.title_en;
  const text = lang === "ta" ? a.text_ta : (a.simple_text_en ?? a.text_en);
  const action = lang === "ta" ? a.action_ta : a.action_en;
  const tone = a.severity === "warning" ? "border-red-200 bg-red-50/60 dark:border-red-500/30 dark:bg-red-500/5"
    : a.severity === "watch" ? "border-amber-200 bg-amber-50/60 dark:border-amber-500/30 dark:bg-amber-500/5"
      : "border-line bg-surface";

  const listen = () => {
    const synth = window.speechSynthesis;
    if (!synth) return;
    if (speaking) { synth.cancel(); setSpeaking(false); return; }
    const voices = synth.getVoices();
    const ta = voices.find((v) => v.lang.toLowerCase().startsWith("ta"));
    const useTa = lang === "ta" && !!ta;
    setVoiceNote(lang === "ta" && !ta);
    const u = new SpeechSynthesisUtterance(useTa ? `${a.title_ta}. ${a.text_ta} ${a.action_ta}` : `${a.title_en}. ${a.simple_text_en ?? a.text_en} ${a.action_en}`);
    u.lang = useTa ? "ta-IN" : "en-IN";
    const en = voices.find((v) => v.lang === "en-IN") ?? voices.find((v) => v.lang.startsWith("en"));
    u.voice = useTa ? ta! : en ?? null;
    u.rate = 0.92;
    u.onend = () => setSpeaking(false);
    u.onerror = () => setSpeaking(false);
    synth.cancel();
    synth.speak(u);
    setSpeaking(true);
  };

  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}
      className={cx("rounded-3xl border p-5", tone)}>
      {a.status === "draft" && (
        <p className="mb-2 inline-block rounded-full bg-subtle px-2 py-0.5 text-[11px] text-muted">{t("pending", lang)}</p>
      )}
      <p className="text-[12px] font-medium text-muted">
        {CROP_EMOJI[a.crop]} {lang === "ta" ? HAZARD_LABEL_TA[a.hazard_type] : HAZARD_LABEL[a.hazard_type]}
      </p>
      <h3 className="mt-1 text-xl font-semibold leading-snug">{title}</h3>
      <p className="mt-2 text-[15px] leading-relaxed">{text}</p>
      <div className="mt-3 rounded-2xl bg-surface/80 p-3.5 text-[15px] leading-relaxed ring-1 ring-line">
        <p className="mb-1 text-[12px] font-semibold text-accent-700 dark:text-accent-400">✅ {t("todo", lang)}</p>
        {action}
      </div>

      <button onClick={listen}
        className="mt-4 flex h-14 w-full items-center justify-center gap-2 rounded-2xl bg-accent-800 text-[17px] font-semibold text-white active:scale-[0.99] dark:bg-accent-700">
        {speaking ? <><Square className="h-5 w-5" /> {t("stop", lang)}</> : <><Volume2 className="h-5 w-5" /> 🔊 {t("listen", lang)}</>}
      </button>
      {voiceNote && <p className="mt-2 text-center text-[12px] text-muted">{t("noVoice", lang)}</p>}

      <div className="mt-5">
        <AnimatePresence mode="wait">
          {sent ? (
            <motion.p key="thanks" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex items-center gap-2 text-[14px] text-accent-800 dark:text-accent-400">
              <CheckCircle2 className="h-5 w-5 shrink-0" /> {t("thanks", lang)}
            </motion.p>
          ) : (
            <motion.div key="ask" exit={{ opacity: 0 }}>
              <p className="text-[14px] font-medium">{t("useful", lang)}</p>
              <div className="mt-2 grid grid-cols-2 gap-2">
                {(["up", "down"] as const).map((v) => (
                  <button key={v} onClick={() => setVote(v)} aria-pressed={vote === v}
                    className={cx("flex h-14 items-center justify-center gap-2 rounded-2xl border text-2xl transition-colors",
                      vote === v ? "border-accent-600 bg-accent-50 dark:bg-accent-500/10" : "border-line bg-surface")}>
                    {v === "up" ? <ThumbsUp className="h-6 w-6" /> : <ThumbsDown className="h-6 w-6" />}
                  </button>
                ))}
              </div>
              <AnimatePresence>
                {vote && (
                  <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }}
                    className="overflow-hidden">
                    <div className="mt-2 flex gap-2">
                      <input value={comment} onChange={(e) => setComment(e.target.value)} placeholder={t("comment", lang)}
                        className="h-12 min-w-0 flex-1 rounded-2xl border border-line bg-surface px-3 text-[15px] outline-none focus:border-accent-600" />
                      <button onClick={() => feedback.mutate(vote)} disabled={feedback.isPending}
                        className="h-12 rounded-2xl bg-accent-800 px-4 text-[15px] font-medium text-white disabled:opacity-60">
                        {t("send", lang)}
                      </button>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
              {feedback.isError && <p className="mt-2 text-[13px] text-red-600">Please try again.</p>}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}
