import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const API_URL = process.env.DEBATE_API_URL ?? "http://127.0.0.1:8001";

// Dev: Vite serwuje klienta i sam proxuje /api oraz /ws do debate-api.
// Prod: `vite build` do dist/client, a serwuje go Express (server/index.ts).
export default defineConfig({
  root: "client",
  plugins: [react()],
  build: { outDir: "../dist/client", emptyOutDir: true },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: API_URL, changeOrigin: true },
      "/ws": { target: API_URL, ws: true, changeOrigin: true },
    },
  },
});
