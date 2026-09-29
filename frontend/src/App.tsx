import { MotionConfig } from "framer-motion";
import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppStateProvider } from "./lib/appState";
import { WarmUpGate } from "./components/WarmUpGate";
import { Shell } from "./components/Shell";
import { DemoPanel } from "./components/DemoPanel";
import { Skeleton } from "./components/ui";
import { Landing } from "./pages/Landing";

const Overview = lazy(() => import("./pages/Overview"));
const District = lazy(() => import("./pages/District"));
const Advisories = lazy(() => import("./pages/Advisories"));
const Delivery = lazy(() => import("./pages/Delivery"));
const Ask = lazy(() => import("./pages/Ask"));
const Health = lazy(() => import("./pages/Health"));
const Farmer = lazy(() => import("./pages/Farmer"));

function PageFallback() {
  return (
    <div className="mx-auto max-w-7xl space-y-4 px-6 py-8">
      <Skeleton className="h-7 w-56" />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-28" />)}
      </div>
      <Skeleton className="h-96" />
    </div>
  );
}

export function App() {
  return (
    <MotionConfig reducedMotion="user">
      <WarmUpGate>
        <BrowserRouter>
          <AppStateProvider>
            <Suspense fallback={<PageFallback />}>
              <Routes>
                <Route path="/" element={<Landing />} />
                <Route path="/farmer" element={<Farmer />} />
                <Route path="/app" element={<Shell />}>
                  <Route index element={<Navigate to="overview" replace />} />
                  <Route path="overview" element={<Overview />} />
                  <Route path="district/:slug" element={<District />} />
                  <Route path="advisories" element={<Advisories />} />
                  <Route path="delivery" element={<Delivery />} />
                  <Route path="ask" element={<Ask />} />
                  <Route path="health" element={<Health />} />
                </Route>
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </Suspense>
            <DemoPanel />
          </AppStateProvider>
        </BrowserRouter>
      </WarmUpGate>
    </MotionConfig>
  );
}
