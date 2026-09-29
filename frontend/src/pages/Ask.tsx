import { AnimatePresence, motion } from "framer-motion";
import { ArrowUp, Bot, Link2, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { streamChat } from "../api/client";
import { Logo } from "../components/Logo";
import { cx } from "../components/ui";
import { useAppState } from "../lib/appState";

interface Msg {
  role: "user" | "assistant";
  text: string;
  meta?: { mode: string; district: string | null; sources: string[] };
  streaming?: boolean;
  failed?: boolean;
}

const SUGGESTIONS = [
  "Should farmers in Madurai sow groundnut this week?",
  "Which districts have alerts right now?",
  "Will there be heavy rain in Chennai next week?",
  "Is a dry spell coming in Salem?",
  "What advisories are drafted for Thanjavur?",
];

export default function Ask() {
  const { date } = useAppState();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const abort = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const busy = msgs.some((m) => m.streaming);

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [msgs]);
  useEffect(() => () => abort.current?.abort(), []);

  const update = (fn: (m: Msg) => Msg) => setMsgs((ms) => ms.map((m, i) => (i === ms.length - 1 ? fn(m) : m)));

  const send = async (text: string) => {
    const q = text.trim();
    if (!q || busy) return;
    setInput("");
    setMsgs((ms) => [...ms, { role: "user", text: q }, { role: "assistant", text: "", streaming: true }]);
    const ctrl = new AbortController();
    abort.current = ctrl;
    // Word-by-word reveal: queue incoming tokens and release them at a steady pace.
    const queue: string[] = [];
    let finished = false;
    const pump = setInterval(() => {
      if (queue.length) {
        const piece = queue.splice(0, Math.max(1, Math.floor(queue.length / 20)));
        update((m) => ({ ...m, text: m.text + piece.join("") }));
      } else if (finished) {
        clearInterval(pump);
        update((m) => ({ ...m, streaming: false }));
      }
    }, 24);
    try {
      await streamChat({ message: q, date }, {
        meta: (m) => update((x) => ({ ...x, meta: m })),
        token: (t) => queue.push(...(t.match(/\S+\s*|\s+/g) ?? [t])),
        error: () => queue.push("Sorry, I couldn't answer that just now. Please try again."),
      }, ctrl.signal);
    } catch {
      if (!ctrl.signal.aborted) {
        queue.push("Sorry, I couldn't reach the forecast service. Please try again in a moment.");
        update((m) => ({ ...m, failed: true }));
      }
    } finally {
      finished = true;
    }
  };

  const stop = () => {
    abort.current?.abort();
    update((m) => ({ ...m, streaming: false }));
  };

  return (
    <div className="flex h-[calc(100vh-4rem)] flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl px-4 py-8">
          {msgs.length === 0 ? (
            <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="mt-[12vh] text-center">
              <Logo className="mx-auto h-10 w-10" />
              <h1 className="mt-4 text-2xl font-semibold tracking-tight">Ask AgriVarsha</h1>
              <p className="mt-2 text-sm text-muted">Answers use the current forecasts, hazards, advisories and observed rain, and quote their numbers.</p>
              <div className="mx-auto mt-8 grid max-w-2xl gap-2 sm:grid-cols-2">
                {SUGGESTIONS.map((s, i) => (
                  <motion.button key={s} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 * i }}
                    onClick={() => send(s)}
                    className="rounded-2xl border border-line px-4 py-3 text-left text-sm text-muted transition-colors hover:bg-subtle hover:text-fg">
                    {s}
                  </motion.button>
                ))}
              </div>
            </motion.div>
          ) : (
            <div className="space-y-6">
              <AnimatePresence initial={false}>
                {msgs.map((m, i) => (
                  <motion.div key={i} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2 }}
                    className={cx("flex gap-3", m.role === "user" && "justify-end")}>
                    {m.role === "assistant" && (
                      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent-800 text-white"><Bot className="h-4 w-4" /></div>
                    )}
                    <div className={cx("max-w-[85%] text-[15px] leading-relaxed",
                      m.role === "user" ? "rounded-2xl bg-subtle px-4 py-2.5" : "min-w-0 flex-1")}>
                      {m.role === "assistant" && !m.text && m.streaming ? (
                        <span className="inline-flex gap-1 py-2">
                          {[0, 1, 2].map((d) => (
                            <motion.span key={d} className="h-1.5 w-1.5 rounded-full bg-faint"
                              animate={{ opacity: [0.3, 1, 0.3] }} transition={{ duration: 1, repeat: Infinity, delay: d * 0.15 }} />
                          ))}
                        </span>
                      ) : (
                        <p className="whitespace-pre-wrap">{m.text}{m.streaming && <span className="ml-0.5 inline-block h-4 w-1.5 translate-y-0.5 animate-pulse bg-fg/60" />}</p>
                      )}
                      {m.role === "assistant" && m.meta && !m.streaming && (
                        <div className="mt-3 flex flex-wrap items-center gap-1.5 text-[11px] text-faint">
                          <span className="rounded-full bg-subtle px-2 py-0.5">{m.meta.mode === "llm" ? "Claude, grounded in live data" : "Template answer from live data"}</span>
                          {m.meta.sources.slice(0, 3).map((s) => (
                            <span key={s} className="inline-flex items-center gap-1 rounded-full bg-subtle px-2 py-0.5 font-mono"><Link2 className="h-3 w-3" />{s}</span>
                          ))}
                        </div>
                      )}
                    </div>
                  </motion.div>
                ))}
              </AnimatePresence>
              <div ref={bottom} />
            </div>
          )}
        </div>
      </div>

      <div className="shrink-0 px-4 pb-6">
        <form onSubmit={(e) => { e.preventDefault(); send(input); }}
          className="mx-auto flex max-w-3xl items-end gap-2 rounded-3xl border border-line bg-surface p-2 pl-4 shadow-sm focus-within:border-accent-600">
          <textarea value={input} onChange={(e) => setInput(e.target.value)} rows={1} placeholder="Ask about rain, sowing or alerts in any district…"
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }}
            className="max-h-40 min-h-[40px] flex-1 resize-none bg-transparent py-2 text-[15px] outline-none placeholder:text-faint" />
          {busy ? (
            <button type="button" onClick={stop} aria-label="Stop" className="flex h-10 w-10 items-center justify-center rounded-full bg-fg text-bg"><Square className="h-4 w-4" /></button>
          ) : (
            <button type="submit" disabled={!input.trim()} aria-label="Send"
              className="flex h-10 w-10 items-center justify-center rounded-full bg-accent-800 text-white disabled:bg-subtle disabled:text-faint">
              <ArrowUp className="h-4 w-4" />
            </button>
          )}
        </form>
        <p className="mt-2 text-center text-[11px] text-faint">Answers are grounded in the dashboard's data for the selected date. Check critical decisions with your agriculture officer.</p>
      </div>
    </div>
  );
}
