import { expect, test, type APIRequestContext } from "@playwright/test";
import { execFileSync } from "node:child_process";

// Needs the lakehouse marts (README "Run the lakehouse warehouse": bootstrap, seed-bronze
// --end-date 2026-10-17 --days 35, run --start-date 2026-08-01) and Trino; skipped otherwise.
async function lakehouseReady(request: APIRequestContext) {
  const response = await request.get("/api/lakehouse/session", { headers: { Authorization: "Bearer admin-demo" } });
  return response.ok();
}

test("Admin reads the k-anonymous organisation report from the lakehouse", async ({ page, request }) => {
  test.skip(!(await lakehouseReady(request)), "lakehouse marts / Trino not available");
  await page.goto("/admin");
  await page.getByLabel("admin access token").fill("admin-demo");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  const sql = page.getByRole("row").filter({ has: page.getByRole("cell", { name: "SQL Foundations" }) });
  await expect(sql).toContainText("%");
  await expect(page.getByText("Hidden: fewer than")).toHaveCount(0);
  await page.getByLabel("Organisation").selectOption("org-globex");
  await expect(page.getByText("Hidden: fewer than 5 learners").first()).toBeVisible();
  await expect(page.getByRole("row").filter({ hasText: "Hidden" }).first()).not.toContainText("%");

  // a single-organisation admin cannot reach another organisation, in the UI or the API
  const scoped = await request.get("/api/admin/organisations/org-globex/skill-progress", { headers: { Authorization: "Bearer acme-admin-demo" } });
  expect(scoped.status()).toBe(403);
  const forbidden = await request.get("/api/admin/organisations/org-acme/skill-progress", { headers: { Authorization: "Bearer instructor-demo" } });
  expect(forbidden.status()).toBe(403);
});

test("Instructor reads per-version video heatmaps and the engagement trend", async ({ page, request }) => {
  test.skip(!(await lakehouseReady(request)), "lakehouse marts / Trino not available");
  await page.goto("/instructor/videos");
  await page.getByLabel("instructor access token").fill("instructor-demo");
  await page.getByRole("button", { name: "Connect", exact: true }).click();

  await page.getByLabel("Course").selectOption("c-sql-101");
  await page.getByLabel("Lesson video").selectOption("v-sql-joins");
  await expect(page.getByText(/version 2, 390 s/)).toBeVisible(); // newest re-cut by default
  await page.getByLabel("Video version").selectOption("1");
  await expect(page.getByText(/version 1, 420 s/)).toBeVisible();
  await expect(page.locator(".heat .col")).not.toHaveCount(0);

  await page.goto("/instructor/engagement");
  await expect(page.getByLabel("instructor access token")).toHaveCount(0); // one token for every instructor page
  await expect(page.getByText(/weekly windows from/)).toBeVisible();
  await expect(page.getByText("Declining", { exact: true }).first()).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("Instructor publishes a transcript version and sees cache, vectors and search follow it", async ({ page, request }) => {
  const ready = await request.get("/api/instructor/courses/c-sql-101/content", { headers: { Authorization: "Bearer instructor-demo" } });
  test.skip(!ready.ok(), "content services (profile br678) not available");
  await page.goto("/instructor/content");
  await page.getByLabel("instructor access token").fill("instructor-demo");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await page.getByLabel("Course").selectOption("c-sql-101");

  const row = page.getByRole("row").filter({ has: page.getByRole("button", { name: /^Joins/ }) });
  await expect(row).toContainText("In sync");
  const before = Number((await row.getByRole("cell").nth(1).innerText()).replace("v", ""));
  await row.getByRole("button").click();
  await expect(page.getByText(/Editing Joins from v\d+ \(served from cache/)).toBeVisible();

  const marker = `checkpoint-${Date.now()}`;
  const body = page.getByLabel("Transcript body");
  await body.fill(`# Joins\n\nA right join keeps every row of the right table, marker ${marker} included.`);
  await page.getByRole("button", { name: "Publish new version" }).click();
  await expect(page.getByText(new RegExp(`Version ${before + 1} is searchable`))).toBeVisible({ timeout: 60000 });
  await expect(row).toContainText(`v${before + 1}`);
  await expect(page.getByText(new RegExp(`Editing Joins from v${before + 1} \\(served from cache: miss\\)`))).toBeVisible();

  await page.getByLabel("Search this course").fill(marker);
  await page.getByRole("button", { name: "Search", exact: true }).click();
  const results = page.getByRole("list", { name: "Search results" });
  await expect(results).toContainText(marker);
  await expect(results).toContainText(`v${before + 1}`);
});

test("Instructor sees today's streamed interactions on top of the daily marts", async ({ page, request }) => {
  test.skip(!(await lakehouseReady(request)), "lakehouse marts / Trino not available");
  const heatmap = async () => (await (await request.get("/api/instructor/videos/v-sql-group/interaction-heatmap", { headers: { Authorization: "Bearer instructor-demo" } })).json());
  test.skip(!("live" in (await heatmap())), "server without live overlays");
  // live telemetry -> Kafka -> telemetry-live (Spark) -> Redis; requires the br678 profile
  execFileSync("docker", ["compose", "exec", "-T", "demo", "edu", "telemetry", "simulate", "--sessions", "40"], { cwd: "../..", timeout: 60000 });
  await expect.poll(async () => (await heatmap()).live?.seconds.length ?? 0, { timeout: 60000 }).toBeGreaterThan(0);

  await page.goto("/instructor/videos");
  await page.getByLabel("instructor access token").fill("instructor-demo");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await page.getByLabel("Course").selectOption("c-sql-101");
  await page.getByLabel("Lesson video").selectOption("v-sql-group");
  await expect(page.getByText(/streamed interactions? from/)).toBeVisible();
  await page.screenshot({ path: "../../docs/evidence/br678/instructor-live.png", fullPage: true });
  await page.getByLabel("Include today (live)").uncheck();
  await expect(page.getByText(/streamed interactions? from/)).toHaveCount(0);
  await page.goto("/instructor/engagement");
  await page.getByLabel("Course").selectOption("c-sql-101");
  await expect(page.getByText(/Today \(.+\) so far: \d+ active learner/)).toBeVisible();
});
