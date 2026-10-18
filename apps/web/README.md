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
```

Start the server first (from the repo root): `uvicorn edu_platform.entrypoints.api.main:app --reload`.

## Build for the server to serve

```bash
npm run build        # type-checks, then writes apps/web/dist
```

The server serves `apps/web/dist` statically and falls back to `index.html` for the SPA routes
(`/learner`, `/instructor`, `/advisor`, `/admin`, `/pipeline`).

## Layout

```
src/
  api.ts          typed client, one function per endpoint
  types.ts        response/request types mirroring docs/api.md
  store.tsx       StoreProvider: reference data, live stats and the SSE event log
  hooks.ts        useFetch / useAction helpers and formatters
  components/     TopBar, FlowStrip (live pipeline strip), Rail, EventDrawer, ui primitives
  views/          Learner, Instructor, Advisor, Admin, Pipeline
  styles/global.css   design tokens and all styling
```

No UI kit or chart library: the heatmap, engagement lines and risk history use SVG/div.

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
