import { useSyncExternalStore } from "react";

export type Theme = "light" | "dark";

// One source of truth: the `dark` class on <html> (set before first paint in index.html).
const listeners = new Set<() => void>();
const read = (): Theme => (document.documentElement.classList.contains("dark") ? "dark" : "light");

export function setTheme(theme: Theme) {
  document.documentElement.classList.toggle("dark", theme === "dark");
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", theme === "dark" ? "#0f0f10" : "#14532d");
  try {
    localStorage.setItem("av-theme", theme);
  } catch { /* private mode */ }
  listeners.forEach((l) => l());
}

export function useTheme(): [Theme, () => void] {
  const theme = useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    read,
  );
  return [theme, () => setTheme(theme === "dark" ? "light" : "dark")];
}
