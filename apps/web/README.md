# DE_261 web client

Vite + React 18 + TypeScript dashboard for the demo. It talks to the FastAPI server described in
`docs/api.md` (prefix `/api`) and listens to `/api/events` (Server-Sent Events) for live updates.

BR4 assessment health and the Advisor view use persistent, authenticated APIs
through `src/analytics.ts`, refreshing every five seconds. Start the Compose
`br45` profile and seed its synthetic operational records first; see
[the implementation and runbook](../../docs/BR4_BR5_IMPLEMENTATION.md).
Local demo tokens are `instructor-demo` and `advisor-demo`.

## Run in development

```bash
cd apps/web
npm install
npm run dev          # http://localhost:5173, proxies /api to http://localhost:8000
API_URL=http://localhost:8001 npm run dev -- --port 5174   # proxy to another API, e.g. a source checkout
```

Start the server first (from the repo root): `uvicorn edu_platform.entrypoints.api.main:app --reload`.

## Build for the server to serve

```bash
npm run build        # type-checks, then writes apps/web/dist
```

The server serves `apps/web/dist` statically and falls back to `index.html` for the SPA routes.

## Workspaces and routes

The design follows the clickable mockup in `docs/ui-mockup/edu-platform-ui-mockup.html`: one workspace
per stakeholder, chosen in the sidebar, each with its own pages.

| Workspace | Route | Page | BR |
|-----------|-------|------|----|
| Learner | `/learner` | Home: courses, recommendations, recent feedback, notifications | BR1, BR2 |
| Learner | `/learner/code-lab` | Code lab: editor, test-by-test feedback, attempts (`?submission=<id>` opens one) | BR3 |
| Instructor | `/instructor/assessments` | Assessment health, question to test-case drill-down | BR4 |
| Instructor | `/instructor/videos` | Video insights: per-version heatmap, live overlay, moments to review | BR7 |
| Instructor | `/instructor/engagement` | Engagement trend: course average, declining learners | BR8 |
| Instructor | `/instructor/content` | Content and search: publish, follow the sync, search preview | BR8 |
| Advisor | `/advisor` | Learners to support: risk queue, point breakdown, history, alert lifecycle | BR5 |
| Org admin | `/admin` | Organisation progress with k-anonymous suppression, CSV export | BR6 |
| Data platform | `/pipeline` | Pipeline health: flow counters, throughput, topics, dead letters, silver tail | Ops |

Instructor, Advisor and Org admin pages sit behind a sign-in card that takes the role's access token
(`instructor-demo`, `advisor-demo`, `admin-demo` locally). The token is kept for the browser tab and
shared by every page of that workspace. Demo-only controls (simulate LMS events, the telemetry
simulator, send one event) sit in dashed "Demo controls" sections.

## Layout

```
src/
  api.ts / analytics.ts   typed clients: demo API and the authenticated analytics APIs
  types.ts                response/request types mirroring docs/api.md
  store.tsx               StoreProvider: reference data, live stats, SSE event log, selected learner
  notifications.ts        BR1 notifications hook with a per-browser "seen" mark
  workspaces.ts           workspace and page definitions (sidebar order, routes, BR tags)
  hooks.ts                useFetch / useAction / usePersisted and formatters
  components/
    Shell.tsx             sidebar, top bar (live events, notifications, sign-out), theme and BR-tag switches
    AnalyticsAccess.tsx   AuthProvider and the sign-in gate per role
    ui.tsx                cards, tiles, badges, controls, toast
    charts.tsx            line chart with crosshair tooltip, small multiples, horizontal bars
    Icon.tsx              stroke icon set
  views/                  learner/, instructor/, AdvisorView, AdminView, PipelineView
  styles/global.css       design tokens (light and dark) and all styling
```

No UI kit or chart library: charts are SVG with a hover tooltip and a "View as table" fallback.
Chart colours use a validated palette (categorical slots and one blue sequential ramp); status colours
are reserved for state and always carry an icon and a label.

## BR1–BR3 browser acceptance checks

```bash
# service-mode stack first (repo root)
docker compose -f docker-compose.yml -f docker-compose.br13.yml up -d --build

npm ci
npx playwright install chromium
npx playwright test tests/br123.spec.ts
```

Evidence is written to `docs/evidence/br123/` (`browser-results.json`, screenshots).
On a minimal Linux host, Chromium may need `libnspr4`, `libnss3` and
`libasound2`; install them or point `PLAYWRIGHT_BROWSERS_PATH` at a provisioned
browser directory.

## BR4/BR5 browser acceptance checks

```bash
npm ci
npx playwright install chromium
npm run test:br45
```

Requires the running, seeded `br45` profile. These tests make reversible grade
corrections and create synthetic learner recovery activity through the real
pipeline. Screenshots and results go to `docs/evidence/br45/`. Set
`BR45_BASE_URL` to test an alternative local API URL.
