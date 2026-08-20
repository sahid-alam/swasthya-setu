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
      // fonts are bundled assets, so the shell renders with no network (Iron Rule 4)
      workbox: { globPatterns: ["**/*.{js,css,html,woff2,svg,png}"] },
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
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
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
