import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { VitePWA } from "vite-plugin-pwa";

// API calls go to /api and are proxied to the FastAPI backend in dev.
const API_TARGET = process.env.VITE_API_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["favicon.svg", "icon-192.png", "icon-512.png"],
      manifest: {
        name: "AgriVarsha — Monsoon advisories",
        short_name: "AgriVarsha",
        description: "Monsoon hazard forecasts and crop advisories for Tamil Nadu",
        theme_color: "#14532d",
        background_color: "#ffffff",
        display: "standalone",
        start_url: "/",
        icons: [
          { src: "icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "icon-512.png", sizes: "512x512", type: "image/png" },
          { src: "icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
      },
      workbox: {
        navigateFallbackDenylist: [/^\/api/],
        // Never cache API responses: every screen shows live backend data.
        runtimeCaching: [{ urlPattern: /\/api\//, handler: "NetworkOnly" }],
      },
    }),
  ],
  server: {
    port: 5173,
    proxy: { "/api": { target: API_TARGET, changeOrigin: true } },
  },
  preview: { port: 4173, proxy: { "/api": { target: API_TARGET, changeOrigin: true } } },
});
