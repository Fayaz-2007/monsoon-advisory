import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Health } from "../api/types";

/**
 * Global demo state: the selected issue date (null = backend default, i.e. the scenario's
 * demo date or today) and helpers to refresh everything after a switch.
 */
interface AppState {
  date: string | null;
  setDate: (d: string | null) => void;
  health: Health | undefined;
  /** The date actually in effect: explicit selection, else the backend's default. */
  effectiveDate: string | undefined;
  refreshAll: () => Promise<void>;
}

const Ctx = createContext<AppState | null>(null);

export function AppStateProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [date, setDateRaw] = useState<string | null>(() => {
    const d = new URLSearchParams(location.search).get("date");
    return d && /^\d{4}-\d{2}-\d{2}$/.test(d) ? d : null;
  });
  const health = useQuery({ queryKey: ["health"], queryFn: () => api.health(), refetchInterval: 15000 });

  const setDate = useCallback((d: string | null) => setDateRaw(d), []);
  const refreshAll = useCallback(async () => {
    await qc.invalidateQueries();
  }, [qc]);

  // Keep ?date= in the URL so a view can be shared / reloaded.
  useEffect(() => {
    const url = new URL(location.href);
    if (date) url.searchParams.set("date", date);
    else url.searchParams.delete("date");
    history.replaceState(history.state, "", url);
  }, [date]);

  const value = useMemo<AppState>(() => ({
    date, setDate, health: health.data, refreshAll,
    effectiveDate: date ?? health.data?.default_date,
  }), [date, setDate, health.data, refreshAll]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAppState(): AppState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAppState outside provider");
  return v;
}
