import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";

const EVIDENCE = "../../docs/evidence/br123";
mkdirSync(EVIDENCE, { recursive: true });

/**
 * BR1–BR3 browser smoke on the service-mode stack:
 *   docker compose -f docker-compose.yml -f docker-compose.br13.yml up -d --build
 *   npx playwright test tests/br123.spec.ts
 */
test.describe("BR1–BR3 learner flows", () => {
  test("BR2 recommendation and BR1 notification controls render", async ({ page }) => {
    await page.goto("/learner");
    await expect(page.getByRole("heading", { name: /Recommended courses/i })).toBeVisible();
    await page.screenshot({ path: `${EVIDENCE}/learner-home.png`, fullPage: true });
    await expect(page.getByText(/Demo controls/i)).toBeVisible();

    await page.getByText(/Demo controls/i).click();
    await page.getByRole("button", { name: /Send deadline reminder/i }).click();
    await expect(
      page.getByText(/queued to the notification service|notification.*created/i).first(),
    ).toBeVisible();
  });

  test("BR3 submit shows test-by-test feedback", async ({ page }) => {
    await page.goto("/learner/code-lab");
    await expect(page.getByRole("heading", { name: /Assignments|Code lab/i })).toBeVisible();

    const editor = page.getByLabel("Code");
    await editor.fill(
      [
        "def fizzbuzz(n):",
        "    out = []",
        "    for i in range(1, n + 1):",
        '        if i % 15 == 0: out.append("FizzBuzz")',
        '        elif i % 3 == 0: out.append("Fizz")',
        '        elif i % 5 == 0: out.append("Buzz")',
        "        else: out.append(str(i))",
        "    return out",
      ].join("\n"),
    );
    await page.getByRole("button", { name: /Submit code/i }).click();
    await expect(page.getByText(/tests passed/i).first()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/All passed|Partly correct/i).first()).toBeVisible();
    await page.screenshot({ path: `${EVIDENCE}/code-lab.png`, fullPage: true });
  });
});
