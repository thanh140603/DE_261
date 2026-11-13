import { expect, test } from "@playwright/test";
import { signInStaff } from "./staff-credentials";

test("staff sessions coexist, survive reload, and sign out independently", async ({ page, context }) => {
  const mode = process.env.BR45_BROWSER_STAFF_MODE;
  test.skip(!mode, "Set BR45_BROWSER_STAFF_MODE to persistent, classroom or replay");
  const advisor = await context.newPage();
  const admin = await context.newPage();
  await page.goto("/instructor/assessments");
  await signInStaff(page, "instructor", true);
  await expect(page.getByText("Invalid username or password")).toBeVisible();
  await signInStaff(page, "instructor");
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  await advisor.goto("/advisor");
  await signInStaff(advisor, "advisor");
  await expect(advisor.getByRole("button", { name: "Sign out" })).toBeVisible();
  await admin.goto("/admin");
  await signInStaff(admin, "admin");
  await expect(admin.getByRole("button", { name: "Sign out" })).toBeVisible();
  await expect(admin.getByLabel("Organisation")).toHaveValue("org-acme");
  if (process.env.BR45_BROWSER_TRINO_DOWN) {
    await expect(admin.getByText(/lakehouse warehouse \(Trino\) is unavailable/)).toBeVisible();
  }
  if (mode === "replay") {
    await expect(page.getByText("Simulated data", { exact: true })).toBeVisible();
    await expect(advisor.getByText("Simulated data", { exact: true })).toBeVisible();
  }
  if (mode === "classroom") {
    const student = await context.newPage();
    await student.goto("/learner");
    await student.getByLabel("Username").fill("chi.demo");
    await student.getByLabel("Password").fill(process.env.BR45_BROWSER_CLASSROOM_PASSWORD!);
    await student.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(student.getByRole("button", { name: "Sign out" })).toBeVisible();
  }
  await page.reload();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByLabel("Username", { exact: true })).toBeVisible();
  expect((await page.request.get("/api/auth/staff/instructor/session")).status()).toBe(401);
  await advisor.reload();
  await expect(advisor.getByRole("button", { name: "Sign out" })).toBeVisible();
  expect((await page.request.get("/api/auth/staff/admin/session")).status()).toBe(200);
  if (mode === "classroom") {
    expect((await page.request.get("/api/classroom/student/session")).status()).toBe(200);
  }
});
