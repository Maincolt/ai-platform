# ADR-0003: Runtime and Development Tooling

- **Status:** Proposed
- **Date:** Not yet accepted
- **Supersedes:** None
- **Superseded by:** None

## Context

ADR-0001 requires modularity, vendor neutrality, portability, Git-first
development, Docker-based deployment, and documented architectural decisions.
ADR-0002 defines asynchronous component collaboration, Orchestrator-owned
workflow state, explicit contracts, idempotency, and capability discovery. It
does not select a runtime or development toolchain.

The first vertical slice proposes several platform modules and deployable
components. Using different runtime and quality toolchains for those components
would increase onboarding, maintenance, dependency, container, and CI costs
before there is evidence that multiple ecosystems are necessary.

This ADR evaluates one runtime and development ecosystem for platform-owned
components. The choice must support AI-agent development and asynchronous,
event-driven services without coupling the architecture to an AI provider,
cloud, CI product, or infrastructure implementation.

The repository contains no implementation code or accepted runtime tooling at
the time of this proposal. Every technology in this ADR is therefore evaluated
rather than treated as an existing standard.

## Decision Drivers

The decision is evaluated against:

- suitability for AI agents and their supporting libraries;
- clear asynchronous and event-driven programming models;
- mature dependency, testing, typing, and editor ecosystems;
- deterministic dependency resolution and repeatable environments;
- portability across Windows, Linux, containers, Unraid, and common CI
  workers;
- low feedback time for local and CI checks;
- maintainability of explicit module and contract boundaries;
- approachable onboarding without hiding important behavior;
- ability to evolve without coupling platform contracts to the runtime; and
- a manageable number of overlapping tools and configuration files.

Performance is relevant, but raw compute throughput is not assumed to outweigh
AI ecosystem access, delivery speed, and maintainability for the initial
I/O-oriented platform workload.

## Runtime Language Evaluation

### Comparative Summary

| Criterion | Python | Go | TypeScript |
| --- | --- | --- | --- |
| AI-agent suitability | Broad AI, model, data, evaluation, and automation ecosystem; many provider SDKs appear in Python early | Good HTTP and infrastructure SDKs, but fewer AI-native libraries and examples | Strong provider and web SDK coverage; good for tool servers and user-facing services |
| Asynchronous programming | Mature `async`/`await`; requires discipline around blocking calls and cancellation | Goroutines, channels, and context cancellation are strong for concurrent services | Mature event-loop and Promise model; blocking work and cancellation still require care |
| Event-driven systems | Mature broker clients and service libraries; dynamic runtime requires validation and typing discipline | Strong concurrency, networking, and operational simplicity | Natural fit for event-driven I/O and JSON-centric contracts |
| Ecosystem maturity | Very mature general and AI ecosystem | Very mature cloud, networking, and operations ecosystem | Very mature web, Node.js, and application ecosystem |
| Portability | CPython and wheels cover major platforms; native dependencies can complicate less common targets | Produces portable static binaries for supported targets with few runtime dependencies | Node.js is portable, but runtime and package installation remain deployment dependencies |
| Testing | Mature standard library and third-party test ecosystem | Strong built-in test tooling with less fixture abstraction | Mature test ecosystem, but several competing frameworks and conventions |
| Typing | Optional static typing is expressive but not runtime-enforced; third-party coverage varies | Static typing is built into the language and toolchain | Strong structural type system, with runtime validation still required at boundaries |
| Maintainability | Concise and readable with enforced typing, boundaries, and tooling; otherwise dynamic behavior can spread | Explicit, simple language and standard tooling; repetitive domain modeling is possible | Productive and strongly typed, but dependency and build-tool churn can add maintenance |
| Onboarding | Low syntax barrier; packaging and environment management need standardization | Small language and unified toolchain, but concurrency idioms require learning | Familiar to web developers; Node package and module conventions add choices |
| Long-term evolution | Strong ecosystem and gradual typing, but runtime performance and native-package compatibility require review | Stable toolchain and good operational characteristics; AI ecosystem gap may force adapters or second-language services | Strong ecosystem and types; Node lifecycle and frontend-oriented churn require governance |

### Python

Advantages:

- It has the strongest overlap with AI-agent, model-provider, data-processing,
  evaluation, and automation libraries.
- Its concise syntax and interactive ecosystem shorten experimentation and
  onboarding.
- `async`/`await`, mature messaging clients, and standard concurrency
  primitives are sufficient for the platform's event-driven I/O.
- The runtime is portable and broadly supported in container and CI
  environments.
- Optional typing can express platform ports and contracts when strict checking
  is enforced from the beginning.

Disadvantages:

- Static types are not enforced by the runtime and third-party packages may
  provide incomplete type information.
- CPU-bound concurrency is less straightforward than in Go and can require
  processes, native extensions, or isolated workers.
- Blocking libraries can accidentally stall an asynchronous service.
- Native wheels and interpreter-version support can lag for some AI
  dependencies.
- Python packaging is flexible enough to become inconsistent without a
  repository standard.

Trade-off and recommendation:

Python provides the most direct path to the AI ecosystem and is adequate for
the initial I/O-oriented orchestration workload. Its weaker runtime type and
concurrency guarantees are accepted only with strict static checking,
contract-boundary validation, isolation of blocking or CPU-bound work, and
repeatable dependency management. Python is recommended as the common runtime.

### Go

Advantages:

- Goroutines, channels, and `context` provide a clear and efficient concurrency
  model.
- Static binaries reduce runtime and container complexity.
- Static typing, fast compilation, formatting, testing, and module management
  are integrated into a stable toolchain.
- Go is well suited to brokers, gateways, infrastructure adapters, and
  long-running network services.

Disadvantages:

- The AI-agent and model experimentation ecosystem is smaller than Python's.
- Provider and agent-framework features may arrive later or require lower-level
  integrations.
- Data transformation and experimentation can require more code.
- Selecting Go could still lead to Python being introduced for AI-heavy Agents,
  defeating the initial single-ecosystem objective.

Why it is not selected:

Go's deployment and concurrency advantages are compelling, but the current
platform objective prioritizes AI-agent ecosystem access and a consistent
runtime for Orchestrator and Agent work. Go remains a possible future choice
for a separately justified component where measured operational needs outweigh
the cost of a second ecosystem.

### TypeScript

Advantages:

- It has a strong type system and a familiar `async`/`await` model.
- Node.js is well suited to event-driven I/O, JSON contracts, APIs, and tool
  integrations.
- AI-provider SDK coverage is strong and often close to Python's.
- The ecosystem is portable and has excellent editor support.

Disadvantages:

- Runtime contract validation remains necessary despite compile-time types.
- Node package, module, build, and test tooling offers many overlapping choices
  that require additional governance.
- The ecosystem is less complete than Python for model-local, data-science, and
  evaluation workloads.
- Dependency volume and release cadence can increase maintenance and
  supply-chain review costs.

Why it is not selected:

TypeScript is viable for user-facing or integration-heavy services, but it
does not provide enough advantage over Python for the first platform slice to
justify giving up Python's broader AI ecosystem. A future frontend or
independently justified integration component may select TypeScript through a
separate decision without changing platform contracts.

## Python Version

Python does not designate long-term-support releases. Each feature release
follows the Python project's maintenance and security lifecycle. At the time of
this proposal:

- Python 3.14 is in bugfix support and reaches end of life in October 2030;
- Python 3.13 is in bugfix support and reaches end of life in October 2029;
- Python 3.12 is in security-only support and reaches end of life in October
  2028; and
- Python 3.15 is a prerelease and is not eligible for the baseline.

### Recommendation

Use CPython 3.13 as the initial runtime, with the latest available 3.13 patch
release used in development, CI, and runtime images. Declare the initial
project range as `>=3.13,<3.14`.

Advantages:

- 3.13 is a maintained stable release with a multi-year security horizon.
- It provides newer language and runtime improvements without depending on a
  prerelease.
- It gives AI and infrastructure libraries more compatibility time than the
  newer 3.14 release.
- One minor version reduces local, CI, container, and dependency-resolution
  variability during the first slice.

Disadvantages and trade-offs:

- The project will not immediately use Python 3.14 improvements.
- The upper bound requires an intentional compatibility review before a minor
  upgrade.
- Some dependencies may still lack 3.13 wheels on a required architecture and
  must be validated before this ADR is accepted.

Python 3.14 is not selected as the initial minimum because the platform values
broad library and native-wheel compatibility over adopting the newest stable
minor immediately. Python 3.12 is not selected because it is already in
security-only support and would shorten the useful baseline. Older versions
add compatibility burden without a documented deployment requirement.

The minimum version must be reviewed when 3.13 enters security-only support,
when a required dependency ends 3.13 support, or when a newer version provides
a measured platform benefit.

## Dependency Management

### Comparison

| Option | Reproducibility and lockfile | Speed | Virtual environments | Developer experience | CI friendliness |
| --- | --- | --- | --- | --- | --- |
| uv | Cross-platform `uv.lock`; exact sync and locked/frozen modes | Very fast resolver, installer, and cache | Creates and synchronizes `.venv` automatically | One CLI for Python, dependencies, environments, tools, running, and building | Standalone cross-platform binary and deterministic commands |
| Poetry | Mature `poetry.lock` and deterministic installs | Adequate, generally slower than uv | Creates or uses isolated environments | Integrated and familiar workflow, but Poetry-specific concepts and configuration remain | Mature, but adds a larger bootstrap tool and separate command model |
| pip + requirements | Repeatability is possible with full pins and hashes; pip has no native project lock workflow | Adequate, with mature caching | Requires `venv` or another tool | Ubiquitous and transparent, but contributors must coordinate several commands and files | Universal, but reproducible compilation and synchronization need additional tooling |
| PDM | Mature `pdm.lock` with platform and Python targeting | Good | Supports managed virtual environments and other modes | Standards-oriented integrated project workflow | Suitable for CI with locked sync, but less common among contributors than pip or Poetry |

### Recommendation: uv

Use uv for Python installation selection, dependency resolution, dependency
groups, virtual environments, locked synchronization, tool execution, and
build invocation.

Advantages:

- A single fast CLI reduces setup steps and feedback time.
- `uv.lock` captures exact transitive resolutions across supported markers and
  is designed to be committed.
- `uv sync` and `uv run` keep the project environment aligned with metadata and
  support editable development installs.
- Locked modes allow CI to fail rather than silently rewrite dependency state.
- The standalone binary works on Windows and Linux without requiring an
  existing Python installation.

Disadvantages and trade-offs:

- `uv.lock` is uv-specific rather than a tool-neutral interchange format.
- uv is newer than pip and Poetry, so command and lock-format evolution require
  governance.
- Standardizing on uv creates a tooling dependency on one project even though
  application architecture remains vendor-neutral.

Poetry is rejected because its main benefits overlap with uv while its resolver
and environment workflow add more overhead for this repository. PDM is a
credible standards-oriented alternative but does not provide a current
project-specific advantage sufficient to choose a less familiar second
workflow. Plain pip and requirements files remain useful interoperability
mechanisms, but they require separate environment, compilation, and
synchronization conventions to achieve the same reproducibility.

The uv version used to create or update the lockfile must be pinned by the
documented developer and CI bootstrap process. Exported requirements or
`pylock.toml` files may be generated for a demonstrated interoperability need,
but they must not become competing dependency sources of truth.

## Project Metadata

The repository will use one root `pyproject.toml` as the source of truth for:

- standard project metadata and supported Python range;
- runtime dependencies;
- standardized development dependency groups;
- build-system declaration when packaging is introduced; and
- Ruff, mypy, and pytest configuration where those tools support it.

The initial project is one internal distribution with one committed `uv.lock`
at the repository root. The lockfile is generated, reviewed, and committed; it
must not be edited manually. Dependency changes update `pyproject.toml` and
`uv.lock` in the same change.

Development environments use an editable install so source changes are visible
without reinstalling. CI verification and runtime-image construction use a
locked environment; runtime artifacts use a non-editable install so they do not
depend on a mutable source checkout.

Advantages:

- Metadata, dependency groups, supported Python, and tool configuration remain
  discoverable in one standard file.
- One application lock produces repeatable developer, CI, and image inputs.
- Editable development preserves a short feedback loop without changing import
  behavior between source and tests.

Disadvantages and trade-offs:

- A single lockfile can grow as component-specific dependencies are added.
- One distribution may eventually be too coarse if components require
  independent release cycles or incompatible dependency sets.
- The exact PEP 517 build backend remains an implementation-time choice because
  this slice does not publish a distribution. It must be documented before the
  first package is built and must preserve this metadata and layout decision.

Multiple independent `requirements.txt` files, per-component lockfiles, and
manually managed editable paths are rejected for the initial slice because they
would allow environments to drift before separate release requirements exist.

## Code Formatting

### Ruff Formatter

Advantages:

- It shares one executable and configuration model with the selected linter.
- It is fast enough to run over the repository frequently in local and CI
  workflows.
- Its style is intentionally close to Black and minimizes discretionary
  formatting.

Disadvantages:

- It has known small deviations from Black.
- Using Ruff and Black interchangeably can produce formatting churn.
- Ruff's formatter has a shorter history than Black.

### Black

Advantages:

- It has a long history, a stable recognizable style, and broad editor and CI
  integration.
- Its intentionally limited configuration reduces style debate.

Disadvantages:

- It adds a second executable when Ruff is already selected for linting.
- It is slower than Ruff for frequent repository-wide checks.
- Formatter and linter configuration must be kept aligned.

### Recommendation

Use Ruff formatter as the only Python formatter. Do not run Black alongside it.
The reduced tool count and faster feedback outweigh Black's longer standalone
history for this new codebase. Pin Ruff through the development dependency
lock, configure it in `pyproject.toml`, and require check mode in review
automation when CI is introduced.

## Linting

### Comparison

| Tool | Advantages | Disadvantages | Outcome |
| --- | --- | --- | --- |
| Ruff | Fast; broad built-in rule coverage; import sorting and automatic fixes; shared configuration with formatter | Some Flake8 plugins or specialized Pylint checks may not have exact equivalents; rule promotion requires version pinning and review | Selected |
| Flake8 | Mature rule-code convention and extensive plugin ecosystem | Useful behavior is distributed across plugins; slower; formatting and import sorting require separate tools | Rejected because it increases plugin and tool coordination without a current coverage need |
| Pylint | Deep semantic checks and highly configurable scoring and policy | Slower, noisier on new code, and more expensive to tune; overlaps with Ruff and the type checker | Rejected as the baseline; a specific missing defect class could justify later evaluation |

### Recommendation

Use Ruff as the only baseline linter. Begin with a documented, conservative
stable rule set and add rule families deliberately. Automatic fixes must not be
applied blindly in CI; CI checks, while developers may apply reviewed safe
fixes locally.

This accepts less specialized analysis than a heavily customized Pylint or
Flake8 plugin installation in exchange for one fast, reproducible linter.
Missing coverage must be demonstrated before another overlapping linter is
added.

## Static Typing

### Pyright

Advantages:

- It is fast, standards-oriented, and supports strict checking.
- Its language server and VS Code integration provide strong interactive
  feedback.
- It has a command-line interface suitable for CI and can use
  `pyproject.toml`.

Disadvantages:

- The official command-line distribution requires Node.js; the Python package
  wrapper is community-maintained.
- Adding Node solely for type checking creates a second tool installation and
  version lifecycle outside `uv.lock`.
- Strict inference can expose many diagnostics in incompletely typed AI
  libraries.

### mypy

Advantages:

- It is mature, Python-native, and can be pinned with all development
  dependencies in `uv.lock`.
- Strict mode is configurable globally and by module.
- It has a large ecosystem of type stubs and framework plugins.
- Its CLI is straightforward to run identically on developer machines and in
  CI.

Disadvantages:

- Editor integration is less uniform and typically depends on an editor
  extension or language-server adapter.
- It can be slower than Pyright on a large codebase.
- Plugins and per-module exemptions can create maintenance cost or hide
  untyped boundaries if not governed.

### Recommendation

Use mypy in strict mode as the authoritative static type checker for
platform-owned Python source and maintained test-support code. New public
functions, ports, contracts, and configuration models must be typed. Narrow
per-module exceptions are permitted only for documented third-party boundaries;
global suppression of missing imports is not permitted.

mypy is selected over Pyright because keeping the authoritative checker in the
Python development lock produces a more reproducible single ecosystem without
a Node bootstrap. The trade-off is weaker out-of-the-box editor integration and
potentially slower checks. If repository scale makes mypy feedback materially
too slow, or editor inconsistency causes recurring defects, Pyright may be
reevaluated.

## Testing

### pytest

Advantages:

- Explicit reusable fixtures support controlled component and infrastructure
  dependencies.
- Parametrization expresses contract examples, state transitions, duplicate
  delivery, and failure cases without repetitive test classes.
- A mature plugin ecosystem can add narrowly justified capabilities.
- It can run existing `unittest`-style tests if migration is ever needed.

Disadvantages:

- Powerful fixtures can hide dependencies or create broad shared state.
- Uncontrolled plugin auto-discovery can make environments differ.
- It adds a development dependency beyond the standard library.

### unittest

Advantages:

- It ships with Python and introduces no third-party test runner dependency.
- Class-based setup and assertion APIs are stable and familiar.

Disadvantages:

- Fixtures and parametrization are more verbose for the platform's contract and
  workflow matrices.
- Shared setup often becomes inheritance-heavy as component scenarios grow.
- The extension ecosystem and failure ergonomics are less cohesive for the
  proposed layered suite.

### Recommendation

Use pytest as the test runner and primary test-authoring style. Prefer explicit,
narrow fixtures and direct assertions. Add plugins only for a documented test
requirement and pin them in the lockfile. The repository must not depend on
ambient, globally installed plugins.

pytest is selected because fixture composition and parametrization directly
support the existing test strategy's contract, workflow, integration, and
resilience cases. The extra dependency and fixture-governance cost are accepted
over the repetitive setup that `unittest` would require.

## Test Organization

This ADR selects the test runner; it does not redefine
[the platform test strategy](../../testing/README.md).

The first vertical slice retains these directories:

```text
tests/
├── unit/
├── contract/
├── component/
├── integration/
└── end-to-end/
```

- Unit tests remain isolated and fast.
- Contract tests validate API, event, manifest, configuration, and port
  contracts with versioned fixtures.
- Component tests exercise one module through its public boundary with
  controlled dependencies.
- Integration tests verify selected real adapters or collaborating boundaries.
- End-to-end tests remain few and validate complete outcomes through the local
  deployed slice.

The testing strategy's distinction between local and external-service tests
remains authoritative. pytest markers may identify execution requirements, but
markers must map to the documented categories rather than create a competing
taxonomy.

Advantages:

- The layout matches the vertical-slice proposal and keeps test intent visible.
- One runner permits shared low-level utilities without merging test levels.

Disadvantages and trade-offs:

- Some fixtures may be shared across levels, so ownership must remain explicit.
- Directory-level separation alone does not enforce isolation; review and
  configuration must prevent external tests from running accidentally.

Co-locating all tests in one undifferentiated directory is rejected because it
would obscure execution cost and boundary ownership. Creating a separate test
framework per level is rejected because it would duplicate tooling and
onboarding.

## Configuration

Configuration follows these standards:

- Environment variables are the authoritative runtime override mechanism.
- Names use one documented platform prefix and component-scoped keys.
- A local `.env` file may be loaded only as an explicit development
  convenience.
- `.env` is ignored by Git; a committed `.env.example` may contain names and
  nonsecret examples, never working credentials.
- Every component validates configuration at startup and fails with a
  sanitized, actionable error when required or invalid values are present.
- Configuration is parsed into typed, immutable models before it reaches domain
  logic.
- Defaults are safe, documented, and must not silently enable external access
  or destructive behavior.
- Secrets remain separate from normal configuration. They are injected at
  runtime through an authorized mechanism and are never committed, copied into
  images, or included in logs and errors.

Advantages:

- Environment variables work consistently in shells, containers, Unraid, and
  common CI systems.
- Optional `.env` support lowers local setup friction.
- Central validation prevents loosely typed strings from spreading into
  modules.

Disadvantages and trade-offs:

- Environment variables are string-based and require explicit parsing.
- Large configurations can become difficult to inspect.
- `.env` convenience creates secret-commit risk if ignore rules or contributor
  discipline fail.

Repository-specific configuration files with embedded secrets are rejected.
A concrete configuration-validation library and future secrets provider are
not selected here; either may be chosen behind the platform configuration
boundary without changing these rules.

## Logging

Platform code uses Python's standard `logging` API behind the shared logging
module proposed by the vertical slice.

The runtime logging configuration must:

- emit structured JSON to standard output for deployed components;
- preserve readable local output as an explicit development option;
- attach correlation, causation, workflow, task, attempt, message, component,
  and contract fields when available;
- propagate correlation context safely across asynchronous tasks and restore it
  from validated message envelopes;
- use stable event names and sanitized error codes;
- exclude secrets and full workflow text; and
- keep formatter and transport details outside domain modules.

Advantages:

- Standard-library logging avoids binding domain code to a logging vendor.
- JSON records are machine-readable while remaining backend-neutral.
- correlation fields satisfy the vertical slice's traceability requirements
  without selecting tracing or monitoring infrastructure.

Disadvantages and trade-offs:

- The standard library does not define a JSON schema or context propagation
  policy, so the shared module must do so.
- Context across asynchronous and thread boundaries requires tests.
- Structured records are less convenient to read directly without local
  formatting or tooling.

Direct use of a monitoring-vendor SDK throughout platform modules is rejected
because it would couple code to an unselected backend. This ADR does not choose
a JSON logging library, collector, metrics backend, or monitoring service.

## Packaging and Module Organization

Use a `src` layout with the import namespace `ai_platform`.

The initial logical package structure is:

```text
src/
└── ai_platform/
    ├── api/
    ├── orchestrator/
    │   └── capability_registry/
    ├── agents/
    │   └── test_agent/
    ├── contracts/
    ├── ports/
    │   ├── event_bus/
    │   └── persistence/
    ├── adapters/
    │   ├── event_bus/
    │   └── persistence/
    └── shared/
        ├── configuration/
        └── logging/
```

This preserves the logical modules in the vertical-slice proposal. It changes
the proposal's placeholder `src/platform/` package name to `src/ai_platform/`
because `platform` is already a Python standard-library module and must not be
shadowed. Hyphenated logical names use Python `snake_case` package names.

Use one regular top-level package rather than an implicit namespace package.
Module boundaries are expressed through public interfaces and imports, not
through packaging tricks. Domain logic must not import concrete transport,
persistence, provider, or deployment implementations.

Advantages:

- `src` layout prevents tests from succeeding only because the repository root
  happens to be on the import path.
- `ai_platform` is explicit and avoids a standard-library name collision.
- The package tree directly reflects the current logical architecture.
- One package and editable install keep the first slice simple.

Disadvantages and trade-offs:

- The concrete package path differs from the placeholder spelling in the
  vertical-slice tree and that document must be updated when implementation
  begins.
- A single distribution does not independently version every module.
- Packaging internal deployable components together can increase image
  contents unless build inputs are controlled.

Flat source layout is rejected because import behavior can differ between a
checkout and an installed artifact. Multiple namespace distributions are
rejected until independent release, ownership, or dependency requirements
justify their additional versioning and build complexity.

## CI Friendliness

The same platform-neutral commands must run locally, in GitHub Actions, and in
Azure DevOps:

```text
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
```

These are proposed commands, not claims that CI is currently configured.
Repository configuration, not CI-specific task behavior, defines tool policy.

The future CI bootstrap must pin uv, select the accepted Python 3.13 patch
policy, and use the committed lockfile without updating it. Caching may improve
speed but must not be required for correctness. Checks must not depend on
GitHub-only actions, Azure-only tasks, globally installed Python packages, or
developer-machine state.

Advantages:

- Local and CI behavior uses the same entry points and locked dependencies.
- Both CI products can invoke the commands from ordinary shell steps.
- CI configuration remains replaceable.

Disadvantages and trade-offs:

- Each CI environment still needs a trustworthy uv bootstrap.
- Cross-platform checks may reveal native dependency differences.
- A single full check can become slow as integration and end-to-end tests grow;
  later job partitioning must preserve the same commands and categories.

CI-vendor-specific quality implementations are rejected because they would make
local reproduction and migration harder. This ADR does not create a pipeline
or claim that any check is currently enforced.

## Decision

If accepted, all initial platform-owned runtime components use this coherent
tooling stack:

- **Runtime language:** Python
- **Runtime:** CPython 3.13, latest approved patch, with
  `requires-python = ">=3.13,<3.14"`
- **Dependency and environment management:** uv
- **Metadata:** one root `pyproject.toml`
- **Dependency lock:** one committed `uv.lock`
- **Development installation:** editable
- **CI and runtime installation:** locked; runtime artifacts are non-editable
- **Source layout:** `src/ai_platform/`
- **Import namespace:** one regular `ai_platform` package
- **Formatting:** Ruff formatter
- **Linting:** Ruff
- **Static typing:** mypy strict mode
- **Testing:** pytest
- **Test layout:** existing unit, contract, component, integration, and
  end-to-end directories
- **Configuration:** validated environment variables with optional local
  `.env` support and strict secret separation
- **Logging:** standard Python logging API with platform-owned structured JSON
  and correlation context
- **CI interface:** the same uv-managed commands in local development, GitHub
  Actions, and Azure DevOps

This decision standardizes implementation tooling, not platform contracts.
Components continue to communicate through the vendor-neutral boundaries
defined by ADR-0001 and ADR-0002.

## Consequences

### Positive Consequences

- Contributors learn and operate one runtime, package manager, formatter,
  linter, type checker, and test runner.
- Python provides direct access to the broad AI-agent ecosystem.
- A committed lockfile makes dependency resolution reviewable and repeatable.
- Fast formatting and linting encourage frequent local checks.
- Strict typing and the `src` layout make module boundaries and packaging
  mistakes visible earlier.
- Test tooling supports the repository's existing layered strategy.
- Environment variables, standard logging, and portable commands work across
  local, container, Unraid, GitHub Actions, and Azure DevOps contexts.

### Negative Consequences

- Python provides weaker compile-time and CPU-concurrency guarantees than Go.
- Strict typing around untyped AI packages may require adapters and maintained
  stubs.
- uv and its lock format become repository tooling dependencies.
- mypy provides less uniform editor feedback than Pyright.
- A single package and lockfile may become coarse as components evolve.
- Structured logging and correlation propagation require a platform-owned
  implementation and tests.

### Migration Impact

There is no implementation to migrate. When this ADR becomes Accepted, initial
scaffolding must:

- create `pyproject.toml` and `uv.lock`;
- use `src/ai_platform/` rather than the vertical slice's placeholder
  `src/platform/`;
- create only the modules required by the active implementation phase;
- configure Ruff, mypy, and pytest in `pyproject.toml`;
- update the vertical-slice repository tree to the accepted package spelling;
  and
- document reproducible setup and check commands.

If implementation appears before acceptance, it must not be treated as evidence
that its tooling has been approved.

### Developer Impact

- Developers install or bootstrap uv and use it to create and synchronize the
  project environment.
- Code is formatted and linted by Ruff, checked by mypy strict mode, and tested
  with pytest before review.
- New platform-owned code includes type annotations and explicit boundary
  validation.
- Local `.env` files remain optional, ignored, and nonauthoritative.
- Contributors do not need Go, Node.js, Poetry, PDM, or globally installed
  Python quality tools for the initial platform.

### CI Impact

- Future pipelines pin uv and invoke the same locked commands used locally.
- GitHub Actions and Azure DevOps require no platform-specific quality
  implementation.
- Python and dependency caches may improve performance but cannot affect
  correctness.
- External-service tests remain opt-in according to the existing test strategy;
  this ADR does not invent CI gates or claim a pipeline exists.

### Future Review Triggers

Review or supersede this decision when:

- Python 3.13 enters security-only support or approaches end of life;
- a required library or deployment target cannot support the selected runtime;
- Python CPU or concurrency limitations are demonstrated through measurement;
- a component requires an independent release cadence or incompatible
  dependency graph;
- `uv.lock` portability or uv maintenance creates recurring failures;
- mypy performance or editor inconsistency materially reduces delivery quality;
- Ruff lacks a required analysis that another tool can demonstrably provide;
- a frontend or specialized service justifies a second language;
- CI portability requirements change; or
- platform contracts begin depending on Python-specific representations.

## Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| A required AI or native library does not support Python 3.13 on a deployment architecture | Validate required libraries and wheels before acceptance; isolate optional native dependencies; revisit the minimum version if evidence requires it |
| Blocking or CPU-bound work stalls an asynchronous service | Keep blocking work behind adapters, test timeouts and cancellation, and use isolated execution when measurements justify it |
| Dynamic types leak through provider SDKs | Validate at trust boundaries, use typed adapters, maintain narrow stubs, and prohibit global missing-import suppression |
| uv or its lock format changes incompatibly | Pin uv, review lockfile changes, document upgrades, and retain standards-based `pyproject.toml` metadata |
| One lockfile couples unrelated components | Use dependency groups initially; split only after independent deployment or conflict evidence is documented |
| Strict mypy creates excessive exceptions | Start strict on greenfield code, keep exceptions narrow and documented, and track removal |
| Ruff rule upgrades create unexpected churn | Pin Ruff and review rule-set or version changes separately from behavior changes |
| `.env` files lead to credential commits | Keep ignore rules, provide nonsecret examples, review secret handling, and follow `SECURITY.md` |
| Structured logs leak workflow text or credentials | Centralize formatting and redaction, whitelist fields, and test sensitive-data paths |
| Python-specific models leak into contracts | Keep contracts serialized and versioned at ports; test them independently of Python classes |

## Assumptions

- ADR-0001 and ADR-0002 remain Accepted and govern module and communication
  boundaries.
- Initial workloads are dominated by orchestration, network, persistence, and
  AI-provider I/O rather than sustained CPU-bound computation.
- No current component has a demonstrated requirement for a second runtime.
- The first slice remains an internal application rather than a public Python
  library.
- Required AI and infrastructure dependencies will be checked for Python 3.13
  compatibility before this ADR is accepted.
- Developers and future CI workers can install the pinned uv binary.
- Docker remains the accepted deployment packaging boundary, but this ADR does
  not choose image topology or local orchestration.

## Open Questions

1. Do all dependencies shortlisted by ADR-0004 through ADR-0006 publish
   compatible Python 3.13 artifacts for every required deployment architecture?
2. Which standards-compliant PEP 517 build backend should create the internal
   distribution when packaging is introduced?
3. What exact policy approves new Python 3.13 patch releases and pins runtime
   image digests?
4. What lockfile update cadence and dependency-upgrade review process should
   contributors follow?
5. Which minimal Ruff rule families should be enabled at first acceptance?
6. Which test-support modules, in addition to all production source, must pass
   mypy strict mode from the first implementation phase?
7. Which configuration and JSON-formatting libraries, if any, are necessary
   after the first contracts are defined?

## Alternatives Considered

The detailed evaluations above considered these coherent alternatives:

### Go Toolchain

Use Go for all platform services with its standard module, formatting, testing,
and static analysis tools. This would simplify binaries and concurrency but was
not selected because AI-agent ecosystem access would be reduced and could force
a second Python ecosystem.

### TypeScript Toolchain

Use TypeScript and Node.js for all components. This would provide strong types,
editor support, and event-driven I/O, but was not selected because Python
provides broader AI, evaluation, and data tooling with less risk of a later
second runtime.

### Python with Poetry, Black, Flake8, Pyright, and unittest

Use mature independent tools for each concern. This was not selected because it
adds overlapping configuration and, for the official Pyright CLI, a Node.js
tool lifecycle. The selected uv, Ruff, mypy, and pytest stack provides the
required capabilities with fewer installation and coordination paths.

### Tool Choice Per Component

Allow every component to select its own language and quality tools. This would
optimize locally but was rejected because no current component requirement
justifies the multiplied onboarding, CI, dependency, container, and maintenance
cost.

## Explicitly Out of Scope

This ADR does not decide:

- Kafka or any other Event Bus implementation;
- persistence technology or workflow persistence design;
- Docker Compose or local container topology;
- API protocol or representation;
- LangGraph or another orchestration framework;
- AI Router design or implementation;
- a logging, monitoring, tracing, or metrics backend;
- a secrets-provider implementation;
- an AI model or external provider; or
- concrete runtime libraries whose need depends on ADR-0004 through ADR-0006.

## Acceptance Checklist

- [ ] The runtime-language comparison reflects the expected platform workload.
- [ ] Python 3.13 compatibility is verified for required libraries and target
      architectures.
- [ ] The absence of a Python LTS designation and the runtime review triggers
      are understood.
- [ ] The project accepts uv and `uv.lock` as tooling dependencies and the
      application dependency source of truth.
- [ ] A pinned uv bootstrap and upgrade policy is agreed.
- [ ] The root `pyproject.toml`, one-lockfile, and editable-development strategy
      are approved.
- [ ] A PEP 517 build backend is selected or explicitly deferred with an owner
      and decision point.
- [ ] `src/ai_platform/` is accepted as the concrete spelling of the vertical
      slice's logical platform package.
- [ ] Ruff formatter is accepted as the only formatter.
- [ ] Ruff is accepted as the only baseline linter and its initial rule set is
      agreed.
- [ ] mypy strict mode is accepted as the authoritative type check and its
      checked paths are agreed.
- [ ] pytest and the existing layered test directories are accepted without
      changing the test strategy.
- [ ] Environment-variable, `.env`, validation, and secret-separation rules
      align with `SECURITY.md`.
- [ ] Standard Python logging, structured JSON, correlation propagation, and
      redaction requirements are approved without selecting a backend.
- [ ] The proposed commands are reproducible on Windows and Linux.
- [ ] GitHub Actions and Azure DevOps can invoke the same commands without
      platform-specific quality dependencies.
- [ ] Every open question has an owner and is either resolved or explicitly
      accepted as a bounded implementation detail.
- [ ] Reviewers confirm that no out-of-scope infrastructure or platform
      technology was selected.

## Related Decisions

- [ADR-0001: Core Design Principles](ADR-0001-core-design-principles.md)
- [ADR-0002: Platform Communication and State](ADR-0002-platform-communication-and-state.md)

## References

- [Vertical Slice 01](../../implementation/vertical-slice-01.md)
- [Platform test strategy](../../testing/README.md)
- [Repository security policy](../../../SECURITY.md)
- [Repository agent guidance](../../../AGENTS.md)
- [Python version status](https://devguide.python.org/versions/)
- [Python logging cookbook](https://docs.python.org/3/howto/logging-cookbook.html)
- [Python packaging guide](https://packaging.python.org/)
- [uv project documentation](https://docs.astral.sh/uv/concepts/projects/)
- [Poetry documentation](https://python-poetry.org/docs/)
- [pip repeatable installs](https://pip.pypa.io/en/stable/topics/repeatable-installs/)
- [PDM lockfile documentation](https://pdm-project.org/latest/usage/lockfile/)
- [Ruff formatter](https://docs.astral.sh/ruff/formatter/)
- [Ruff linter](https://docs.astral.sh/ruff/linter/)
- [Pyright documentation](https://microsoft.github.io/pyright/)
- [mypy documentation](https://mypy.readthedocs.io/)
- [pytest documentation](https://docs.pytest.org/)
