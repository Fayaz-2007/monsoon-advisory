import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../api/client";
import { Logo } from "./Logo";

/**
 * The backend can take ~90 s on a cold start. Poll /api/health quietly and show a calm
 * full-screen warm-up state until it answers, then fade into the app.
 */
export function WarmUpGate({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const started = useRef(Date.now());

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), 4000);
      try {
        await api.health(ctrl.signal);
        if (alive) setReady(true);
        return;
      } catch {
        /* not up yet */
      } finally {
        clearTimeout(t);
      }
      if (alive) {
        setElapsed(Math.round((Date.now() - started.current) / 1000));
        timer = setTimeout(tick, 2000);
      }
    };
    tick();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, []);

  const hint =
    elapsed < 20 ? "Connecting to the forecast service…"
      : elapsed < 60 ? "Loading 35 years of rainfall and the district maps…"
        : elapsed < 120 ? "Almost there. The first start after a reboot takes about a minute and a half."
          : "Still starting. Make sure the backend is running (run_demo.bat starts everything).";

  return (
    <AnimatePresence mode="wait">
      {ready ? (
        <motion.div key="app" className="h-full" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.3 }}>
          {children}
        </motion.div>
      ) : (
        <motion.div key="warm" exit={{ opacity: 0 }} transition={{ duration: 0.3 }}
          className="fixed inset-0 z-[2000] flex flex-col items-center justify-center bg-bg px-6 text-center">
          <Logo className="h-12 w-12" />
          <h1 className="mt-6 text-xl font-semibold tracking-tight">Warming up AgriVarsha…</h1>
          <p className="mt-2 max-w-sm text-sm text-muted" aria-live="polite">{hint}</p>
          <div className="mt-8 h-1.5 w-64 overflow-hidden rounded-full bg-subtle">
            <div className="skeleton h-full w-full rounded-full" />
          </div>
          {elapsed > 0 && <p className="mt-3 text-xs text-faint tabular-nums">{elapsed}s</p>}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
