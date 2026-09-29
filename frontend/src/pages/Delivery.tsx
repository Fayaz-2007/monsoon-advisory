import { AnimatePresence, motion } from "framer-motion";
import { Inbox, MessageSquareQuote, ThumbsDown, ThumbsUp } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { BroadcastStatus, Channel } from "../api/types";
import { CHANNEL_META, useBroadcast } from "../components/LiveDelivery";
import { IvrPhone, SmsPhone, WhatsAppPhone } from "../components/PhoneMockups";
import {
  Card, CardHeader, Chip, CountUp, cx, EmptyState, fadeUp, Page, PageTitle, RetryState, SeverityChip, Skeleton,
  SkeletonLines, stagger,
} from "../components/ui";
import { compact, CROP_EMOJI, pct, timeAgo } from "../lib/format";

const STAGE = { queued: 0, sending: 1, delivering: 2, reading: 3, completed: 4 } as const;

export default function Delivery() {
  const [params, setParams] = useSearchParams();
  const [lang, setLang] = useState<"en" | "ta">("en");
  const list = useQuery({ queryKey: ["broadcasts"], queryFn: () => api.broadcasts(30), refetchInterval: 4000 });
  const broadcasts = list.data?.broadcasts ?? [];
  const selected = params.get("broadcast") ? Number(params.get("broadcast")) : broadcasts[0]?.broadcast_id ?? null;
  const status = useBroadcast(selected);
  const b = status.data;

  useEffect(() => {
    if (!params.get("broadcast") && broadcasts[0]) {
      const p = new URLSearchParams(params);
      p.set("broadcast", String(broadcasts[0].broadcast_id));
      setParams(p, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [broadcasts[0]?.broadcast_id]);

  const choose = (id: number) => {
    const p = new URLSearchParams(params);
    p.set("broadcast", String(id));
    setParams(p, { replace: true });
  };

  if (list.isError) return <Page><RetryState onRetry={() => list.refetch()} /></Page>;

  return (
    <Page>
      <PageTitle title="Delivery monitor"
        subtitle="What farmers actually receive on each channel, and how far each message got (simulated gateway)."
        right={
          <div className="flex rounded-xl bg-subtle p-1 text-[13px]">
            {(["en", "ta"] as const).map((l) => (
              <button key={l} onClick={() => setLang(l)}
                className={cx("rounded-lg px-3 py-1.5 font-medium", lang === l ? "bg-surface text-fg ring-1 ring-line" : "text-muted")}>
                {l === "en" ? "English" : "தமிழ்"}
              </button>
            ))}
          </div>
        } />

      {list.data && !broadcasts.length ? (
        <Card>
          <EmptyState icon={<Inbox className="h-5 w-5" />} title="No broadcasts yet">
            Approve an advisory in the <Link to="/app/advisories" className="text-accent-700 underline dark:text-accent-400">queue</Link> and broadcast it to see it here.
          </EmptyState>
        </Card>
      ) : (
        <>
          <motion.div variants={fadeUp} className="grid gap-6 md:grid-cols-3">
            {b ? <Phones b={b} lang={lang} /> : Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="mx-auto h-[516px] w-[260px] rounded-[2.2rem]" />)}
          </motion.div>

          <div className="mt-6 grid gap-4 lg:grid-cols-5">
            <Card className="lg:col-span-3">
              <CardHeader title="Delivery funnel"
                subtitle={b ? <>{b.status === "completed" ? "Completed" : "In progress"} · {compact(b.total_recipients)} recipients · {b.channels.length} channels</> : "…"} />
              <div className="px-5 pb-5">{b ? <Funnel b={b} /> : <SkeletonLines n={4} />}</div>
            </Card>
            <Card className="lg:col-span-2">
              <CardHeader title="Farmer feedback" subtitle="Live 👍/👎 for this advisory (includes the Farmer app)" />
              <div className="px-5 pb-5">{b ? <FeedbackBox advisoryId={b.advisory_id} /> : <SkeletonLines n={3} />}</div>
            </Card>
          </div>

          <Card className="mt-4">
            <CardHeader title="Past broadcasts" subtitle="Newest first" />
            <div className="px-2 pb-3">
              {!list.data ? <SkeletonLines n={4} /> : (
                <motion.ul initial="hidden" animate="show" variants={stagger} className="divide-y divide-line">
                  {broadcasts.map((x) => (
                    <motion.li key={x.broadcast_id} variants={fadeUp}>
                      <button onClick={() => choose(x.broadcast_id)}
                        className={cx("flex w-full flex-wrap items-center gap-2 rounded-xl px-3 py-2.5 text-left text-sm",
                          x.broadcast_id === selected ? "bg-subtle" : "hover:bg-subtle/60")}>
                        <span>{CROP_EMOJI[x.crop]}</span>
                        <span className="font-medium">{x.title_en}</span>
                        <SeverityChip severity={x.severity} />
                        <span className="text-muted">{x.district}</span>
                        <span className="flex gap-1">{x.channels.map((c) => <Chip key={c}>{CHANNEL_META[c].label}</Chip>)}</span>
                        <span className="ml-auto text-[12px] text-muted tabular-nums">
                          {compact(x.total_recipients)} · {x.status === "completed" ? timeAgo(x.created_at) : "sending…"}
                        </span>
                      </button>
                    </motion.li>
                  ))}
                </motion.ul>
              )}
            </div>
          </Card>
        </>
      )}
    </Page>
  );
}

function Phones({ b, lang }: { b: BroadcastStatus; lang: "en" | "ta" }) {
  const ch = (c: Channel) => b.channels.find((x) => x.channel === c);
  const sms = ch("sms");
  const wa = ch("whatsapp");
  const ivr = ch("ivr");
  const text = (c: typeof sms) => (c ? (lang === "en" ? c.content_en : c.content_ta) : null);
  const missing = (label: string) => (
    <div className="mx-auto flex h-[516px] w-[260px] items-center justify-center rounded-[2.2rem] border border-dashed border-line text-[13px] text-faint">
      {label} not used in this broadcast
    </div>
  );
  return (
    <AnimatePresence mode="wait">
      <motion.div key={`${b.broadcast_id}-${lang}`} className="contents">
        <div>
          <p className="mb-2 text-center text-[12px] font-medium text-muted">SMS</p>
          {sms ? <SmsPhone text={text(sms)!} lang={lang} segments={lang === "en" ? sms.sms_segments_en : sms.sms_segments_ta} /> : missing("SMS")}
        </div>
        <div>
          <p className="mb-2 text-center text-[12px] font-medium text-muted">WhatsApp</p>
          {wa ? <WhatsAppPhone text={text(wa)!} lang={lang} stage={STAGE[wa.status]} /> : missing("WhatsApp")}
        </div>
        <div>
          <p className="mb-2 text-center text-[12px] font-medium text-muted">Voice call (IVR)</p>
          {ivr ? <IvrPhone script={text(ivr)!} lang={lang} stage={STAGE[ivr.status]} /> : missing("Voice")}
        </div>
      </motion.div>
    </AnimatePresence>
  );
}

function Funnel({ b }: { b: BroadcastStatus }) {
  const t = b.totals;
  const steps = [
    { k: "Queued", v: t.queued },
    { k: "Sent", v: t.sent },
    { k: "Delivered / answered", v: t.delivered },
    { k: "Read / listened", v: t.read },
  ];
  const max = Math.max(1, t.queued);
  return (
    <div className="space-y-3">
      {steps.map((s, i) => (
        <div key={s.k}>
          <div className="mb-1 flex justify-between text-[13px]">
            <span className="text-muted">{s.k}</span>
            <span className="font-medium tabular-nums">
              <CountUp value={s.v} format={(n) => compact(Math.round(n))} />
              {i > 0 && <span className="ml-2 text-[12px] font-normal text-faint">{pct(s.v / max)}</span>}
            </span>
          </div>
          <div className="h-3 overflow-hidden rounded-full bg-subtle">
            <motion.div className={cx("h-full rounded-full", i === 3 ? "bg-accent-600" : "bg-accent-600/40")}
              animate={{ width: `${(s.v / max) * 100}%` }} transition={{ duration: 0.6, ease: "easeOut" }} />
          </div>
        </div>
      ))}
      <div className="grid grid-cols-2 gap-2 pt-2 sm:grid-cols-4">
        {b.channels.map((c) => (
          <div key={c.channel} className="rounded-xl bg-subtle px-3 py-2 text-[12px]">
            <p className="font-medium">{CHANNEL_META[c.channel].label}</p>
            <p className="text-muted">{pct(c.delivery_rate)} {CHANNEL_META[c.channel].delivered.toLowerCase()}</p>
            <p className="text-muted">{pct(c.read_rate)} {CHANNEL_META[c.channel].read.toLowerCase()}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function FeedbackBox({ advisoryId }: { advisoryId: number }) {
  const q = useQuery({
    queryKey: ["feedback", advisoryId],
    queryFn: () => api.feedbackSummary(advisoryId),
    refetchInterval: 3000,
  });
  if (!q.data) return <SkeletonLines n={3} />;
  const t = q.data.totals;
  return (
    <div>
      <div className="grid grid-cols-3 gap-2 text-center">
        <div className="rounded-xl bg-subtle py-2.5"><p className="flex items-center justify-center gap-1 text-[12px] text-muted"><ThumbsUp className="h-3 w-3" /> Useful</p><p className="text-lg font-semibold tabular-nums"><CountUp value={t.up} /></p></div>
        <div className="rounded-xl bg-subtle py-2.5"><p className="flex items-center justify-center gap-1 text-[12px] text-muted"><ThumbsDown className="h-3 w-3" /> Not useful</p><p className="text-lg font-semibold tabular-nums"><CountUp value={t.down} /></p></div>
        <div className="rounded-xl bg-subtle py-2.5"><p className="text-[12px] text-muted">Positive</p><p className="text-lg font-semibold tabular-nums">{pct(t.positive_rate)}</p></div>
      </div>
      <p className="mt-2 text-[11px] text-faint">{t.real} from farmers in the app · {t.simulated} simulated responses</p>
      <ul className="mt-3 space-y-2">
        <AnimatePresence initial={false}>
          {q.data.recent_comments.slice(0, 5).map((c) => (
            <motion.li key={c.id} layout initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }}
              className="flex gap-2 text-[13px]">
              <MessageSquareQuote className="mt-0.5 h-3.5 w-3.5 shrink-0 text-faint" />
              <span>
                {c.rating === 1 ? "👍" : "👎"} {c.comment}
                <span className="text-[11px] text-faint"> · {c.channel ?? "app"}{c.simulated ? " · simulated" : ""} · {timeAgo(c.created_at)}</span>
              </span>
            </motion.li>
          ))}
        </AnimatePresence>
      </ul>
      {!q.data.recent_comments.length && <p className="mt-3 text-[13px] text-faint">No comments yet.</p>}
    </div>
  );
}

