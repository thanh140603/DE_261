# DE_261 web client

Vite + React 18 + TypeScript dashboard for the demo. It talks to the FastAPI server described in
`docs/api.md` (prefix `/api`) and listens to `/api/events` (Server-Sent Events) for live updates.

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

No UI kit and no chart library: the heatmap, engagement lines, risk gauge and sparklines are plain SVG/div.
