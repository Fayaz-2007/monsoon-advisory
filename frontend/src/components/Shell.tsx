import { AnimatePresence, motion } from "framer-motion";
import {
  Activity, BellRing, Bot, CalendarDays, ChevronsLeft, ChevronsRight, FlaskConical, LayoutDashboard,
  Menu, Moon, Pause, Play, Radio, Smartphone, Sun, X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, Link } from "react-router-dom";
import { useIsFetching, useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAppState } from "../lib/appState";
import { addDays, longDate, titleCase } from "../lib/format";
import { useTheme } from "../lib/theme";
import { Logo } from "./Logo";
import { cx } from "./ui";

const NAV = [
  { to: "/app/overview", label: "Overview", icon: LayoutDashboard },
  { to: "/app/advisories", label: "Advisory queue", icon: BellRing },
  { to: "/app/delivery", label: "Delivery monitor", icon: Radio },
  { to: "/app/ask", label: "Ask AgriVarsha", icon: Bot },
  { to: "/app/health", label: "System health", icon: Activity },
];

export function Shell() {
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("av-sidebar") === "1");
  const [mobileOpen, setMobileOpen] = useState(false);
  const loc = useLocation();
  useEffect(() => setMobileOpen(false), [loc.pathname]);
  useEffect(() => {
    try { localStorage.setItem("av-sidebar", collapsed ? "1" : "0"); } catch { /* ignore */ }
  }, [collapsed]);

  return (
    <div className="flex h-full">
      {/* desktop sidebar */}
      <motion.aside animate={{ width: collapsed ? 68 : 248 }} transition={{ duration: 0.2, ease: "easeOut" }}
        className="hidden shrink-0 flex-col border-r border-line bg-subtle/60 md:flex">
        <SidebarBody collapsed={collapsed} />
        <button onClick={() => setCollapsed((c) => !c)}
          className="m-3 flex h-9 items-center justify-center gap-2 rounded-xl text-sm text-muted hover:bg-subtle hover:text-fg"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}>
          {collapsed ? <ChevronsRight className="h-4 w-4" /> : <><ChevronsLeft className="h-4 w-4" /> Collapse</>}
        </button>
      </motion.aside>

      {/* mobile drawer */}
      <AnimatePresence>
        {mobileOpen && (
          <>
            <motion.div className="fixed inset-0 z-[1100] bg-black/30 md:hidden" initial={{ opacity: 0 }}
              animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setMobileOpen(false)} />
            <motion.aside className="fixed inset-y-0 left-0 z-[1101] flex w-64 flex-col border-r border-line bg-bg md:hidden"
              initial={{ x: -280 }} animate={{ x: 0 }} exit={{ x: -280 }} transition={{ duration: 0.2 }}>
              <button className="absolute right-3 top-4 rounded-lg p-1.5 text-muted hover:bg-subtle"
                onClick={() => setMobileOpen(false)} aria-label="Close menu"><X className="h-4 w-4" /></button>
              <SidebarBody collapsed={false} />
            </motion.aside>
          </>
        )}
      </AnimatePresence>

      <div className="flex min-w-0 flex-1 flex-col">
        <Header onMenu={() => setMobileOpen(true)} />
        <main className="min-h-0 flex-1 overflow-y-auto">
          <AnimatePresence mode="wait">
            <motion.div key={loc.pathname} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}>
              <Outlet />
            </motion.div>
          </AnimatePresence>
        </main>
      </div>
    </div>
  );
}

function SidebarBody({ collapsed }: { collapsed: boolean }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Link to="/" className="flex h-16 items-center gap-2.5 px-4">
        <Logo />
        {!collapsed && <span className="text-[15px] font-semibold tracking-tight">AgriVarsha</span>}
      </Link>
      <nav className="flex flex-col gap-0.5 px-3">
        {NAV.map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to} title={collapsed ? label : undefined}
            className={({ isActive }) => cx(
              "flex h-9 items-center gap-3 rounded-xl px-2.5 text-sm transition-colors",
              isActive ? "bg-surface font-medium text-fg ring-1 ring-line" : "text-muted hover:bg-surface hover:text-fg",
            )}>
            <Icon className="h-4 w-4 shrink-0" />
            {!collapsed && <span className="truncate">{label}</span>}
          </NavLink>
        ))}
        <div className="my-3 border-t border-line" />
        <NavLink to="/farmer" title={collapsed ? "Farmer app" : undefined}
          className="flex h-9 items-center gap-3 rounded-xl px-2.5 text-sm text-muted hover:bg-surface hover:text-fg">
          <Smartphone className="h-4 w-4 shrink-0" />
          {!collapsed && <span>Farmer app</span>}
        </NavLink>
      </nav>
      <div className="mt-auto px-4 pb-2">
        {!collapsed && (
          <p className="text-[11px] leading-relaxed text-faint">
            Press <kbd className="rounded border border-line bg-surface px-1 font-sans">D</kbd> for demo controls
          </p>
        )}
      </div>
    </div>
  );
}

const SEASON_END = (d: string) => `${d.slice(0, 4)}-12-31`;

function Header({ onMenu }: { onMenu: () => void }) {
  const { date, setDate, effectiveDate, health, refreshAll } = useAppState();
  const [theme, toggleTheme] = useTheme();
  const [playing, setPlaying] = useState(false);
  const fetching = useIsFetching();
  const source = useQuery({ queryKey: ["source"], queryFn: api.sourceInfo });
  const switchSource = useMutation({
    mutationFn: (s: "mock" | "real") => api.setSource(s, date),
    onSuccess: () => refreshAll(),
  });

  // ▶ Play season: step the date forward once the previous date has finished loading.
  useEffect(() => {
    if (!playing || !effectiveDate || fetching > 0) return;
    const next = addDays(effectiveDate, 3);
    if (next > SEASON_END(effectiveDate)) {
      setPlaying(false);
      return;
    }
    const t = setTimeout(() => setDate(next), 900);
    return () => clearTimeout(t);
  }, [playing, effectiveDate, fetching, setDate]);

  const current = source.data?.source ?? health?.forecast_source;
  const scenario = health?.scenario;

  return (
    <header className="sticky top-0 z-[1000] flex h-16 shrink-0 items-center gap-2 border-b border-line bg-bg/85 px-4 backdrop-blur sm:px-6">
      <button onClick={onMenu} className="rounded-lg p-2 text-muted hover:bg-subtle md:hidden" aria-label="Open menu">
        <Menu className="h-4 w-4" />
      </button>

      <div className="flex items-center gap-1.5">
        <label className="relative flex h-9 items-center gap-2 rounded-xl border border-line bg-surface px-3 text-sm hover:bg-subtle">
          <CalendarDays className="h-4 w-4 text-muted" />
          <span className="tabular-nums">{effectiveDate ? longDate(effectiveDate) : "…"}</span>
          <input type="date" aria-label="Issue date" value={effectiveDate ?? ""}
            onChange={(e) => e.target.value && setDate(e.target.value)}
            className="absolute inset-0 cursor-pointer opacity-0" />
        </label>
        <button onClick={() => setPlaying((p) => !p)} title="Play the season: advance the date 3 days at a time"
          className={cx("flex h-9 items-center gap-1.5 rounded-xl border px-3 text-sm transition-colors",
            playing ? "border-accent-700 bg-accent-800 text-white" : "border-line bg-surface hover:bg-subtle")}>
          {playing ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
          <span className="hidden sm:inline">{playing ? "Pause" : "Play season"}</span>
        </button>
        {date && (
          <button onClick={() => { setPlaying(false); setDate(null); }}
            className="hidden h-9 rounded-xl px-2.5 text-[13px] text-muted hover:bg-subtle hover:text-fg lg:block">
            Today
          </button>
        )}
      </div>

      <div className="ml-auto flex items-center gap-2">
        {scenario && current === "mock" && (
          <span className="hidden items-center gap-1.5 rounded-full bg-amber-50 px-2.5 py-1 text-[12px] font-medium text-amber-800 ring-1 ring-amber-200 lg:inline-flex dark:bg-amber-500/10 dark:text-amber-300 dark:ring-amber-500/30">
            <FlaskConical className="h-3.5 w-3.5" /> Scenario: {titleCase(scenario)}
          </span>
        )}
        <div role="radiogroup" aria-label="Forecast source"
          className="flex h-9 items-center rounded-xl border border-line bg-subtle p-0.5 text-[13px]">
          {(["mock", "real"] as const).map((s) => (
            <button key={s} role="radio" aria-checked={current === s} disabled={switchSource.isPending}
              onClick={() => current !== s && switchSource.mutate(s)}
              className={cx("relative h-full rounded-[10px] px-3 font-medium transition-colors",
                current === s ? "text-fg" : "text-muted hover:text-fg")}>
              {current === s && (
                <motion.span layoutId="source-pill" className="absolute inset-0 rounded-[10px] bg-surface shadow-sm ring-1 ring-line"
                  transition={{ duration: 0.2 }} />
              )}
              <span className="relative">{s === "mock" ? "Mock" : "Real model"}</span>
            </button>
          ))}
        </div>
        <button onClick={toggleTheme} className="rounded-xl p-2.5 text-muted hover:bg-subtle hover:text-fg"
          aria-label="Toggle dark mode">
          {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </button>
      </div>
    </header>
  );
}
