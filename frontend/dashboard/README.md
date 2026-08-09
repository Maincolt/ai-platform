# Agent Status Dashboard

A small Vue 3 + Vite single-page app that shows every Agent binding
declared in the Capability Registry and its current readiness status,
polling `GET /api/v1/agents` every 5 seconds.

This is a read-only view. It never submits work and never affects
candidate selection — it shows exactly what `SubmissionOrchestrator`
itself sees.

## Running locally

Requires the platform's Workflow API running and reachable at
`http://127.0.0.1:8000` (see `infrastructure/README.md`, or run the
in-memory dev command from the repository root: `ai-platform-dev`, if
configured, or any process serving `src/ai_platform/api/app.py`).

```bash
cd frontend/dashboard
npm install
npm run dev
```

Open the printed local URL (typically `http://localhost:5173`). The dev
server proxies `/api` and `/health` to `http://127.0.0.1:8000`, so the
browser never needs the backend to send CORS headers.

## Building

```bash
npm run build
```

Outputs a static `dist/` bundle. Deployment (Azure static hosting,
CI/CD) is not yet wired up — this first pass is local-dev only.
