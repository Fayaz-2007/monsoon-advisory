import { AnimatePresence, motion } from "framer-motion";
import {
  Check, CheckCircle2, ClipboardList, History, Languages, Pencil, Search, Send, ShieldCheck, Sparkles, X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Advisory, AdvisoryDetail, AdvisoryStatus, Severity } from "../api/types";
import { BroadcastDialog } from "../components/BroadcastDialog";
import { Dialog } from "../components/Dialog";
import {
  BlockDemoBadge, Button, Card, Chip, cx, EmptyState, fadeUp, Page, PageTitle, RetryState, SeverityChip, SkeletonLines, stagger, useToast,
} from "../components/ui";
import { useAppState } from "../lib/appState";
import { compact, CROP_EMOJI, HAZARD_LABEL, pct, timeAgo, titleCase } from "../lib/format";

const TABS: { key: AdvisoryStatus; label: string }[] = [
  { key: "draft", label: "Drafts" },
  { key: "approved", label: "Approved" },
  { key: "sent", label: "Sent" },
  { key: "rejected", label: "Rejected" },
];

export default function Advisories() {
  const { date } = useAppState();
  const [params, setParams] = useSearchParams();
  const [status, setStatus] = useState<AdvisoryStatus>("draft");
  const [severity, setSeverity] = useState<Severity | "">("");
  const [search, setSearch] = useState("");
  const selectedId = params.get("id") ? Number(params.get("id")) : null;
  const select = (id: number | null) => {
    const p = new URLSearchParams(params);
    if (id === null) p.delete("id");
    else p.set("id", String(id));
    setParams(p, { replace: true });
  };

  const list = useQuery({
    queryKey: ["advisories", "queue", date, status, severity],
    queryFn: () => api.advisories({ date, status, severity: severity || undefined, limit: 300 }),
    placeholderData: keepPreviousData,
  });
  const items = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (list.data?.advisories ?? []).filter((a) =>
      !q || a.district.toLowerCase().includes(q) || a.crop.includes(q) || a.title_en.toLowerCase().includes(q));
  }, [list.data, search]);

  // Select the first item when nothing (valid) is selected.
  useEffect(() => {
    if (!list.data || list.isPlaceholderData) return;
    if (selectedId === null && items.length) select(items[0].id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [list.data, list.isPlaceholderData]);

  const counts = list.data?.status_counts ?? {};

  return (
    <Page>
      <PageTitle title="Advisory queue"
        subtitle="Drafted automatically from hazards × crop stage. Review, edit, approve, then broadcast." />
      <div className="grid gap-4 lg:grid-cols-[380px_1fr]">
        {/* list */}
        <Card className="flex min-h-[560px] flex-col lg:max-h-[calc(100vh-190px)]">
          <div className="border-b border-line p-3">
            <div className="flex gap-1 rounded-xl bg-subtle p-1">
              {TABS.map((t) => (
                <button key={t.key} onClick={() => { setStatus(t.key); select(null); }}
                  className={cx("relative flex-1 rounded-lg px-2 py-1.5 text-[13px] font-medium transition-colors",
                    status === t.key ? "text-fg" : "text-muted hover:text-fg")}>
                  {status === t.key && <motion.span layoutId="adv-tab" className="absolute inset-0 rounded-lg bg-surface ring-1 ring-line" transition={{ duration: 0.2 }} />}
                  <span className="relative">{t.label} <span className="text-faint tabular-nums">{counts[t.key] ?? 0}</span></span>
                </button>
              ))}
            </div>
            <div className="mt-2 flex gap-2">
              <label className="flex h-9 flex-1 items-center gap-2 rounded-xl border border-line px-3">
                <Search className="h-4 w-4 text-faint" />
                <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="District or crop"
                  className="w-full bg-transparent text-sm outline-none placeholder:text-faint" />
              </label>
              <select value={severity} onChange={(e) => setSeverity(e.target.value as Severity | "")}
                className="h-9 rounded-xl border border-line bg-surface px-2 text-[13px]">
                <option value="">All levels</option>
                <option value="warning">Warning</option>
                <option value="watch">Watch</option>
                <option value="info">Info</option>
              </select>
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {list.isError ? <RetryState onRetry={() => list.refetch()} />
              : !list.data ? <SkeletonLines n={10} />
                : items.length ? (
                  <motion.ul key={`${status}-${severity}-${date}`} initial="hidden" animate="show" variants={stagger}>
                    {items.map((a) => <QueueItem key={a.id} a={a} active={a.id === selectedId} onClick={() => select(a.id)} />)}
                  </motion.ul>
                ) : (
                  <EmptyState icon={<ClipboardList className="h-5 w-5" />} title={`No ${status} advisories`}>
                    {status === "draft" ? "Everything has been reviewed for this date." : "Nothing here yet."}
                  </EmptyState>
                )}
          </div>
        </Card>

        {/* detail */}
        <div className="min-w-0">
          <AnimatePresence mode="wait">
            {selectedId ? (
              <motion.div key={selectedId} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                transition={{ duration: 0.2 }}>
                <AdvisoryPanel id={selectedId} />
              </motion.div>
            ) : (
              <Card><EmptyState icon={<ClipboardList className="h-5 w-5" />} title="Select an advisory to review" /></Card>
            )}
          </AnimatePresence>
        </div>
      </div>
    </Page>
  );
}

function QueueItem({ a, active, onClick }: { a: Advisory; active: boolean; onClick: () => void }) {
  return (
    <motion.li variants={fadeUp}>
      <button onClick={onClick}
        className={cx("w-full rounded-xl px-3 py-2.5 text-left transition-colors", active ? "bg-subtle ring-1 ring-line" : "hover:bg-subtle/70")}>
        <div className="flex items-center gap-2">
          <span className="text-base leading-none">{CROP_EMOJI[a.crop]}</span>
          <span className="truncate text-sm font-medium">{a.title_en}</span>
        </div>
        <div className="mt-1 flex items-center gap-1.5 text-[12px] text-muted">
          <SeverityChip severity={a.severity} />
          <span className="truncate">{a.district} · {titleCase(a.stage)}</span>
          {isBlockAdvisory(a) && <span className="shrink-0 rounded-full bg-violet-50 px-1.5 text-[10px] font-medium text-violet-700 dark:bg-violet-500/10 dark:text-violet-300" title="Block level · demo data">demo</span>}
          <span className="ml-auto shrink-0 tabular-nums">{compact(a.farmers_targeted)}</span>
        </div>
      </button>
    </motion.li>
  );
}

function AdvisoryPanel({ id }: { id: number }) {
  const qc = useQueryClient();
  const [lang, setLang] = useState<"en" | "ta">("en");
  const [editing, setEditing] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [broadcasting, setBroadcasting] = useState(false);
  const [toast, showToast] = useToast();
  const q = useQuery({ queryKey: ["advisory", id], queryFn: () => api.advisory(id) });
  const a = q.data;

  const after = (msg: string) => (d: AdvisoryDetail) => {
    qc.setQueryData(["advisory", id], (old: AdvisoryDetail | undefined) => ({ ...(old ?? {}), ...d }) as AdvisoryDetail);
    qc.invalidateQueries({ queryKey: ["advisory", id] });
    qc.invalidateQueries({ queryKey: ["advisories"] });
    qc.invalidateQueries({ queryKey: ["overview"] });
    showToast(msg);
  };
  const approve = useMutation({ mutationFn: () => api.approve(id, "officer"), onSuccess: after("Approved. Ready to broadcast."), onError: () => showToast("Couldn't approve. Try again.") });

  if (q.isError) return <Card><RetryState onRetry={() => q.refetch()} /></Card>;
  if (!a) return <Card><SkeletonLines n={10} /></Card>;

  const title = lang === "en" ? a.title_en : a.title_ta;
  const text = lang === "en" ? a.text_en : a.text_ta;
  const action = lang === "en" ? a.action_en : a.action_ta;

  return (
    <motion.div initial="hidden" animate="show" variants={stagger} className="space-y-4">
      <Card className="p-5">
        <div className="flex flex-wrap items-center gap-2">
          <SeverityChip severity={a.severity} />
          <Chip>{titleCase(a.status)}</Chip>
          {a.edited && <Chip><Pencil className="h-3 w-3" /> Edited</Chip>}
          <Chip>{CROP_EMOJI[a.crop]} {titleCase(a.crop)} · {titleCase(a.stage)}</Chip>
          <Chip>{a.district}</Chip>
          {isBlockAdvisory(a) && <BlockDemoBadge />}
          <div className="ml-auto flex rounded-lg bg-subtle p-0.5 text-[12px]">
            {(["en", "ta"] as const).map((l) => (
              <button key={l} onClick={() => setLang(l)}
                className={cx("rounded-md px-2.5 py-1 font-medium", lang === l ? "bg-surface text-fg ring-1 ring-line" : "text-muted")}>
                {l === "en" ? "English" : "தமிழ்"}
              </button>
            ))}
          </div>
        </div>

        <AnimatePresence mode="wait">
          <motion.div key={lang} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.15 }}>
            <h2 className="mt-4 text-xl font-semibold tracking-tight" lang={lang}>{title}</h2>
            <p className="mt-2 text-[15px] leading-relaxed" lang={lang}>{text}</p>
            <div className="mt-4 rounded-xl bg-accent-50 p-3.5 text-[14px] leading-relaxed text-accent-900 dark:bg-accent-500/10 dark:text-accent-100" lang={lang}>
              <p className="mb-1 flex items-center gap-1.5 text-[12px] font-medium uppercase tracking-wide text-accent-700 dark:text-accent-400">
                <CheckCircle2 className="h-3.5 w-3.5" /> {lang === "en" ? "What to do" : "செய்ய வேண்டியது"}
              </p>
              {action}
            </div>
            {lang === "ta" && !a.tamil_reviewed && (
              <p className="mt-2 flex items-center gap-1.5 text-[12px] text-amber-700 dark:text-amber-300">
                <Languages className="h-3.5 w-3.5" /> Tamil text not yet reviewed by a native speaker
              </p>
            )}
            {lang === "en" && a.simple_text_en && (
              <p className="mt-3 flex gap-2 rounded-xl border border-line p-3 text-[13px] text-muted">
                <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0" /> <span><b className="font-medium text-fg">Simpler wording ({a.rephrased_by}):</b> {a.simple_text_en}</span>
              </p>
            )}
          </motion.div>
        </AnimatePresence>

        <div className="mt-5 flex flex-wrap gap-2">
          {a.status === "draft" && (
            <Button variant="primary" onClick={() => approve.mutate()} disabled={approve.isPending}>
              <Check className="h-4 w-4" /> {approve.isPending ? "Approving…" : "Approve"}
            </Button>
          )}
          {a.status === "approved" && (
            <Button variant="primary" onClick={() => setBroadcasting(true)}><Send className="h-4 w-4" /> Broadcast</Button>
          )}
          {["draft", "approved", "rejected"].includes(a.status) && (
            <Button onClick={() => setEditing(true)}><Pencil className="h-4 w-4" /> Edit</Button>
          )}
          {["draft", "approved"].includes(a.status) && (
            <Button variant="danger" onClick={() => setRejecting(true)}><X className="h-4 w-4" /> Reject</Button>
          )}
        </div>
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card className="p-5">
          <p className="mb-2 flex items-center gap-1.5 text-[13px] font-medium"><ShieldCheck className="h-4 w-4 text-muted" /> Why this advisory</p>
          <p className="text-[13px] leading-relaxed text-muted">{a.hazard_why}</p>
          <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-[12px]">
            <dt className="text-faint">Hazard</dt><dd>{HAZARD_LABEL[a.hazard_type]}{a.hazard_subtype ? ` (${a.hazard_subtype})` : ""}</dd>
            <dt className="text-faint">Probability</dt><dd>{a.hazard_lead_week === 0 ? "Observed" : pct(a.hazard_probability)}</dd>
            <dt className="text-faint">Lead</dt><dd>{a.hazard_lead_week === 0 ? "Now" : `Week ${a.hazard_lead_week}`}</dd>
            <dt className="text-faint">Confidence</dt><dd>{a.hazard_confidence}</dd>
            <dt className="text-faint">Rule</dt><dd className="font-mono text-[11px]">{a.rule_id}</dd>
            <dt className="text-faint">Farmers</dt><dd>{compact(a.farmers_targeted)} <span className="text-faint">(mock)</span></dd>
            <dt className="text-faint">Forecast</dt><dd>{a.forecast_source === "real" ? "Real model" : "Mock"}{a.scenario !== "none" ? ` · ${titleCase(a.scenario)}` : ""}</dd>
          </dl>
          <p className="mt-3 text-[11px] leading-relaxed text-faint">{a.source_note}</p>
        </Card>
        <Card className="p-5">
          <p className="mb-3 flex items-center gap-1.5 text-[13px] font-medium"><History className="h-4 w-4 text-muted" /> Audit trail</p>
          <motion.ol initial="hidden" animate="show" variants={stagger} className="relative space-y-3 border-l border-line pl-4">
            {a.events.map((e, i) => (
              <motion.li key={i} variants={fadeUp} className="relative text-[13px]">
                <span className={cx("absolute -left-[21px] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-surface",
                  e.action === "approved" || e.action === "broadcast" ? "bg-accent-600" : e.action === "rejected" ? "bg-red-500" : "bg-zinc-400")} />
                <span className="font-medium">{titleCase(e.action)}</span>
                <span className="text-muted"> · {e.actor ?? "system"} · {timeAgo(e.at)}</span>
                {e.note && <p className="text-[12px] text-muted">“{e.note}”</p>}
                {e.action === "broadcast" && typeof e.payload.recipients === "number" && (
                  <p className="text-[12px] text-muted">{compact(e.payload.recipients)} recipients · {(e.payload.channels as string[]).join(", ")}</p>
                )}
                {e.action === "edited" && e.payload.after !== undefined && (
                  <p className="text-[12px] text-muted">Changed {Object.keys(e.payload.after as object).join(", ")}</p>
                )}
              </motion.li>
            ))}
          </motion.ol>
        </Card>
      </div>

      <EditDialog a={a} open={editing} onClose={() => setEditing(false)} onSaved={after("Saved. The advisory is back in drafts for approval.")} />
      <RejectDialog a={a} open={rejecting} onClose={() => setRejecting(false)} onDone={after("Rejected.")} />
      <BroadcastDialog advisory={a} open={broadcasting} onClose={() => setBroadcasting(false)} />
      <AnimatePresence>{toast}</AnimatePresence>
    </motion.div>
  );
}

function EditDialog({ a, open, onClose, onSaved }: {
  a: AdvisoryDetail; open: boolean; onClose: () => void; onSaved: (d: AdvisoryDetail) => void;
}) {
  const [f, setF] = useState(() => pick(a));
  useEffect(() => { if (open) setF(pick(a)); }, [open, a]);
  const save = useMutation({
    mutationFn: () => api.edit(a.id, { ...diff(pick(a), f), reviewer: "officer" }),
    onSuccess: (d) => { onSaved(d); onClose(); },
  });
  const changed = Object.keys(diff(pick(a), f)).length > 0;
  const field = (k: keyof ReturnType<typeof pick>, label: string, rows = 3) => (
    <label className="block">
      <span className="text-[12px] font-medium text-muted">{label}</span>
      <textarea rows={rows} value={f[k] as string} onChange={(e) => setF({ ...f, [k]: e.target.value })}
        className="mt-1 w-full resize-y rounded-xl border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent-600" />
    </label>
  );
  return (
    <Dialog open={open} onClose={onClose} wide title="Edit advisory">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-3">
          <p className="text-[12px] font-semibold uppercase tracking-wide text-faint">English</p>
          {field("title_en", "Title", 1)}
          {field("text_en", "Advice", 4)}
          {field("action_en", "What to do", 3)}
        </div>
        <div className="space-y-3">
          <p className="text-[12px] font-semibold uppercase tracking-wide text-faint">தமிழ்</p>
          {field("title_ta", "தலைப்பு", 1)}
          {field("text_ta", "ஆலோசனை", 4)}
          {field("action_ta", "செய்ய வேண்டியது", 3)}
        </div>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-4">
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={f.tamil_reviewed} onChange={(e) => setF({ ...f, tamil_reviewed: e.target.checked })}
            className="h-4 w-4 accent-green-700" /> Tamil reviewed
        </label>
        <label className="flex items-center gap-2 text-sm">
          Severity
          <select value={f.severity} onChange={(e) => setF({ ...f, severity: e.target.value as Severity })}
            className="h-8 rounded-lg border border-line bg-surface px-2 text-[13px]">
            <option value="info">Info</option><option value="watch">Watch</option><option value="warning">Warning</option>
          </select>
        </label>
      </div>
      {save.isError && <p className="mt-3 text-[13px] text-red-600 dark:text-red-400">Couldn't save. Please try again.</p>}
      <div className="mt-5 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!changed || save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? "Saving…" : "Save changes"}
        </Button>
      </div>
    </Dialog>
  );
}

function pick(a: AdvisoryDetail) {
  return {
    title_en: a.title_en, text_en: a.text_en, action_en: a.action_en,
    title_ta: a.title_ta, text_ta: a.text_ta, action_ta: a.action_ta,
    tamil_reviewed: a.tamil_reviewed, severity: a.severity,
  };
}

function diff<T extends Record<string, unknown>>(before: T, after: T): Partial<T> {
  const out: Partial<T> = {};
  for (const k of Object.keys(after) as (keyof T)[]) if (after[k] !== before[k]) out[k] = after[k];
  return out;
}

function RejectDialog({ a, open, onClose, onDone }: {
  a: AdvisoryDetail; open: boolean; onClose: () => void; onDone: (d: AdvisoryDetail) => void;
}) {
  const [reason, setReason] = useState("");
  const m = useMutation({
    mutationFn: () => api.reject(a.id, "officer", reason || undefined),
    onSuccess: (d) => { onDone(d); onClose(); setReason(""); },
  });
  return (
    <Dialog open={open} onClose={onClose} title="Reject advisory">
      <p className="text-sm text-muted">“{a.title_en}” for {a.district} will not be sent.</p>
      <textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (optional)"
        className="mt-3 w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent-600" />
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="danger" disabled={m.isPending} onClick={() => m.mutate()}>{m.isPending ? "Rejecting…" : "Reject"}</Button>
      </div>
    </Dialog>
  );
}

/** Advisories for MOCK block-level demo regions (Madurai blocks) use region ids above 90000. */
function isBlockAdvisory(a: { region_id: number }): boolean {
  return a.region_id > 90000;
}
