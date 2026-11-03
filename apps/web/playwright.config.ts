import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  timeout: 60000,
  expect: { timeout: 25000 },
  use: { baseURL: process.env.BR45_BASE_URL ?? "http://localhost:8000", viewport: { width: 1440, height: 1050 }, screenshot: "only-on-failure" },
  // EVIDENCE=br678 records BR6-BR8 runs separately instead of overwriting the BR4/BR5 results
  reporter: [["list"], ["json", { outputFile: `../../docs/evidence/${process.env.EVIDENCE ?? "br45"}/browser-results.json` }]],
});
