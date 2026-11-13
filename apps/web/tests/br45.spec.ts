import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { bearerFor, signInStaff } from "./staff-credentials";

const CDC_TIMEOUT = 150_000;
const EVIDENCE = `../../docs/evidence/${process.env.EVIDENCE ?? "br45"}`;

function runSourceScript(source: string, ...args: string[]) {
  return execFileSync("docker", [
    "compose", "exec", "-T", "br45-cdc", "python", "-c", source, ...args,
  ], { cwd: "../..", timeout: 30000 });
}

test("Instructor reads actual metrics, drills down and refreshes after a PostgreSQL correction", async ({ page, request }) => {
  test.setTimeout(220_000);
  await page.goto("/instructor/assessments");
  await signInStaff(page, "instructor");
  const question = page.getByRole("row").filter({ has: page.getByRole("button", { name: /SYNTHETIC: Sum even numbers/ }) });
  await expect(question).toContainText("8%", { timeout: CDC_TIMEOUT });
  await question.getByRole("button").click();
  await expect(page.getByRole("region", { name: "Selected question test cases" }).getByText("Suspicious test case", { exact: true })).toBeVisible();
  await expect(page.getByText(/below the median of other required tests/)).toBeVisible();
  await page.screenshot({ path: `${EVIDENCE}/instructor-desktop.png`, fullPage: true });
  const correct = (status: string) => execFileSync("docker", ["compose", "exec", "-T", "br45-cdc", "python", "-c", `from edu_platform.br45.db import connect\nwith connect() as c:\n c.execute("UPDATE br45.evaluations SET status=%s WHERE id=%s", ("${status}", "br45-demo-evaluation-2-1"))`], { cwd: "../..", timeout: 30000 });
  try {
    correct("passed");
    await expect(question).toContainText("13%", { timeout: CDC_TIMEOUT });
    const response = await request.get("/api/instructor/courses/c-py-201/questions/statistics", { headers: bearerFor("instructor") });
    const data = await response.json();
    expect(data.items.find((r: { question_id: string }) => r.question_id === "br45-demo-question").passed_evaluations).toBe(3);
  } finally { correct("failed"); }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => window.scrollTo(0, 0));
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: `${EVIDENCE}/instructor-mobile.png`, fullPage: true });
});

test("Advisor manages an actual alert and sees CDC recovery without refreshing the page", async ({ page }) => {
  test.setTimeout(350_000);
  const student = `br45-browser-${randomUUID().slice(0, 8)}`;
  const study = (phase: "prior" | "recent" | "cleanup") => runSourceScript(`
from datetime import timedelta
from sys import argv

from edu_platform.br45.contracts import timestamp
from edu_platform.br45.db import connect, state
from edu_platform.br45.fixtures import upsert

student, phase = argv[1:]
with connect() as db:
    if phase == "cleanup":
        db.execute("DELETE FROM br45.activity_events WHERE student_id=%s", (student,))
        db.execute("DELETE FROM br45.enrollments WHERE id=%s", (student + "-enrollment",))
    else:
        at = timestamp(state(db, "evaluation_clock"))
        course = "c-py-201"
        if phase == "prior":
            upsert(db, "enrollments", {
                "id": student + "-enrollment", "student_id": student,
                "course_id": course, "status": "active",
                "enrolled_at": at - timedelta(days=30),
            })
        for index in range(4):
            event_at = at - (timedelta(days=8 + index) if phase == "prior"
                             else timedelta(minutes=index + 1))
            upsert(db, "activity_events", {
                "id": f"{student}-{phase}-{index}", "student_id": student,
                "course_id": course, "event_type": "lesson_complete", "event_time": event_at,
            })
`, student, phase);

  study("prior");
  try {
    await page.goto("/advisor");
    await signInStaff(page, "advisor");
    const riskRow = page.getByRole("button", { name: student, exact: true });
    await expect(riskRow).toContainText("100", { timeout: CDC_TIMEOUT });
    await expect(riskRow).toContainText("Critical");
    await riskRow.click();
    const detail = page.getByRole("region", { name: `Risk detail for ${student}` });
    await detail.getByRole("button", { name: "Acknowledge", exact: true }).click();
    await expect(detail).toContainText("Acknowledged");
    await page.screenshot({ path: `${EVIDENCE}/advisor-desktop.png`, fullPage: true });

    study("recent");
    await expect(riskRow).toContainText("50", { timeout: CDC_TIMEOUT });
    await expect(riskRow).toContainText("Medium");
    await expect(detail).toContainText("Resolved");
    await expect(page.getByText("Risk history · points out of 100")).toBeVisible();
    await page.setViewportSize({ width: 390, height: 844 });
    await page.evaluate(() => window.scrollTo(0, 0));
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: `${EVIDENCE}/advisor-mobile.png`, fullPage: true });
  } finally {
    study("cleanup");
  }
});

test("Invalid credentials display an access error and do not expose learner records", async ({ page, request }) => {
  await page.goto("/advisor");
  await signInStaff(page, "advisor", true);
  await expect(page.getByText(/Invalid username or password/)).toBeVisible();
  await expect(page.getByLabel("Username", { exact: true })).toBeVisible();
  expect((await request.get("/api/advisor/alerts")).status()).toBe(401);
  expect((await request.get("/api/advisor/alerts", { headers: bearerFor("instructor") })).status()).toBe(403);
  expect((await request.get("/api/advisor/courses/c-sql-101/at-risk-students", { headers: bearerFor("advisor") })).status()).toBe(403);
});
