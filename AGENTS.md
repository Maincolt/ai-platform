# AI Platform Agent Guidance

This file defines repository-wide expectations for human contributors and AI
agents. It deliberately does not define individual agents or assign
role-specific behavior.

## Project Philosophy

- Build the platform as a collection of focused, replaceable modules.
- Prefer explicit boundaries and stable contracts over shared internal
  knowledge.
- Keep the core independent of any single model, vendor, cloud, or external
  service.
- Treat source control as the source of truth for code, configuration,
  infrastructure definitions, and documentation.
- Prefer open interfaces and reproducible processes.
- Make architectural intent visible. Record significant decisions before their
  consequences become difficult to reverse.
- Add complexity only when a current, documented requirement justifies it.

## Collaboration Principles

- Start by reading the repository guidance and the documentation relevant to
  the area being changed.
- Keep each change focused on one clear outcome.
- Respect module ownership and avoid unrelated edits.
- Make assumptions explicit when repository context cannot resolve them.
- Raise conflicts, unclear requirements, and irreversible trade-offs rather
  than silently choosing a direction.
- Preserve work already present in the working tree unless changing it is part
  of the request.
- Review changes for effects on contracts, documentation, tests, operations,
  and other modules.
- Verify work in proportion to its risk and report what was and was not
  validated.

## Coding Standards

These standards apply when implementation code is introduced:

- Favor small, cohesive modules with narrow public interfaces.
- Keep domain logic separate from providers, transport, persistence, and
  deployment concerns.
- Depend on documented abstractions at module boundaries.
- Use clear names and straightforward control flow; avoid cleverness that
  obscures intent.
- Handle errors explicitly and preserve enough context for diagnosis.
- Make operations safe to retry where practical.
- Validate data at trust boundaries and never expose secrets in source,
  fixtures, logs, or error messages.
- Keep configuration external to implementation code and provide safe,
  documented defaults where appropriate.
- Add automated tests for new behavior and regressions at the lowest useful
  level.
- Follow established formatting, linting, typing, and test conventions once
  they exist. Do not introduce a new tool or convention without documenting
  the decision.
- Remove obsolete paths when replacing behavior unless compatibility is an
  explicit requirement.

## Documentation Standards

- Update documentation in the same change as the behavior, contract, or
  process it describes.
- Keep repository and directory README files accurate, concise, and scoped to
  their audience.
- Document interfaces, inputs, outputs, failure modes, operational
  expectations, and compatibility constraints.
- Record significant architectural decisions as Architecture Decision Records
  under `docs/architecture/decisions/`.
- ADRs must describe status, context, decision, considered alternatives, and
  consequences.
- Do not rewrite accepted ADRs to hide earlier decisions. Supersede them with a
  new record and link both records.
- Clearly distinguish current behavior from proposals or planned work.
- Avoid claiming support for components, integrations, or technologies that
  have not been implemented and verified.

## Responsibilities of AI Agents

AI agents working in this repository must:

- Act only within the scope and authority of the current request.
- Inspect relevant files and repository state before making changes.
- Preserve modularity, vendor neutrality, and documented contracts.
- Avoid defining new architecture implicitly through implementation.
- Create or update an ADR when making a significant architectural decision.
- Keep changes reviewable and avoid modifying unrelated files.
- Never commit credentials, tokens, private data, or environment-specific
  secrets.
- Validate their work and communicate limitations, unresolved risks, and
  assumptions.
- Leave the repository in a coherent state and identify any incomplete work.
- Avoid defining specific agent roles in this file; individual definitions
  belong under `agents/` when they are intentionally introduced.

## Communication Principles

- Communicate clearly, concisely, and with enough context for another
  contributor to continue the work.
- Lead with outcomes, decisions, and blockers.
- Separate observed facts from assumptions and recommendations.
- Use shared terminology from repository documentation and define new terms
  before relying on them.
- Reference relevant files, contracts, decisions, and validation results.
- Do not imply that unimplemented or unverified behavior is available.
- Prefer durable communication in version-controlled documentation for
  decisions that affect future work.

## Event-Driven Behaviour

Events are contracts between modules, not informal notifications.

- Modules communicate across boundaries through documented events rather than
  direct knowledge of one another's internals.
- Event names and payloads must express business meaning and have a clear
  owner.
- Schemas, required fields, compatibility expectations, and versioning rules
  must be documented before use.
- Events should include identifiers that support tracing, correlation, and
  causation without exposing sensitive data.
- Producers must not depend on the number, location, or implementation of
  consumers.
- Consumers must validate incoming events, handle duplicates safely, and avoid
  assuming delivery order unless the contract guarantees it.
- Failure, retry, timeout, and recovery behavior must be explicit and
  observable.
- Contract changes must preserve compatibility or introduce a documented
  version transition.
- Event payloads should contain the information required by the contract
  without exposing module internals.
- Commands, facts, and responses should remain semantically distinct.

Specific event formats, transports, delivery guarantees, and operational
policies require documented architectural decisions before implementation.
