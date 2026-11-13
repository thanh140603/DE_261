# Staff sign-in

Instructor, Advisor and Organisation Admin use username and password in Classroom, Persistent and Replay. Each workspace has its own session. A session lasts eight hours and ends on sign-out or API restart. Sessions are held in one API process.

## Provision accounts

Run these commands from the repository root with the project's demo dependencies installed. Each command prompts for a password and its confirmation and prints a JSON array with one account. Choose a password of at least 12 characters for each account.

```bash
umask 077
accounts_dir=$(mktemp -d)
python -m edu_platform.br45.auth instructor instructor.demo instructor-local "Demo Instructor" \
  --course c-py-201 --course c-sql-101 --course c-de-301 > "$accounts_dir/instructor.json"
python -m edu_platform.br45.auth advisor advisor.demo advisor-local "Demo Advisor" \
  --course c-py-201 > "$accounts_dir/advisor.json"
python -m edu_platform.br45.auth admin admin.demo admin-local "Demo Admin" \
  --organisation org-acme --organisation org-globex > "$accounts_dir/admin.json"
python -m edu_platform.br45.auth admin acme-admin.demo acme-admin-local "Acme Admin" \
  --organisation org-acme > "$accounts_dir/acme-admin.json"
export EDU_STAFF_ACCOUNTS="$(jq -cs 'add' "$accounts_dir"/*.json)"
```

Compose forwards `EDU_STAFF_ACCOUNTS` to `demo` and `br45-bench-api`. Each entry uses `username`, `id`, `name`, `role`, `password_hash` and its assigned `courses` or `organisations`. Use stable IDs for accounts that already appear in audit records. Recreate the API container to load changed configuration. If a reverse proxy terminates HTTPS or replaces the original host, set `EDU_STAFF_ORIGIN` to the public origin, for example `https://learning.example.org`.

For the generated BR45 walkthrough, use the course ID from `jq -r .course_id "$DATA"` when provisioning the Instructor and Advisor. Start the walkthrough API with the updated `EDU_STAFF_ACCOUNTS`.

## Script and browser verification

Scripts can supply `Authorization: Bearer …` using a token configured in `EDU_BR45_AUTH`. The persistent verification harness reads `BR45_VERIFY_INSTRUCTOR_TOKEN` and `BR45_VERIFY_ADVISOR_TOKEN` from the caller's environment. The isolated benchmark overlay provisions its own fixture tokens.

For Playwright, set `BR45_BROWSER_STAFF_MODE` to the server's mode and `BR45_BASE_URL` to its URL. Tests use the demo usernames above by default. Override with `BR45_BROWSER_INSTRUCTOR_USERNAME`, `BR45_BROWSER_ADVISOR_USERNAME` and `BR45_BROWSER_ADMIN_USERNAME`. Set the corresponding `_PASSWORD` variables, or use `BR45_BROWSER_STAFF_PASSWORD` when the test accounts share a password. Classroom tests also need `BR45_BROWSER_CLASSROOM_PASSWORD`. Report tests that check Bearer access use the corresponding `BR45_VERIFY_*_TOKEN` variables.

```sh
cd apps/web
npx playwright test tests/staff-auth.spec.ts
```
