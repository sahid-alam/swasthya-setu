import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: "autoUpdate",
      // fonts are bundled assets, so the shell renders with no network (Iron Rule 4).
      // The Vapi SDK is the one thing deliberately NOT precached: 300 kB of voice
      // agent on a patient's budget Android, for a button that only exists in the
      // staff dashboard and only works online anyway.
      workbox: {
        globPatterns: ["**/*.{js,css,html,woff2,svg,png}"],
        globIgnores: ["**/vapi-*.js"],
      },
      manifest: {
        name: "Swasthya-Setu",
        short_name: "Swasthya",
        theme_color: "#0a0e14",
        background_color: "#f5f7fb",
        display: "standalone",
        start_url: "/",
        icons: [
          {
            src: "/icon.svg",
            sizes: "any",
            type: "image/svg+xml",
            purpose: "any",
          },
        ],
      },
    }),
  ],
  // The one .env at the repo root serves backend and frontend alike; without this
  // Vite looks in frontend/ and silently sees no VITE_* vars at all.
  envDir: "..",
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
  build: {
    rollupOptions: {
      // Named so the service worker can recognise it above; a hashed anonymous chunk
      // could not be excluded by pattern.
      output: {
        manualChunks: (id: string) =>
          id.includes("@vapi-ai") || id.includes("@daily-co")
            ? "vapi"
            : undefined,
      },
    },
  },
  test: {
    environment: "jsdom",
    // jsdom disables localStorage on an opaque origin, and the offline outbox lives
    // in localStorage — without a real URL those tests see `undefined`.
    environmentOptions: { jsdom: { url: "http://localhost:5173" } },
    setupFiles: ["./src/test-setup.ts"],
    css: false,
  },
});
