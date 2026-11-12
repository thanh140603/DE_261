import { expect, test } from "@playwright/test";

test("replay publishes the same synthetic stage to Instructor and Advisor", async ({ page, request }) => {
  test.skip(!process.env.BR45_REPLAY_BROWSER, "Start the replay server first");
  await page.goto("/instructor/assessments");
  await page.getByLabel("instructor access token").fill("instructor-demo");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(page.getByText("Simulated data", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Measured benchmarks" })).toBeVisible();

  const endpoint = "/api/analytics/replay";
  const advisor = { Authorization: "Bearer advisor-demo" };
  const initial = await (await request.get(endpoint, { headers: advisor })).json();
  await page.getByRole("button", { name: "Advance demo" }).click();
  await expect.poll(async () => (await (await request.get(endpoint, { headers: advisor })).json()).revision)
    .toBeGreaterThan(initial.revision);

  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.goto("/advisor");
  await page.getByLabel("advisor access token").fill("advisor-demo");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(page.getByText("Simulated data", { exact: true })).toBeVisible();
  await expect(page.getByRole("list", { name: "Learners to review" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});

test("a classroom learner records lesson activity and gets persistent Code Lab feedback", async ({ page }) => {
  const password = process.env.BR45_BROWSER_CLASSROOM_PASSWORD;
  test.skip(!password, "Start a classroom fixture with the same password");
  if (process.env.BR45_BROWSER_MOBILE) {
    await page.setViewportSize({ width: 390, height: 844 });
  }
  await page.goto("/learner");
  await page.getByLabel("Username").fill("chi.demo");
  await page.getByLabel("Password").fill(password!);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();

  const lesson = page.getByRole("listitem").filter({ has: page.getByRole("button", { name: "Start lesson" }) }).first();
  await lesson.getByRole("button", { name: "Start lesson" }).click();
  await expect(page.getByRole("button", { name: "Complete lesson" }).first()).toBeVisible();
  await page.getByRole("button", { name: "Complete lesson" }).first().click();

  await page.goto("/learner/code-lab");
  await page.getByLabel("Assignment", { exact: true }).selectOption("a-py-fizz");
  await page.getByLabel("Code", { exact: true }).fill(
    'def fizzbuzz(n):\n    return ["FizzBuzz" if i % 15 == 0 else "Fizz" if i % 3 == 0 else "Buzz" if i % 5 == 0 else str(i) for i in range(1, n + 1)]',
  );
  const response = page.waitForResponse((r) => r.url().endsWith("/api/submissions") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Submit code" }).click();
  const written = await response;
  expect(written.status()).toBe(202);
  const { submission_id: id } = await written.json();
  await expect(page.getByRole("region", { name: "Feedback" }).getByText("All passed")).toBeVisible();
  expect((await (await page.request.get(`/api/submissions/${id}`)).json()).id).toBe(id);

  expect(await page.evaluate(() => document.documentElement.scrollWidth))
    .toBeLessThanOrEqual(page.viewportSize()!.width);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByLabel("Username")).toBeVisible();
  expect((await page.request.get(`/api/submissions/${id}`)).status()).toBe(401);
});
