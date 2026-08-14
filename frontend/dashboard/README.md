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
CI/CD) is not yet wired up beyond the local container below.

## Running in its own container

`Dockerfile` is a multi-stage build: `npm run build`, then serve the
static bundle from a minimal `nginx:1.27-alpine` image. `nginx.conf`
reverse-proxies `/api/` and `/health/` to the real platform process, so
the same relative-path `fetch()` calls this app uses in local dev work
unchanged in the container — no separate "production API URL" to
configure.

This is wired into `infrastructure/compose/docker-compose.yml` as the
`dashboard` service (see `infrastructure/README.md`'s "Agent status
dashboard" section for why it shares `platform`'s network namespace
rather than getting its own). The topology runs on a dedicated Docker host
(a Mac at `192.168.1.123`, see `infrastructure/README.md` Section 1) —
run these from an SSH session into it:

```bash
ssh -i ~/.ssh/mac_docker gebruiker@192.168.1.123
cd ~/ai-platform/infrastructure/compose
docker compose --profile app build dashboard
docker compose --profile app up -d platform test-agent dashboard
```

Open `http://192.168.1.123:8080` (or `http://127.0.0.1:8080` if browsing
from the Docker host itself). If the image was built before a `src/`
change merged, rebuild `ai-platform:sprint6` itself first
(`docker build -f infrastructure/Dockerfile -t ai-platform:sprint6 .`
from the repository root) — `docker compose build dashboard` only
rebuilds the dashboard's own image, not `platform`'s.
