var _a, _b, _c;
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
// API_URL points the dev proxy at another server, e.g. a source checkout on :8001.
var env = (_b = (_a = globalThis.process) === null || _a === void 0 ? void 0 : _a.env) !== null && _b !== void 0 ? _b : {};
export default defineConfig({
    plugins: [react()],
    base: "/",
    build: { outDir: "dist", emptyOutDir: true },
    server: {
        port: 5173,
        proxy: {
            "/api": { target: (_c = env.API_URL) !== null && _c !== void 0 ? _c : "http://localhost:8000", changeOrigin: true },
        },
    },
});
