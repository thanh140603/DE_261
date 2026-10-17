import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  timeout: 60000,
  expect: { timeout: 25000 },
  use: { baseURL: process.env.BR45_BASE_URL ?? "http://localhost:8000", viewport: { width: 1440, height: 1050 }, screenshot: "only-on-failure" },
  reporter: [["list"], ["json", { outputFile: "../../docs/evidence/br45/browser-results.json" }]],
});
