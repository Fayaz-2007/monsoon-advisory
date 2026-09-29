import { AnimatePresence, motion } from "framer-motion";
import { Check, CheckCheck, MessageCircle, MessageSquare, Phone, Smartphone } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { api } from "../api/client";
import type { BroadcastChannel, BroadcastStatus, Channel } from "../api/types";
import { compact, pct } from "../lib/format";
import { CountUp, cx, Skeleton } from "./ui";

export const CHANNEL_META: Record<Channel, { label: string; icon: typeof Phone; read: string; delivered: string }> = {
  sms: { label: "SMS", icon: MessageSquare, delivered: "Delivered", read: "Read" },
  whatsapp: { label: "WhatsApp", icon: MessageCircle, delivered: "Delivered", read: "Read" },
  ivr: { label: "Voice call (IVR)", icon: Phone, delivered: "Answered", read: "Listened fully" },
  app: { label: "App push", icon: Smartphone, delivered: "Delivered", read: "Opened" },
};

/** Polls a broadcast until it completes and animates the per-channel funnel. */
export function useBroadcast(id: number | null, onDone?: (b: BroadcastStatus) => void) {
  const q = useQuery({
    queryKey: ["broadcast", id],
    queryFn: () => api.broadcastStatus(id!),
    enabled: id !== null,
    refetchInterval: (query) => (query.state.data?.status === "completed" ? false : 600),
    placeholderData: undefined,
  });
  const done = q.data?.status === "completed";
  useEffect(() => {
    if (done && q.data) onDone?.(q.data);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [done]);
  return q;
}

export function LiveDelivery({ status }: { status: BroadcastStatus | undefined }) {
  if (!status) return <div className="space-y-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-16" />)}</div>;
  const t = status.totals;
  return (
    <div>
      <div className="mb-4 flex items-baseline justify-between">
        <p className="text-sm font-medium">
          {status.status === "completed" ? "Delivered" : "Sending…"}
          <span className="ml-2 font-normal text-muted">to {compact(status.total_recipients)} farmers</span>
        </p>
        <span className="text-[12px] text-faint">{status.delivery_mode} gateway</span>
      </div>
      <div className="mb-5 h-1 overflow-hidden rounded-full bg-subtle">
        <motion.div className="h-full bg-accent-600" animate={{ width: `${Math.round(status.progress * 100)}%` }}
          transition={{ duration: 0.5, ease: "linear" }} />
      </div>
      <div className="grid grid-cols-4 gap-2 text-center">
        {([["Queued", t.queued], ["Sent", t.sent], ["Delivered", t.delivered], ["Read", t.read]] as const).map(([k, v]) => (
          <div key={k} className="rounded-xl bg-subtle px-2 py-2.5">
            <p className="text-[11px] text-muted">{k}</p>
            <p className="text-lg font-semibold tabular-nums"><CountUp value={v} format={(n) => compact(Math.round(n))} /></p>
          </div>
        ))}
      </div>
      <ul className="mt-4 space-y-2">
        {status.channels.map((c) => <ChannelRow key={c.channel} c={c} />)}
      </ul>
    </div>
  );
}

function ChannelRow({ c }: { c: BroadcastChannel }) {
  const m = CHANNEL_META[c.channel];
  const Icon = m.icon;
  const stage = { queued: 0, sending: 1, delivering: 2, reading: 3, completed: 4 }[c.status];
  return (
    <li className="rounded-xl border border-line px-3 py-2.5">
      <div className="flex items-center gap-2 text-sm">
        <Icon className="h-4 w-4 text-muted" />
        <span className="font-medium">{m.label}</span>
        <span className="ml-auto flex items-center gap-1 text-[12px] text-muted tabular-nums">
          <Ticks stage={stage} />
          {compact(c.read)} / {compact(c.recipients)}
        </span>
      </div>
      <div className="mt-2 grid grid-cols-3 gap-1.5 text-[11px] text-muted">
        <Bar label="Sent" v={c.sent} of={c.recipients} />
        <Bar label={m.delivered} v={c.delivered} of={c.recipients} />
        <Bar label={m.read} v={c.read} of={c.recipients} accent />
      </div>
    </li>
  );
}

function Bar({ label, v, of, accent }: { label: string; v: number; of: number; accent?: boolean }) {
  const f = of ? v / of : 0;
  return (
    <div>
      <div className="flex justify-between"><span>{label}</span><span className="tabular-nums">{pct(f)}</span></div>
      <div className="mt-1 h-1 overflow-hidden rounded-full bg-subtle">
        <motion.div className={cx("h-full rounded-full", accent ? "bg-accent-600" : "bg-zinc-400 dark:bg-zinc-500")}
          animate={{ width: `${f * 100}%` }} transition={{ duration: 0.5 }} />
      </div>
    </div>
  );
}

/** WhatsApp-style ticks that animate in: ✓ sent, ✓✓ delivered, blue ✓✓ read. */
export function Ticks({ stage }: { stage: number }) {
  return (
    <span className="inline-flex w-5 justify-center">
      <AnimatePresence mode="wait" initial={false}>
        {stage <= 0 ? (
          <motion.span key="q" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="h-1.5 w-1.5 rounded-full bg-zinc-400" />
        ) : stage === 1 ? (
          <motion.span key="s" initial={{ opacity: 0, scale: 0.6 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0 }}><Check className="h-3.5 w-3.5" /></motion.span>
        ) : (
          <motion.span key={stage >= 3 ? "r" : "d"} initial={{ opacity: 0, scale: 0.6 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0 }}>
            <CheckCheck className={cx("h-3.5 w-3.5", stage >= 3 && "text-sky-500")} />
          </motion.span>
        )}
      </AnimatePresence>
    </span>
  );
}
