import { motion } from "framer-motion";
import { ChevronLeft, Grid3x3, Mic, PhoneOff, Video, Volume2 } from "lucide-react";
import type { ReactNode } from "react";
import { Ticks } from "./LiveDelivery";
import { cx } from "./ui";

/** A generic phone frame. `dark` for the call screen. */
export function PhoneFrame({ children, className, dark }: { children: ReactNode; className?: string; dark?: boolean }) {
  return (
    <div className={cx("mx-auto w-[260px] rounded-[2.2rem] border border-line bg-zinc-900 p-2 shadow-sm dark:bg-zinc-800", className)}>
      <div className={cx("relative flex h-[500px] flex-col overflow-hidden rounded-[1.7rem]", dark ? "bg-zinc-950 text-white" : "bg-white text-zinc-900")}>
        <div className="absolute left-1/2 top-2 z-10 h-4 w-20 -translate-x-1/2 rounded-full bg-black" />
        <div className="flex h-8 shrink-0 items-end justify-between px-5 pb-0.5 text-[10px] font-semibold opacity-80">
          <span>9:41</span><span>●●● 4G</span>
        </div>
        {children}
      </div>
    </div>
  );
}

function Bubble({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}
      className={cx("max-w-[88%] whitespace-pre-line rounded-2xl px-3 py-2 text-[12px] leading-snug", className)}>
      {children}
    </motion.div>
  );
}

export function SmsPhone({ text, segments, lang }: { text: string; segments?: number; lang: string }) {
  return (
    <PhoneFrame>
      <div className="flex items-center gap-2 border-b border-zinc-200 px-3 py-2">
        <ChevronLeft className="h-4 w-4 text-sky-600" />
        <div className="flex h-7 w-7 items-center justify-center rounded-full bg-zinc-300 text-[10px] font-semibold text-zinc-700">AV</div>
        <div className="text-[12px] font-semibold">AGRVRS</div>
      </div>
      <div className="flex-1 space-y-2 overflow-y-auto bg-white p-3">
        <p className="text-center text-[10px] text-zinc-400">Text Message · Today</p>
        <Bubble className="bg-zinc-100 text-zinc-900"><span lang={lang}>{text}</span></Bubble>
        <p className="pl-1 text-[10px] text-zinc-400">
          {text.length} chars{segments ? ` · ${segments} SMS part${segments > 1 ? "s" : ""}` : ""}
        </p>
      </div>
    </PhoneFrame>
  );
}

/** Renders WhatsApp-style *bold* and _italic_ markup. */
function waFormat(s: string): ReactNode[] {
  return s.split(/(\*[^*\n]+\*|_[^_\n]+_)/g).map((part, i) =>
    part.startsWith("*") && part.endsWith("*") ? <b key={i}>{part.slice(1, -1)}</b>
      : part.startsWith("_") && part.endsWith("_") ? <i key={i} className="opacity-70">{part.slice(1, -1)}</i>
        : <span key={i}>{part}</span>);
}

export function WhatsAppPhone({ text, stage, lang }: { text: string; stage: number; lang: string }) {
  return (
    <PhoneFrame>
      <div className="flex items-center gap-2 bg-[#075e54] px-3 py-2 text-white">
        <ChevronLeft className="h-4 w-4" />
        <div className="flex h-7 w-7 items-center justify-center rounded-full bg-accent-700 text-[10px] font-semibold">AV</div>
        <div className="min-w-0">
          <div className="truncate text-[12px] font-semibold">AgriVarsha ✓</div>
          <div className="text-[10px] opacity-80">Business account</div>
        </div>
        <Video className="ml-auto h-4 w-4 opacity-80" />
      </div>
      <div className="flex-1 space-y-2 overflow-y-auto bg-[#ece5dd] p-3">
        <Bubble className="bg-white text-zinc-900 shadow-sm">
          <span lang={lang}>{waFormat(text)}</span>
          <span className="mt-1 flex items-center justify-end gap-0.5 text-[9px] text-zinc-400">9:41 <Ticks stage={stage} /></span>
        </Bubble>
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.4 }}
          className="flex gap-1.5 pl-1">
          {["👍", "👎"].map((e) => (
            <span key={e} className="rounded-full bg-white px-2.5 py-1 text-[12px] shadow-sm">{e}</span>
          ))}
        </motion.div>
      </div>
    </PhoneFrame>
  );
}

export function IvrPhone({ script, lang, stage }: { script: string; lang: string; stage: number }) {
  const answered = stage >= 2;
  return (
    <PhoneFrame dark>
      <div className="flex flex-1 flex-col items-center px-4 pt-6 text-center">
        <p className="text-[11px] opacity-60">{answered ? "AgriVarsha voice advisory" : "Incoming call…"}</p>
        <div className="relative mt-4">
          {!answered && (
            <motion.span className="absolute inset-0 rounded-full bg-accent-500/30"
              animate={{ scale: [1, 1.35], opacity: [0.6, 0] }} transition={{ duration: 1.6, repeat: Infinity }} />
          )}
          <div className="relative flex h-16 w-16 items-center justify-center rounded-full bg-accent-700 text-lg font-semibold">AV</div>
        </div>
        <p className="mt-3 text-[15px] font-semibold">1800-AGRI-VAR</p>
        <p className="text-[11px] opacity-60">{answered ? "00:" + String(Math.min(59, 12 + stage * 9)).padStart(2, "0") : "Tamil Nadu Agri Dept"}</p>
        <div className="mt-4 max-h-[190px] overflow-y-auto rounded-xl bg-white/5 p-3 text-left text-[11px] leading-relaxed opacity-90" lang={lang}>
          <p className="mb-1 flex items-center gap-1 text-[10px] uppercase tracking-wide opacity-60"><Volume2 className="h-3 w-3" /> Spoken script</p>
          {script}
        </div>
        <div className="mt-auto mb-6 grid w-full grid-cols-3 gap-3 text-[10px] opacity-80">
          {[{ i: Mic, t: "Mute" }, { i: Grid3x3, t: "1 · 2 · 3" }, { i: Volume2, t: "Speaker" }].map(({ i: I, t }) => (
            <div key={t} className="flex flex-col items-center gap-1">
              <span className="flex h-10 w-10 items-center justify-center rounded-full bg-white/10"><I className="h-4 w-4" /></span>{t}
            </div>
          ))}
          <div className="col-span-3 mt-2 flex justify-center">
            <span className="flex h-11 w-11 items-center justify-center rounded-full bg-red-500"><PhoneOff className="h-4 w-4" /></span>
          </div>
        </div>
      </div>
    </PhoneFrame>
  );
}
