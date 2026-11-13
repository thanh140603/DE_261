import type { Page } from "@playwright/test";

export type StaffRole = "instructor" | "advisor" | "admin";

export async function signInStaff(page: Page, role: StaffRole, invalid = false) {
  const prefix = `BR45_BROWSER_${role.toUpperCase()}`;
  const username = process.env[`${prefix}_USERNAME`] ?? `${role}.demo`;
  const password = process.env[`${prefix}_PASSWORD`] ?? process.env.BR45_BROWSER_STAFF_PASSWORD;
  if (!password && !invalid) throw new Error(`Set ${prefix}_PASSWORD or BR45_BROWSER_STAFF_PASSWORD`);
  await page.getByLabel("Username", { exact: true }).fill(username);
  await page.getByLabel("Password", { exact: true }).fill(invalid ? "invalid-credentials" : password!);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
}

export function bearerFor(name: StaffRole | "acme-admin") {
  const key = `BR45_VERIFY_${name.replace("-", "_").toUpperCase()}_TOKEN`;
  const token = process.env[key];
  if (!token) throw new Error(`Set ${key} to a configured API token`);
  return { Authorization: `Bearer ${token}` };
}
