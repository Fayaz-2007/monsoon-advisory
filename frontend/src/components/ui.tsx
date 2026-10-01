import { animate, motion, useInView, useReducedMotion, type HTMLMotionProps, type Variants } from "framer-motion";
import clsx from "clsx";
import { RefreshCw, CloudOff } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Severity } from "../api/types";
import { SEVERITY_STYLE } from "../lib/format";

export const cx = clsx;

export const fadeUp: Variants = {
  hidden: { opacity: 0, y: 8 },
  show: { opacity: 1, y: 0, transition: { duration: 0.25, ease: "easeOut" } },
};
export const stagger: Variants = { hidden: {}, show: { transition: { staggerChildren: 0.04 } } };

export function Card({ className, children, ...rest }: HTMLMotionProps<"div">) {
  return (
    <motion.div variants={fadeUp} className={cx("rounded-2xl border border-line bg-surface", className)} {...rest}>
      {children}
    </motion.div>
  );
}

export function CardHeader({ title, subtitle, right, icon }: {
  title: ReactNode; subtitle?: ReactNode; right?: ReactNode; icon?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-3 px-5 pt-4 pb-3">
      <div className="flex min-w-0 items-start gap-2.5">
        {icon && <div className="mt-0.5 text-muted">{icon}</div>}
        <div className="min-w-0">
          <h3 className="text-[15px] font-semibold tracking-tight">{title}</h3>
          {subtitle && <div className="mt-0.5 text-[13px] text-muted">{subtitle}</div>}
        </div>
      </div>
      {right}
    </div>
  );
}

export function Page({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <motion.div initial="hidden" animate="show" variants={stagger}
      className={cx("mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8", className)}>
      {children}
    </motion.div>
  );
}

export function PageTitle({ title, subtitle, right }: { title: ReactNode; subtitle?: ReactNode; right?: ReactNode }) {
  return (
    <motion.div variants={fadeUp} className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <div className="mt-1 text-sm text-muted">{subtitle}</div>}
      </div>
      {right}
    </motion.div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("skeleton", className)} aria-hidden />;
}

export function SkeletonLines({ n = 3 }: { n?: number }) {
  return (
    <div className="space-y-2.5 p-5">
      {Array.from({ length: n }, (_, i) => (
        <Skeleton key={i} className={cx("h-3.5", i === n - 1 ? "w-2/3" : "w-full")} />
      ))}
    </div>
  );
}

export function Button({ variant = "secondary", size = "md", className, children, ...rest }:
  React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "danger"; size?: "sm" | "md" }) {
  return (
    <button
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-xl font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-600",
        size === "sm" ? "h-8 px-3 text-[13px]" : "h-10 px-4 text-sm",
        variant === "primary" && "bg-accent-800 text-white hover:bg-accent-900 dark:bg-accent-700 dark:hover:bg-accent-800",
        variant === "secondary" && "border border-line bg-surface hover:bg-subtle",
        variant === "ghost" && "text-muted hover:bg-subtle hover:text-fg",
        variant === "danger" && "border border-line bg-surface text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-500/10",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}

export function SeverityChip({ severity, className }: { severity: Severity | "none"; className?: string }) {
  const s = SEVERITY_STYLE[severity];
  return (
    <span className={cx("inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset", s.chip, className)}>
      <span className={cx("h-1.5 w-1.5 rounded-full", s.dot)} />
      {s.label}
    </span>
  );
}

export function Chip({ children, className, title }: { children: ReactNode; className?: string; title?: string }) {
  return (
    <span title={title} className={cx("inline-flex items-center gap-1 rounded-full bg-subtle px-2 py-0.5 text-[11px] font-medium text-muted ring-1 ring-inset ring-line", className)}>
      {children}
    </span>
  );
}

/** "Block level · demo data" badge: marks MOCK block-level regions (Madurai blocks). */
export function BlockDemoBadge({ className }: { className?: string }) {
  return (
    <span title="Community Development block — MOCK demo data, not a real forecast"
      className={cx("inline-flex items-center gap-1 rounded-full bg-violet-50 px-2 py-0.5 text-[11px] font-medium text-violet-800 ring-1 ring-inset ring-violet-200 dark:bg-violet-500/10 dark:text-violet-200 dark:ring-violet-500/30", className)}>
      Block level · demo data
    </span>
  );
}

/** "Observed data" badge: marks alerts driven by REAL IMD rainfall. */
export function ObservedBadge({ className }: { className?: string }) {
  return (
    <span title="Detected from real IMD observed rainfall (Segment 1), not from a forecast"
      className={cx("inline-flex items-center gap-1 rounded-full bg-accent-50 px-2 py-0.5 text-[11px] font-medium text-accent-800 ring-1 ring-inset ring-accent-200 dark:bg-accent-500/10 dark:text-accent-400 dark:ring-accent-500/30", className)}>
      <span className="h-1.5 w-1.5 rounded-full bg-accent-600" />
      Observed data
    </span>
  );
}

/** Animated number (count-up). Respects prefers-reduced-motion. */
export function CountUp({ value, format = (n) => Math.round(n).toLocaleString("en-IN"), className }: {
  value: number; format?: (n: number) => string; className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const prev = useRef(0);
  const reduce = useReducedMotion();
  const inView = useInView(ref, { once: true });
  useEffect(() => {
    const el = ref.current;
    if (!el || !inView) return;
    if (reduce) {
      el.textContent = format(value);
      prev.current = value;
      return;
    }
    const controls = animate(prev.current, value, {
      duration: 0.8,
      ease: "easeOut",
      onUpdate: (v) => { el.textContent = format(v); },
    });
    prev.current = value;
    return () => controls.stop();
  }, [value, inView, reduce, format]);
  return <span ref={ref} className={className}>{format(0)}</span>;
}

/** Friendly failure state with retry (never shows raw errors). */
export function RetryState({ onRetry, title = "We couldn't load this just now", className }: {
  onRetry: () => void; title?: string; className?: string;
}) {
  return (
    <div className={cx("flex flex-col items-center justify-center gap-3 px-6 py-10 text-center", className)}>
      <CloudOff className="h-6 w-6 text-faint" />
      <div>
        <p className="text-sm font-medium">{title}</p>
        <p className="mt-1 text-[13px] text-muted">The service may be busy. It usually recovers in a few seconds.</p>
      </div>
      <Button size="sm" onClick={onRetry}><RefreshCw className="h-3.5 w-3.5" /> Try again</Button>
    </div>
  );
}

export function EmptyState({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-10 text-center">
      {icon && <div className="text-faint">{icon}</div>}
      <p className="text-sm font-medium">{title}</p>
      {children && <div className="text-[13px] text-muted">{children}</div>}
    </div>
  );
}

/** Small toast used after mutations. */
export function useToast(): [ReactNode, (msg: string) => void] {
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    if (!msg) return;
    const t = setTimeout(() => setMsg(null), 2800);
    return () => clearTimeout(t);
  }, [msg]);
  const node = msg ? (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
      className="fixed bottom-6 left-1/2 z-[1200] -translate-x-1/2 rounded-xl border border-line bg-surface px-4 py-2.5 text-sm shadow-lg">
      {msg}
    </motion.div>
  ) : null;
  return [node, setMsg];
}

export function Tooltip({ content, children }: { content: ReactNode; children: ReactNode }) {
  return (
    <span className="group relative inline-flex">
      {children}
      <span role="tooltip"
        className="pointer-events-none absolute bottom-full right-0 z-50 mb-2 hidden w-64 rounded-xl border border-line bg-surface p-3 text-left text-xs font-normal leading-relaxed text-muted shadow-lg group-hover:block group-focus-within:block">
        {content}
      </span>
    </span>
  );
}
