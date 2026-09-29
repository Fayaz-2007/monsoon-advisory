import { motion } from "framer-motion";
import { Radio, Send } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { AdvisoryDetail, Channel } from "../api/types";
import { compact } from "../lib/format";
import { Dialog } from "./Dialog";
import { CHANNEL_META, LiveDelivery, useBroadcast } from "./LiveDelivery";
import { Button, cx } from "./ui";

// MOCK reach shares come from the backend's farmer registry; shown here only as labels.
const ALL: Channel[] = ["sms", "whatsapp", "ivr", "app"];

export function BroadcastDialog({ advisory, open, onClose }: {
  advisory: AdvisoryDetail; open: boolean; onClose: () => void;
}) {
  const qc = useQueryClient();
  const [channels, setChannels] = useState<Channel[]>(ALL);
  const [broadcastId, setBroadcastId] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);
  const start = useMutation({
    mutationFn: () => api.broadcast(advisory.id, channels, "officer"),
    onSuccess: (b) => {
      setBroadcastId(b.broadcast_id);
      qc.setQueryData(["broadcast", b.broadcast_id], b);
      qc.invalidateQueries({ queryKey: ["advisories"] });
      qc.invalidateQueries({ queryKey: ["advisory", advisory.id] });
    },
    onError: () => setFailed(true),
  });
  const status = useBroadcast(broadcastId, () => {
    qc.invalidateQueries({ queryKey: ["overview"] });
    qc.invalidateQueries({ queryKey: ["broadcasts"] });
    qc.invalidateQueries({ queryKey: ["advisory", advisory.id] });
  });

  const close = () => {
    onClose();
    setTimeout(() => { setBroadcastId(null); setFailed(false); setChannels(ALL); }, 250);
  };
  const toggle = (c: Channel) => setChannels((cs) => (cs.includes(c) ? cs.filter((x) => x !== c) : [...cs, c]));

  return (
    <Dialog open={open} onClose={close} wide title={broadcastId ? "Live delivery" : "Broadcast advisory"}>
      {broadcastId === null ? (
        <div>
          <p className="text-sm text-muted">
            <span className="font-medium text-fg">{advisory.title_en}</span> · {advisory.district} ·{" "}
            {compact(advisory.farmers_targeted)} registered {advisory.crop} farmers
          </p>
          <p className="mt-4 mb-2 text-[13px] font-medium">Channels</p>
          <div className="grid gap-2 sm:grid-cols-2">
            {ALL.map((c) => {
              const m = CHANNEL_META[c];
              const Icon = m.icon;
              const on = channels.includes(c);
              const prev = advisory.channel_preview[c];
              return (
                <button key={c} onClick={() => toggle(c)} aria-pressed={on}
                  className={cx("rounded-xl border p-3 text-left transition-colors",
                    on ? "border-accent-600 bg-accent-50/60 dark:bg-accent-500/10" : "border-line hover:bg-subtle")}>
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <Icon className="h-4 w-4" /> {m.label}
                    <span className={cx("ml-auto h-4 w-4 rounded-full border", on ? "border-accent-600 bg-accent-600" : "border-line")} />
                  </div>
                  <p className="mt-1.5 line-clamp-2 text-[12px] text-muted">{prev.en}</p>
                  <p className="mt-1 text-[11px] text-faint">
                    {prev.chars_en} chars EN · {prev.chars_ta} TA
                    {prev.segments_ta ? ` · Tamil SMS = ${prev.segments_ta} parts` : ""}
                  </p>
                </button>
              );
            })}
          </div>
          {failed && <p className="mt-3 text-[13px] text-red-600 dark:text-red-400">Couldn't start the broadcast. Please try again.</p>}
          <div className="mt-5 flex justify-end gap-2">
            <Button onClick={close}>Cancel</Button>
            <Button variant="primary" disabled={!channels.length || start.isPending} onClick={() => start.mutate()}>
              <Send className="h-4 w-4" /> {start.isPending ? "Starting…" : `Send on ${channels.length} channel${channels.length > 1 ? "s" : ""}`}
            </Button>
          </div>
        </div>
      ) : (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
          <LiveDelivery status={status.data} />
          <div className="mt-5 flex justify-end gap-2">
            <Link to={`/app/delivery?broadcast=${broadcastId}`} onClick={close}
              className="inline-flex h-10 items-center gap-1.5 rounded-xl border border-line px-4 text-sm font-medium hover:bg-subtle">
              <Radio className="h-4 w-4" /> Open delivery monitor
            </Link>
            <Button variant="primary" onClick={close}>Done</Button>
          </div>
        </motion.div>
      )}
    </Dialog>
  );
}
