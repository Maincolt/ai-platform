# Repository Guidance

This repository hosts a modular, event-driven AI agent platform.

## Principles

- Preserve modular boundaries and communicate across them through documented
  contracts and events.
- Keep AI model, infrastructure, cloud, and service integrations replaceable.
- Prefer open standards and reproducible Infrastructure as Code.
- Design deployment assets for Docker and support Unraid as a first-class
  target.
- Keep changes Git-first and never commit secrets or environment-specific
  credentials.

## Architecture

Document every major architectural decision as an ADR under
`docs/architecture/decisions/`. Update relevant documentation with the change
that introduces or alters a component, interface, event, or operational
procedure.

## Project Layout

- `agents/` — agent definitions and agent-local assets
- `docs/` — project and architecture documentation
- `infrastructure/` — deployment configuration and Infrastructure as Code
- `monitoring/` — observability configuration
- `scripts/` — development and operations utilities
- `skills/` — reusable agent capabilities
- `tests/` — automated validation
