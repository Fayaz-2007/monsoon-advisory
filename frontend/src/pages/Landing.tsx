import { motion } from "framer-motion";
import { ArrowRight, Moon, Smartphone, Sun } from "lucide-react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { Logo } from "../components/Logo";
import { CountUp, fadeUp, stagger } from "../components/ui";
import { useTheme } from "../lib/theme";

export function Landing() {
  const [theme, toggle] = useTheme();
  const overview = useQuery({ queryKey: ["overview", null], queryFn: () => api.overview() });
  const o = overview.data;

  return (
    <div className="flex min-h-full flex-col">
      <header className="flex h-16 items-center justify-between px-6">
        <div className="flex items-center gap-2.5">
          <Logo />
          <span className="text-[15px] font-semibold tracking-tight">AgriVarsha</span>
        </div>
        <button onClick={toggle} className="rounded-xl p-2.5 text-muted hover:bg-subtle" aria-label="Toggle dark mode">
          {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </button>
      </header>

      <motion.main initial="hidden" animate="show" variants={stagger}
        className="mx-auto flex w-full max-w-3xl flex-1 flex-col items-center justify-center px-6 pb-20 text-center">
        <motion.span variants={fadeUp}
          className="rounded-full border border-line px-3 py-1 text-[12px] font-medium text-muted">
          Tamil Nadu · 38 districts · NE &amp; SW monsoon
        </motion.span>
        <motion.h1 variants={fadeUp} className="mt-6 text-4xl font-semibold tracking-tight sm:text-5xl">
          Know the monsoon before it <span className="text-accent-700 dark:text-accent-400">fails your crop</span>.
        </motion.h1>
        <motion.p variants={fadeUp} className="mt-4 max-w-xl text-base text-muted">
          AgriVarsha turns 4-week rainfall forecasts and real IMD observations into hazard alerts and
          crop advice in Tamil and English, reviewed by officers and delivered by SMS, WhatsApp and voice.
        </motion.p>
        <motion.div variants={fadeUp} className="mt-8 flex flex-wrap justify-center gap-3">
          <Link to="/app/overview"
            className="inline-flex h-11 items-center gap-2 rounded-xl bg-accent-800 px-5 text-sm font-medium text-white hover:bg-accent-900">
            Officer Dashboard <ArrowRight className="h-4 w-4" />
          </Link>
          <Link to="/farmer"
            className="inline-flex h-11 items-center gap-2 rounded-xl border border-line px-5 text-sm font-medium hover:bg-subtle">
            <Smartphone className="h-4 w-4" /> Farmer App
          </Link>
        </motion.div>

        <motion.dl variants={fadeUp} className="mt-14 grid w-full grid-cols-3 divide-x divide-line rounded-2xl border border-line">
          {[
            { label: "Districts on alert", value: o?.districts.with_alerts },
            { label: "Advisories to review", value: o?.advisories.pending_review },
            { label: "Farmers registered", value: o?.farmers.registered_total, note: "mock" },
          ].map((s) => (
            <div key={s.label} className="px-4 py-4">
              <dt className="text-[12px] text-muted">{s.label}{s.note && <span className="text-faint"> · {s.note}</span>}</dt>
              <dd className="mt-1 text-2xl font-semibold tabular-nums">
                {s.value === undefined ? <span className="text-faint">—</span> : <CountUp value={s.value} />}
              </dd>
            </div>
          ))}
        </motion.dl>
      </motion.main>
    </div>
  );
}
