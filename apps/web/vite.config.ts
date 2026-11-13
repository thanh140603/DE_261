import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// API_URL points the dev proxy at another server, e.g. a source checkout on :8001.
const env = (globalThis as { process?: { env: Record<string, string | undefined> } }).process?.env ?? {};

export default defineConfig({
  plugins: [react()],
  base: "/",
  build: { outDir: "dist", emptyOutDir: true },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: env.API_URL ?? "http://localhost:8000" },
    },
  },
});
