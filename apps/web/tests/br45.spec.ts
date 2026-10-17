import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";

test("Instructor reads actual metrics, drills down and refreshes after a PostgreSQL correction", async ({ page, request }) => {
  await page.goto("/instructor");
  await page.getByLabel("instructor access token").fill("instructor-demo");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  const question = page.getByRole("row").filter({ has: page.getByRole("button", { name: /SYNTHETIC: Sum even numbers/ }) });
  await expect(question).toContainText("8%");
  await question.getByRole("button").click();
  await expect(page.getByRole("region", { name: "Selected question test cases" }).getByText("SUSPICIOUS TEST CASE", { exact: true })).toBeVisible();
  await expect(page.getByText(/below the median of other required tests/)).toBeVisible();
  await page.screenshot({ path: "../../docs/evidence/br45/instructor-desktop.png", fullPage: true });
  const correct = (status: string) => execFileSync("docker", ["compose", "exec", "-T", "br45-cdc", "python", "-c", `from edu_platform.br45.db import connect\nwith connect() as c:\n c.execute("UPDATE br45.evaluations SET status=%s WHERE id=%s", ("${status}", "br45-demo-evaluation-2-1"))`], { cwd: "../..", timeout: 30000 });
  try {
    correct("passed");
    await expect(question).toContainText("13%");
    const response = await request.get("/api/instructor/courses/c-py-201/questions/statistics", { headers: { Authorization: "Bearer instructor-demo" } });
    const data = await response.json();
    expect(data.items.find((r: { question_id: string }) => r.question_id === "br45-demo-question").passed_evaluations).toBe(3);
  } finally { correct("failed"); }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => window.scrollTo(0, 0));
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: "../../docs/evidence/br45/instructor-mobile.png", fullPage: true });
});

test("Advisor manages an actual alert and sees CDC recovery without refreshing the page", async ({ page, request }) => {
  await page.goto("/advisor");
  await page.getByLabel("advisor access token").fill("advisor-demo");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  const riskRow = page.getByRole("row").filter({ has: page.getByRole("button", { name: "br45-demo-at-risk", exact: true }) }).first();
  await expect(riskRow).toContainText("100");
  await expect(riskRow).toContainText("CRITICAL");
  const alertRow = page.getByRole("row").filter({ has: page.getByRole("button", { name: "br45-demo-at-risk", exact: true }) }).last();
  if (await alertRow.getByRole("button", { name: "Acknowledge", exact: true }).isEnabled()) {
    await alertRow.getByRole("button", { name: "Acknowledge", exact: true }).click();
    await expect(alertRow).toContainText("ACKNOWLEDGED");
  }
  await page.screenshot({ path: "../../docs/evidence/br45/advisor-desktop.png", fullPage: true });
  const response = await request.get("/api/advisor/students/br45-demo-at-risk/risk", { headers: { Authorization: "Bearer advisor-demo" } });
  const at = new Date((await response.json()).courses[0].evaluated_at).getTime();
  for (let i = 0; i < 4; i++) {
    const written = await request.post("/api/learning/activity", { headers: { Authorization: "Bearer learner-demo" }, data: { event_id: `br45-demo-recovery-browser-${i}`, course_id: "c-py-201", event_type: "lesson_complete", event_time: new Date(at - (i + 1) * 60000).toISOString() } });
    expect(written.status()).toBe(202);
  }
  await expect(riskRow).toContainText("50");
  await expect(riskRow).toContainText("MEDIUM");
  await expect(alertRow).toContainText("RESOLVED");
  await riskRow.getByRole("button").click();
  await expect(page.getByText("Risk history · points out of 100")).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => window.scrollTo(0, 0));
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: "../../docs/evidence/br45/advisor-mobile.png", fullPage: true });
});

test("Invalid credentials display an access error and do not expose learner records", async ({ page, request }) => {
  await page.goto("/advisor");
  await page.getByLabel("advisor access token").fill("incorrect-token");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(page.getByText(/Invalid analytics access token/)).toBeVisible();
  expect((await request.get("/api/advisor/alerts")).status()).toBe(401);
  expect((await request.get("/api/advisor/alerts", { headers: { Authorization: "Bearer instructor-demo" } })).status()).toBe(403);
  expect((await request.get("/api/advisor/courses/c-sql-101/at-risk-students", { headers: { Authorization: "Bearer advisor-demo" } })).status()).toBe(403);
});
