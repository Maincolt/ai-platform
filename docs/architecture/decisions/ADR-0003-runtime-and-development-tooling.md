# ADR-0003: Runtime and Development Tooling

- **Status:** Accepted
- **Date:** 2026-07-26
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

At the time this ADR was proposed, the repository contained no implementation
code or accepted runtime tooling, so every technology in this ADR was evaluated
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

Use CPython 3.14 as the initial runtime, with the latest approved 3.14 patch
release used in development, CI, and runtime images. Declare the initial
project range as `>=3.14,<3.15`.

### Ecosystem Compatibility Review

The current stable releases of the expected library categories were reviewed
through their published project metadata and release artifacts:

| Category | Evidence of Python 3.14 support |
| --- | --- |
| API and validation | FastAPI declares Python 3.14 support. Pydantic v2 declares support, and `pydantic-core` publishes CPython 3.14 wheels for mainstream Windows, macOS, glibc Linux, and musl Linux targets. |
| Kafka clients | `confluent-kafka` publishes CPython 3.14 wheels for mainstream Windows, macOS, and Linux targets. `aiokafka` declares Python 3.14 support and publishes CPython 3.14 wheels. This compatibility check does not select a Kafka client or Event Bus. |
| Development tools | pytest, Ruff, mypy, and uv declare Python 3.14 compatibility or publish compatible artifacts. |
| Common AI libraries | The OpenAI, Anthropic, and LangChain Python packages declare Python 3.14 support and publish universal Python wheels. This compatibility check does not select an AI provider or framework. |

The expected platform ecosystem no longer shows a significant Python 3.14
compatibility gap. A later ADR may select a library not reviewed here; that
library and all required optional extras must still be validated against the
target runtime and deployment architecture before implementation.

Advantages:

- 3.14 is a maintained stable release with bugfix support and the longest
  security horizon among currently released Python versions.
- Expected API, validation, Kafka-client, testing, tooling, and AI libraries
  now publish explicit support or compatible artifacts.
- Starting on 3.14 avoids an early runtime migration after implementation
  begins.
- One minor version reduces local, CI, container, and dependency-resolution
  variability during the first slice.

Disadvantages and trade-offs:

- The upper bound requires an intentional compatibility review before a minor
  upgrade.
- A later-selected native dependency or optional extra may have narrower wheel
  coverage than the libraries reviewed here.
- Unraid hosts or container base images on less common architectures still
  require artifact validation.

Python 3.13 remains supported, but it is not selected because the concrete
compatibility reason for preferring it has expired and it provides a shorter
maintenance horizon. Python 3.12 is not selected because it is already in
security-only support. Older versions add compatibility burden without a
documented deployment requirement, and Python 3.15 remains a prerelease.

The minimum version must be reviewed when 3.14 enters security-only support,
when a required dependency ends 3.14 support, or when a newer version provides
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
groups, virtual environments, locked synchronization, Python tool execution,
and build invocation. The selected BasedPyright distribution is a
development-only Python package managed through the same uv dependency group
and lockfile, as described in the static typing decision.

Advantages:

- One fast CLI covers the Python runtime, application dependencies, environment,
  build, and most development tools.
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
- BasedPyright packages a Node-based checker behind a Python distribution, so
  its release and platform-wheel availability remain additional dependency
  considerations even though contributors do not manage Node or npm directly.

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

BasedPyright is declared in the standardized development dependency group and
resolved in `uv.lock`. No root `package.json`, `package-lock.json`, npm
bootstrap, or separately managed Node.js runtime is introduced solely for
static typing.

## Project Metadata

The repository will use one root `pyproject.toml` as the source of truth for:

- standard project metadata and supported Python range;
- runtime dependencies;
- standardized development dependency groups;
- the Hatchling build-system declaration; and
- Ruff, BasedPyright, and pytest configuration where those tools support it.

The initial project is one internal distribution with one committed `uv.lock`
at the repository root. The lockfile is generated, reviewed, and committed; it
must not be edited manually. Dependency changes update `pyproject.toml` and
`uv.lock` in the same change.

The BasedPyright development dependency and its transitive dependencies are
resolved in the same committed `uv.lock`. Its bundled Pyright and Node
implementation details do not create a second repository package manifest or
lockfile.

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
- BasedPyright is a forked distribution rather than Microsoft's direct Pyright
  package, so its release maintenance and upstream synchronization must be
  reviewed during upgrades.

Multiple independent `requirements.txt` files, per-component lockfiles, and
manually managed editable paths are rejected for the initial slice because they
would allow environments to drift before separate release requirements exist.

### Build Backend Evaluation

| Backend | Advantages | Disadvantages |
| --- | --- | --- |
| Hatchling | Standards-compliant PEP 517 and PEP 660 support; native `pyproject.toml` configuration; direct support for `src` packages, editable installs, reproducible builds, file selection, and future build hooks; works with uv as the build frontend | Adds a build dependency; less appropriate than Setuptools for projects that require traditional extension-module machinery; flexible hooks still require governance |
| Setuptools | Long ecosystem history; broad compatibility; mature package discovery, extension-module, and legacy-project support; supports modern `pyproject.toml` and editable installs | Larger configuration and behavior surface; legacy `setup.py` and `setup.cfg` paths can create competing conventions; automatic discovery and extensibility add complexity the pure-Python internal platform does not currently need |

### Build Backend Recommendation

Use Hatchling as the PEP 517 build backend and declare
`build-backend = "hatchling.build"` in `pyproject.toml`. Use its standard
PEP 660 editable-install behavior for development and build wheels or source
distributions through uv.

Hatchling aligns with the selected `src/ai_platform/` layout, keeps packaging
configuration in `pyproject.toml`, and provides more future packaging
flexibility than the initial pure-Python platform requires without inheriting
Setuptools' legacy configuration surfaces. Setuptools is not selected because
its extension and compatibility strengths do not address a current requirement.

The Hatchling build requirement must use a reviewed version range in
`[build-system]`. A future need for compiled extension modules or unsupported
build behavior is a review trigger, not a reason to leave the initial backend
undecided.

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

### Comparison

| Criterion | Pyright | mypy |
| --- | --- | --- |
| Type inference quality | Strong control-flow narrowing and inference for unannotated expressions; strict collection inference reduces propagation of `Any` | Mature gradual typing with predictable annotation-driven behavior; inference is strong but generally less aggressive in interactive use |
| Strictness | A documented `strict` mode enables broad unknown-type, missing-stub, and boundary diagnostics; individual rules remain configurable | `strict` mode is mature and highly configurable, with granular error codes and per-module overrides |
| Diagnostics | Fast, precise diagnostics are available continuously through the language server and from the CLI; JSON output supports machine consumers | Stable CLI diagnostics and error codes are well suited to CI, but feedback is usually batch-oriented without another editor integration |
| Editor experience | Pyright-family analysis provides completion, navigation, narrowing, and immediate diagnostics through Pylance, Pyright, or a compatible language-server extension | Requires a separate mypy editor extension or daemon integration alongside the normal VS Code language server, which can produce delayed or duplicated feedback |
| AI-first workflow | Immediate diagnostics and inferred types improve the feedback available while GitHub Copilot, Codex, GPT-based tools, and developers create or revise code; agents can also consume the authoritative CLI result | AI tools can run and interpret the CLI, but receive less continuous editor feedback and may encounter differences between editor inference and CI checks |
| CI integration | The selected BasedPyright CLI supports deterministic noninteractive checks and runs from the uv-managed environment; the official distribution would require separately managed Node.js and npm | Runs directly inside the uv-managed Python environment with no second runtime |
| Performance | Designed for high performance on large Python codebases and responsive language-server use | Incremental caches and the daemon improve performance, but cold and repository-wide checks are generally slower |
| Maintenance | One configuration can drive CLI and editor analysis; the selected BasedPyright distribution can use the workspace-pinned version, but adds fork-synchronization risk | One Python lockfile and mature plugins simplify installation; plugins and checker-specific exceptions can accumulate |
| Ecosystem maturity | Mature, standards-oriented checker with first-class VS Code/Pylance usage and support in other editors | Long-established checker with a large stub and plugin ecosystem |

### Recommendation

Use Pyright-family analysis in strict mode as the authoritative static type
check for platform-owned Python source and maintained test-support code. Use
the BasedPyright distribution and store its configuration under
`[tool.basedpyright]` in `pyproject.toml`. New public functions, ports,
contracts, and configuration models must be typed. Narrow exclusions are
permitted only for documented third-party boundaries; global suppression of
missing imports or unknown types is not permitted.

### Pyright Installation Strategy Evaluation

| Criterion | BasedPyright through uv | Python wrapper for Pyright through uv | Official Pyright through npm |
| --- | --- | --- | --- |
| Repository simplicity | Uses the existing development dependency group and `uv.lock`; no Node manifest or npm commands | Uses the Python dependency group, but wraps a separately installed or cached Node and npm execution path | Requires root `package.json`, `package-lock.json`, npm commands, and a supported Node runtime |
| Reproducibility | Pins the checker, its bundled Pyright payload, and Python-visible transitive dependencies in `uv.lock`; the editor can load the workspace package | Pins the wrapper and its targeted Pyright version, but installation or cache behavior for Node and the npm package adds another layer to diagnose | Pins Microsoft's package and transitive npm dependencies directly in `package-lock.json`; Node itself still needs a separate version policy |
| Long-term maintenance | Normal uv upgrades and one lockfile; accepts a fork-maintenance and upstream-synchronization dependency | Tracks upstream Pyright closely, but depends on a community wrapper plus its Node discovery, download, npm, and cache behavior | Uses Microsoft's direct distribution, but requires ongoing Node, npm, manifest, lockfile, and supply-chain maintenance |
| Developer onboarding | `uv sync --locked` installs the development tool; no separately managed Node or npm prerequisite | Appears Python-native, but failures can expose Node, npm, cache, and wrapper-specific environment controls | Requires contributors to install and understand Node and npm in addition to uv |
| CI complexity | Runs with `uv run basedpyright` after the normal locked sync | Runs from uv, but deferred Node or npm setup can add cache and network failure modes unless separately controlled | Requires both `uv sync --locked` and `npm ci`, plus a pinned Node bootstrap |
| Dependency management | Keeps application and development dependencies in the selected primary Python toolchain | Keeps the wrapper in uv while obscuring part of the executable acquisition behind the wrapper | Makes the second package manager explicit and reproducible, but splits development tooling across two dependency graphs |
| VS Code integration | The BasedPyright extension can discover the workspace package so editor and CI use the pinned version; Pylance-exclusive features may require a documented hybrid setup | Works with Pyright/Pylance configuration, but the independently updated Pylance engine can differ from the pinned CLI | Provides the direct upstream CLI and familiar Pylance path, but does not by itself keep the Pylance engine aligned with CI |
| Single primary Python toolchain | Strongest alignment: uv installs and invokes the checker | Partial alignment: uv installs the wrapper, but the wrapper still manages Node/npm behavior | Weakest alignment: Node and npm become explicit development prerequisites |

Use BasedPyright as a development dependency managed and locked entirely
through uv. The package bundles the Pyright payload and its Node implementation
dependency, so Node remains an internal implementation detail rather than a
separately managed repository toolchain. The pinned `uv.lock` resolution and
`uv run basedpyright` command are authoritative in local checks and CI.

VS Code uses the BasedPyright extension configured to discover the package in
the workspace environment. This aligns interactive diagnostics with the
locked CLI version. Pylance is not the default type-checking path because its
independently bundled engine can diverge; if a Pylance-exclusive language
feature becomes necessary, Pylance type checking must be disabled so duplicate
diagnostics are not produced.

Pyright-family analysis is selected because inference quality, diagnostic
speed, and direct alignment with the VS Code experience materially improve the
feedback loop for developers and AI coding tools. Codex, GPT-based tools, and
GitHub Copilot do not require Pyright, but they benefit from fast, local,
consistent diagnostics during generation and review.

mypy remains a mature, reproducible, Python-native alternative and would be
preferable if avoiding any Node-based implementation, including one packaged
behind a Python distribution, were the dominant constraint. It is not selected
because its installation simplicity does not compensate for the separate and
less immediate editor-checking path.

The community Python wrapper for Pyright is not selected because it still
discovers or downloads Node and installs or caches the npm package behind the
Python entry point. Although that preserves the direct upstream checker and can
be pinned through uv, the hidden bootstrap and cache behavior is less
transparent and less hermetic than installing a complete BasedPyright
distribution through the normal locked sync.

The official npm distribution is not selected because direct Microsoft
provenance does not provide enough additional architectural value to justify a
second package manager, lockfile, runtime bootstrap, and CI installation path
for one development tool. It also does not solve editor-to-CI version drift
when Pylance bundles a different engine. BasedPyright accepts a fork dependency
in exchange for lower repository and operational complexity; its upstream
Pyright base must be verified during each upgrade.

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
uv run basedpyright
uv run pytest
```

These are proposed commands, not claims that CI is currently configured.
Repository configuration, not CI-specific task behavior, defines tool policy.

The future CI bootstrap must pin uv, select the accepted Python 3.14 patch
policy, and use the committed `uv.lock` without updating it. Caching may improve
speed but must not be required for correctness. Checks must not depend on
GitHub-only actions, Azure-only tasks, globally installed Python packages, or
developer-machine state.

Advantages:

- Local and CI behavior uses the same entry points and locked dependencies.
- Both CI products can invoke the commands from ordinary shell steps.
- CI configuration remains replaceable.

Disadvantages and trade-offs:

- Each CI environment still needs a trustworthy uv bootstrap.
- BasedPyright increases the size of the Python development dependency set
  because it packages the checker and its implementation runtime.
- Cross-platform checks may reveal native dependency differences.
- A single full check can become slow as integration and end-to-end tests grow;
  later job partitioning must preserve the same commands and categories.

CI-vendor-specific quality implementations are rejected because they would make
local reproduction and migration harder. This ADR does not create a pipeline
or claim that any check is currently enforced.

## Decision

All initial platform-owned runtime components use this coherent tooling stack:

- **Runtime language:** Python
- **Runtime:** CPython 3.14, latest approved patch, with
  `requires-python = ">=3.14,<3.15"`
- **Dependency and environment management:** uv
- **Metadata:** one root `pyproject.toml`
- **Build backend:** Hatchling
- **Python dependency lock:** one committed `uv.lock`
- **Type-checker lock:** BasedPyright in the committed `uv.lock`
- **Development installation:** editable
- **CI and runtime installation:** locked; runtime artifacts are non-editable
- **Source layout:** `src/ai_platform/`
- **Import namespace:** one regular `ai_platform` package
- **Formatting:** Ruff formatter
- **Linting:** Ruff
- **Static typing:** Pyright-family strict mode through the uv-managed
  BasedPyright distribution; VS Code uses the workspace-pinned checker
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

- Contributors learn and operate one primary Python runtime and dependency
  toolchain for application and development dependencies.
- Python provides direct access to the broad AI-agent ecosystem.
- One committed lockfile makes Python and type-checker dependency resolution
  reviewable and repeatable.
- Fast formatting and linting encourage frequent local checks.
- Fast Pyright diagnostics, strict typing, Hatchling, and the `src` layout make
  module boundaries and packaging mistakes visible earlier.
- Test tooling supports the repository's existing layered strategy.
- Environment variables, standard logging, and portable commands work across
  local, container, Unraid, GitHub Actions, and Azure DevOps contexts.

### Negative Consequences

- Python provides weaker compile-time and CPU-concurrency guarantees than Go.
- Strict typing around untyped AI packages may require adapters and maintained
  stubs.
- uv and its lock format become repository tooling dependencies.
- BasedPyright introduces reliance on a community-maintained fork and its
  synchronization with upstream Pyright.
- The BasedPyright VS Code extension may not provide every Pylance-exclusive
  language feature.
- Hatchling is another build dependency and would need reevaluation for native
  extension modules it cannot support directly.
- A single package and lockfile may become coarse as components evolve.
- Structured logging and correlation propagation require a platform-owned
  implementation and tests.

### Migration Impact

There is no implementation to migrate. Acceptance of this ADR requires initial
scaffolding to:

- create `pyproject.toml` with Hatchling as its build backend and create
  `uv.lock`;
- include BasedPyright in the standardized development dependency group and
  resolve it in `uv.lock`;
- use `src/ai_platform/` rather than the vertical slice's placeholder
  `src/platform/`;
- create only the modules required by the active implementation phase;
- configure Ruff, BasedPyright strict mode, and pytest in `pyproject.toml`;
- verify Hatchling editable and non-editable builds through uv;
- update the vertical-slice repository tree to the accepted package spelling;
  and
- document reproducible setup and check commands.

If implementation appears before acceptance, it must not be treated as evidence
that its tooling has been approved.

### Developer Impact

- Developers install or bootstrap uv, then use the committed `uv.lock`.
- Code is formatted and linted by Ruff, checked by BasedPyright in strict mode,
  and tested with pytest before review.
- New platform-owned code includes type annotations and explicit boundary
  validation.
- Local `.env` files remain optional, ignored, and nonauthoritative.
- Contributors do not need Go, Poetry, PDM, globally installed Python quality
  tools, Node.js, or npm for the initial platform.

### CI Impact

- Future pipelines pin uv, provide the supported Python runtime, and invoke the
  same locked commands used locally.
- GitHub Actions and Azure DevOps require no platform-specific quality
  implementation.
- Python and dependency caches may improve performance but cannot affect
  correctness.
- External-service tests remain opt-in according to the existing test strategy;
  this ADR does not invent CI gates or claim a pipeline exists.

### Future Review Triggers

Review or supersede this decision when:

- Python 3.14 enters security-only support or approaches end of life;
- a required library or deployment target cannot support the selected runtime;
- Python CPU or concurrency limitations are demonstrated through measurement;
- a component requires an independent release cadence or incompatible
  dependency graph;
- `uv.lock` portability or uv maintenance creates recurring failures;
- BasedPyright no longer tracks upstream Pyright promptly, its maintenance
  becomes uncertain, or its VS Code integration materially reduces delivery
  quality;
- Hatchling cannot support a required packaging behavior or native extension;
- Ruff lacks a required analysis that another tool can demonstrably provide;
- a frontend or specialized service justifies a second language;
- CI portability requirements change; or
- platform contracts begin depending on Python-specific representations.

## Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| A later-selected AI or native library does not support Python 3.14 on a deployment architecture | Validate selected libraries, optional extras, and wheels before implementation; isolate optional native dependencies; revisit the runtime if evidence requires it |
| Blocking or CPU-bound work stalls an asynchronous service | Keep blocking work behind adapters, test timeouts and cancellation, and use isolated execution when measurements justify it |
| Dynamic types leak through provider SDKs | Validate at trust boundaries, use typed adapters, maintain narrow stubs, and prohibit global missing-import suppression |
| uv or its lock format changes incompatibly | Pin uv, review lockfile changes, document upgrades, and retain standards-based `pyproject.toml` metadata |
| One lockfile couples unrelated components | Use dependency groups initially; split only after independent deployment or conflict evidence is documented |
| Strict Pyright creates excessive unknown-type diagnostics around AI libraries | Start strict on greenfield code, isolate untyped SDKs behind typed adapters, keep exclusions narrow and documented, and track removal |
| BasedPyright diverges materially from upstream Pyright or becomes insufficiently maintained | Pin and review every upgrade, verify the reported upstream Pyright base, and reconsider the official distribution if synchronization or maintenance becomes unreliable |
| BasedPyright's VS Code extension lacks a required Pylance-exclusive feature | Prefer the workspace-pinned extension; if a hybrid is necessary, disable Pylance type checking and keep the locked BasedPyright CLI authoritative |
| Hatchling cannot support a future native or specialized build | Keep runtime code pure Python initially and review the backend when a demonstrated packaging requirement exceeds Hatchling |
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
- Current expected API, validation, Kafka-client, test, tooling, and common AI
  packages provide Python 3.14-compatible releases; later-selected dependencies
  and optional extras will be revalidated before implementation.
- Developers and future CI workers can install the pinned uv binary.
- BasedPyright continues to publish Python 3.14-compatible distributions for
  supported developer and CI platforms and remains promptly synchronized with
  upstream Pyright.
- Docker remains the accepted deployment packaging boundary, but this ADR does
  not choose image topology or local orchestration.

## Open Questions

1. What exact policy approves new Python 3.14 patch releases and pins runtime
   image digests?
2. What lockfile update cadence and dependency-upgrade review process should
   contributors follow?
3. Which minimal Ruff rule families should be enabled at first acceptance?
4. Which test-support modules, in addition to all production source, must pass
   Pyright strict mode from the first implementation phase?
5. What upgrade evidence is required to confirm a BasedPyright release's
   upstream Pyright base and editor compatibility?
6. Which configuration and JSON-formatting libraries, if any, are necessary
   after the first contracts are defined?

These questions govern implementation policy and dependency maintenance. They
do not leave the runtime, static type checker, or build backend undecided.

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

### Python with Poetry, Black, Flake8, mypy, Setuptools, and unittest

Use mature independent tools for each concern. This was not selected because it
adds overlapping configuration and gives up Pyright-family analysis's direct
VS Code feedback loop. The selected uv, Hatchling, Ruff, BasedPyright, and
pytest stack keeps the type checker in the primary Python dependency workflow
while retaining fast, consistent interactive diagnostics.

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
- [ ] Python 3.14 compatibility is verified for required libraries, extras, and
      target architectures; the current ecosystem evidence is accepted.
- [ ] The Python 3.14 range `>=3.14,<3.15` and runtime review triggers are
      approved.
- [ ] The absence of a Python LTS designation and the runtime review triggers
      are understood.
- [ ] The project accepts uv and `uv.lock` as tooling dependencies and the
      application dependency source of truth.
- [ ] A pinned uv bootstrap and upgrade policy is agreed.
- [ ] The root `pyproject.toml`, single `uv.lock`, and editable-development
      strategy are approved.
- [ ] Hatchling is accepted as the PEP 517/PEP 660 build backend for editable
      development and future wheel or source-distribution builds.
- [ ] `src/ai_platform/` is accepted as the concrete spelling of the vertical
      slice's logical platform package.
- [ ] Ruff formatter is accepted as the only formatter.
- [ ] Ruff is accepted as the only baseline linter and its initial rule set is
      agreed.
- [ ] Pyright-family strict mode through the uv-managed BasedPyright
      distribution is accepted as the authoritative type check, and its checked
      paths are agreed.
- [ ] The BasedPyright fork-maintenance trade-off and workspace-pinned VS Code
      extension strategy are approved.
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
- [BasedPyright command-line and language-server installation](https://docs.basedpyright.com/dev/installation/command-line-and-language-server/)
- [BasedPyright IDE installation](https://docs.basedpyright.com/dev/installation/ides/)
- [BasedPyright package and editor version pinning](https://docs.basedpyright.com/dev/benefits-over-pyright/pypi-package-vscode-pinning/)
- [BasedPyright upstream synchronization](https://docs.basedpyright.com/dev/development/upstream/)
- [Pyright Python wrapper](https://github.com/RobertCraigie/pyright-python)
- [mypy documentation](https://mypy.readthedocs.io/)
- [pytest documentation](https://docs.pytest.org/)
- [FastAPI package metadata](https://pypi.org/project/fastapi/)
- [Pydantic package metadata](https://pypi.org/project/pydantic/)
- [Pydantic Core package metadata](https://pypi.org/project/pydantic-core/)
- [Confluent Kafka package metadata](https://pypi.org/project/confluent-kafka/)
- [AIOKafka package metadata](https://pypi.org/project/aiokafka/)
- [OpenAI package metadata](https://pypi.org/project/openai/)
- [Anthropic package metadata](https://pypi.org/project/anthropic/)
- [LangChain package metadata](https://pypi.org/project/langchain/)
- [Hatchling build configuration](https://hatch.pypa.io/latest/config/build/)
- [Setuptools editable installs](https://setuptools.pypa.io/en/latest/userguide/development_mode.html)
