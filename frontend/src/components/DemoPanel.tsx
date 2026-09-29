import { AnimatePresence, motion } from "framer-motion";
import { CalendarClock, FlaskConical, RotateCcw, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAppState } from "../lib/appState";
import { longDate } from "../lib/format";
import { Button, cx } from "./ui";

/** Floating demo controls, toggled with the "D" key. */
export function DemoPanel() {
  const [open, setOpen] = useState(false);
  const { setDate, effectiveDate, health, refreshAll } = useAppState();
  const [jump, setJump] = useState("");
  const [purge, setPurge] = useState(false);
  const scenarios = useQuery({ queryKey: ["scenarios"], queryFn: api.scenarios, enabled: open });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (el.closest("input, textarea, select, [contenteditable=true]") || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "d" || e.key === "D") setOpen((o) => !o);
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const activate = useMutation({
    mutationFn: (name: string) => api.activateScenario(name),
    onSuccess: async () => {
      setDate(null); // follow the scenario's default date
      await refreshAll();
    },
  });
  const reset = useMutation({
    mutationFn: () => api.reset(purge),
    onSuccess: async () => {
      setDate(null);
      setPurge(false);
      await refreshAll();
    },
  });
  const active = health?.scenario ?? scenarios.data?.active;

  return (
    <>
      <AnimatePresence>
        {open && (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 12 }}
            transition={{ duration: 0.2 }}
            className="fixed bottom-4 right-4 z-[1600] w-[340px] max-w-[calc(100vw-2rem)] rounded-2xl border border-line bg-surface shadow-xl">
            <div className="flex items-center justify-between border-b border-line px-4 py-3">
              <p className="flex items-center gap-2 text-sm font-semibold"><FlaskConical className="h-4 w-4 text-accent-700" /> Demo controls</p>
              <button onClick={() => setOpen(false)} className="rounded-lg p-1 text-muted hover:bg-subtle" aria-label="Close demo controls"><X className="h-4 w-4" /></button>
            </div>
            <div className="max-h-[70vh] space-y-4 overflow-y-auto p-4">
              <div>
                <p className="mb-2 text-[12px] font-medium uppercase tracking-wide text-faint">Scenarios (mock forecasts)</p>
                <div className="space-y-1.5">
                  {scenarios.data?.scenarios.map((s) => (
                    <button key={s.name} onClick={() => activate.mutate(s.name)} disabled={activate.isPending}
                      className={cx("w-full rounded-xl border px-3 py-2 text-left transition-colors disabled:opacity-60",
                        active === s.name ? "border-accent-600 bg-accent-50/60 dark:bg-accent-500/10" : "border-line hover:bg-subtle")}>
                      <div className="flex items-center justify-between text-sm font-medium">
                        {s.title}
                        <span className="text-[11px] font-normal text-muted">{longDate(s.demo_date)}</span>
                      </div>
                      <p className="mt-0.5 text-[12px] leading-snug text-muted">{s.description}</p>
                      {activate.isPending && activate.variables === s.name && <p className="mt-1 text-[11px] text-accent-700">Computing hazards and advisories…</p>}
                    </button>
                  )) ?? <p className="text-[13px] text-faint">Loading…</p>}
                </div>
              </div>

              <div>
                <p className="mb-2 text-[12px] font-medium uppercase tracking-wide text-faint">Date</p>
                <p className="mb-2 text-[13px] text-muted">Showing <b className="text-fg">{longDate(effectiveDate)}</b></p>
                <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (jump) setDate(jump); }}>
                  <input type="date" value={jump} onChange={(e) => setJump(e.target.value)}
                    className="h-9 flex-1 rounded-xl border border-line bg-surface px-2 text-sm" />
                  <Button size="sm" type="submit" disabled={!jump}><CalendarClock className="h-3.5 w-3.5" /> Jump</Button>
                </form>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  <Button size="sm" variant="ghost" onClick={() => setDate(null)}>Default</Button>
                  <Button size="sm" variant="ghost" onClick={() => setDate(`${(effectiveDate ?? "2026").slice(0, 4)}-10-20`)}>NE monsoon (20 Oct)</Button>
                  <Button size="sm" variant="ghost" onClick={() => setDate(`${(effectiveDate ?? "2026").slice(0, 4)}-08-14`)}>Mid-season (14 Aug)</Button>
                </div>
              </div>

              <div className="border-t border-line pt-4">
                <label className="mb-2 flex items-center gap-2 text-[13px] text-muted">
                  <input type="checkbox" checked={purge} onChange={(e) => setPurge(e.target.checked)} className="h-4 w-4 accent-green-700" />
                  Also clear hazards, advisories, broadcasts and feedback
                </label>
                <Button className="w-full" variant={purge ? "danger" : "secondary"} onClick={() => reset.mutate()} disabled={reset.isPending}>
                  <RotateCcw className="h-4 w-4" /> {reset.isPending ? "Resetting…" : purge ? "Reset and clear demo data" : "Reset scenario & source"}
                </Button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
      {!open && (
        <button onClick={() => setOpen(true)} title="Demo controls (D)"
          className="fixed bottom-4 right-4 z-[1600] flex h-10 w-10 items-center justify-center rounded-full border border-line bg-surface text-muted shadow-sm hover:text-fg">
          <FlaskConical className="h-4 w-4" />
        </button>
      )}
    </>
  );
}
