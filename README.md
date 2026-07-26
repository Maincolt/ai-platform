# AI Platform

AI Platform is a foundation for coordinating specialized AI agents through
modular boundaries and event-driven communication.

The repository is currently at its initial structure and documentation stage.
The architecture below describes the direction of the project, not completed
functionality.

## Project Vision

The project aims to make collaborative AI systems easier to extend, operate,
and understand. Instead of concentrating every responsibility in one assistant,
the platform will coordinate focused agents that can work independently and
collaborate through stable contracts.

The platform is intended to support different models, service providers, and
deployment environments without making the core architecture depend on any one
of them. Components should be replaceable as requirements change.

## Philosophy

- **Modular by default** — Each component has a focused responsibility and a
  clear boundary.
- **Events over direct coupling** — Components collaborate through documented
  events and contracts rather than knowledge of each other's internals.
- **Specialization over monoliths** — Agents remain small enough to reason
  about, test, replace, and evolve independently.
- **Vendor and environment neutral** — External systems are integrations, not
  assumptions embedded in the core design.
- **Git-first and reproducible** — Documentation, configuration, and
  infrastructure definitions belong in version control.
- **Documented decisions** — Significant architectural choices are recorded as
  Architecture Decision Records alongside the project.
- **Open interfaces** — Interoperability and explicit contracts are preferred
  over proprietary coupling.

## Repository Layout

```text
.
├── agents/                         # Agent definitions and agent-local assets
├── docs/
│   └── architecture/
│       └── decisions/              # Architecture Decision Records
├── infrastructure/                 # Infrastructure definitions
├── monitoring/                     # Observability configuration
├── scripts/                        # Development and operations utilities
├── skills/                         # Reusable agent capabilities
├── tests/                          # Automated validation
├── AGENTS.md                       # Repository-wide contributor guidance
└── README.md
```

Each top-level area owns a distinct concern. Its local `README.md` describes
the intended boundary without committing the project to an implementation that
has not yet been selected.

## High-Level Architecture

The intended architecture separates coordination, communication, agent
behavior, and external integrations:

```text
                         External requests
                                 |
                                 v
                    +-------------------------+
                    |      Orchestrator       |-----+
                    +------------+------------+     |
                                 |                  |
                         workflow events            | AI capability
                                 |                  | requests
                                 v                  |
                    +-------------------------+     |
                    |        Event Bus        |     |
                    +------------+------------+     |
                                 |                  |
                                 v                  |
                    +-------------------------+     |
                    |         Agents          |-----+
                    +-------------------------+     |
                                                   v
                                      +-------------------------+
                                      |        AI Router        |
                                      +------------+------------+
                                                   |
                                                   v
                                      External AI capabilities
```

The orchestration boundary coordinates work without absorbing agent-specific
behavior. Agents own focused responsibilities and collaborate through explicit
events on the Event Bus. AI capability requests pass through the AI Router so
that external providers remain behind a replaceable boundary.

See the [platform architecture](docs/architecture/README.md) for component
responsibilities and collaboration flows. Significant design choices are
recorded in the [ADR index](docs/architecture/decisions/README.md).

## License

This project is available under the [MIT License](LICENSE).
