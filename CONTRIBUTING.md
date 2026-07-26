# Contributing

Thank you for contributing to AI Platform. This project favors focused,
reviewable changes that preserve modular boundaries and keep documentation,
contracts, and implementation aligned.

Read [AGENTS.md](AGENTS.md), the
[platform architecture](docs/architecture/README.md), and relevant accepted
[Architecture Decision Records](docs/architecture/decisions/README.md) before
making changes.

## Branch and Pull Request Workflow

1. Check existing issues and documentation before starting work. Discuss a
   change first when its scope, ownership, or architectural impact is unclear.
2. Create a short-lived branch from the latest `main`. Use a concise,
   descriptive name such as `docs/security-guidance` or
   `fix/event-correlation`.
3. Keep the branch limited to one clear outcome. Avoid unrelated formatting,
   refactoring, or cleanup.
4. Update implementation, tests, contracts, and documentation together where
   they are affected.
5. Validate the change locally and record the checks performed.
6. Open a pull request describing:
   - the problem and intended outcome;
   - the scope of the solution;
   - architectural or contract effects;
   - validation performed and results;
   - security and operational considerations; and
   - known limitations or follow-up work.
7. Address review feedback and keep the branch current enough to be reviewed
   and merged safely.

Use a draft pull request when early feedback is useful but the change is not
ready to merge. Do not mix multiple independent changes into one pull request.

## Small, Focused Commits

- Each commit should represent one coherent, reviewable step.
- Keep refactoring separate from behavior changes where practical.
- Do not include caches, generated output, local configuration, editor state,
  or unrelated files.
- Preserve a usable repository state at each commit when practical.
- Rewrite or squash temporary correction commits before merge when doing so
  improves clarity and does not discard useful history.

## Documentation Requirements

Update documentation in the same pull request as the behavior or process it
describes.

Documentation must:

- distinguish implemented behavior from proposals and future work;
- describe changed interfaces, inputs, outputs, failure modes, and
  compatibility expectations;
- update relevant root and directory README files;
- update event, capability, and other shared contracts when they change;
- include operational or migration guidance when required; and
- use repository terminology and American English.

Verify local Markdown links and keep documentation concise enough to remain
maintainable.

## Architecture Decision Records

Create a Proposed ADR for a significant, cross-cutting, difficult-to-reverse,
or boundary-changing decision. Examples include changes to component
responsibilities, communication semantics, shared contracts, persistence,
security boundaries, or deployment strategy.

Use the [ADR template](docs/architecture/decisions/ADR-template.md), assign the
next sequential number, and update the ADR index. An ADR must describe context,
the decision, alternatives, and positive and negative consequences.

Do not silently introduce architecture through implementation. Do not mark a
Proposed ADR as Accepted without explicit repository-owner or maintainer
approval. Accepted ADRs are historical records; supersede them with a new ADR
instead of rewriting their decisions.

## Testing Expectations

- Add tests for new behavior and regressions at the lowest useful level.
- Validate module boundaries and public contracts independently.
- Test duplicate delivery, failure, retry, and recovery behavior when changing
  asynchronous workflows.
- Test authorization and input validation at affected trust boundaries.
- Validate infrastructure and configuration changes with the relevant local
  tools before requesting review.
- For documentation-only changes, check formatting, links, paths, and stated
  implementation status.

List the exact validation performed in the pull request. If a relevant check
cannot be run, explain why and describe the remaining risk.

The repository does not currently define automated continuous-integration
checks. Contributors are responsible for appropriate local validation until
such checks are intentionally introduced and documented.

## Code Review Expectations

Authors should obtain review from a repository owner or designated reviewer
before merge. Reviewers should evaluate:

- correctness and clarity;
- scope and modular boundaries;
- compatibility of interfaces and events;
- security, secret handling, and least privilege;
- failure, rollback, and recovery behavior;
- test relevance and validation evidence;
- documentation accuracy; and
- compliance with accepted ADRs.

Resolve review comments explicitly. Material changes made during review should
be revalidated and made visible to reviewers.

## Secrets

Follow [SECURITY.md](SECURITY.md).

Never commit credentials, tokens, passwords, private keys, provider secrets,
production values, or sensitive customer data. Use nonfunctional placeholders
in example configuration and keep real values outside source control.

If a secret is exposed, stop sharing it, notify the repository owner through a
private channel, and revoke or rotate it. Removing a secret from the latest
commit does not make it safe.

## Reporting Issues

Use the repository issue tracker for non-sensitive bugs, documentation
problems, and feature proposals when issue tracking is available. Search for an
existing report before opening a new one.

A useful issue includes:

- a concise title and description;
- expected and actual behavior;
- reproducible steps;
- relevant environment and version information;
- sanitized logs or examples; and
- known impact or workaround.

Do not report vulnerabilities or include secrets in a public issue. Follow the
private reporting guidance in [SECURITY.md](SECURITY.md). If no suitable public
or private reporting channel is configured, ask the repository owner for the
appropriate channel without disclosing sensitive details.

## Commit Messages

Use a short, imperative subject that describes the outcome of the commit:

```text
Document workflow state ownership
Fix event correlation metadata
Add contributor security guidance
```

Keep the subject specific and avoid vague messages such as `updates` or
`changes`. Add a body when the motivation, trade-offs, compatibility effects,
or follow-up work are not clear from the subject alone. Reference relevant
issues or ADRs where useful.

No mandatory commit-message convention is currently configured.
