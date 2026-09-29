# Segment 6 — Frontend (AgriVarsha)

React + Vite + TypeScript + Tailwind + Framer Motion + TanStack Query + Leaflet + Recharts,
installable as a PWA. Uses only the endpoints in [`docs/contracts/api.md`](../docs/contracts/api.md).

```bash
npm install
npm run dev      # http://localhost:5173 (proxies /api to http://127.0.0.1:8000)
npm run build    # production build + service worker in dist/
```

`VITE_API_TARGET` changes the proxied backend; `VITE_API_BASE` points a built app at another
API origin. Routes: `/` landing, `/app/overview`, `/app/district/:slug`, `/app/advisories`,
`/app/delivery`, `/app/ask`, `/app/health`, `/farmer`. Press **D** for demo controls.
