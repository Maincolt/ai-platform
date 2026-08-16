# Security Policy

## Supported Versions

AI Platform is currently pre-release and has no formally supported production
version. Security fixes are considered only for the latest state of the default
branch.

This section must be updated with an explicit version-support table before the
first release. Older commits, development branches, forks, and unmaintained
deployments are not covered by a support commitment.

## Reporting a Vulnerability

Do not disclose suspected vulnerabilities, exploit details, credentials, or
sensitive data in a public issue.

Private security contact: **[REPOSITORY OWNER MUST PROVIDE A PRIVATE SECURITY
CONTACT OR REPORTING CHANNEL]**

Until that contact is configured, ask the repository owner for a private
reporting channel without including sensitive details. A report should include:

- a concise description and potential impact;
- affected versions, components, or configurations;
- reproducible steps or a minimal proof of concept;
- known mitigations or suggested remediation; and
- whether the issue is already public or actively exploited.

No acknowledgement, remediation, or disclosure SLA is currently established.

## Secrets and Credentials

- Never commit passwords, API tokens, private keys, certificates containing
  private material, cloud credentials, AI provider credentials, session data,
  or production environment values.
- Keep secrets outside source control and inject them at runtime through an
  approved secret or configuration boundary.
- Commit only clearly marked example files containing nonfunctional placeholder
  values.
- Prevent secrets from appearing in events, prompts, model outputs, logs,
  traces, test fixtures, build artifacts, or container images.
- Treat an exposed secret as compromised. Revoke or rotate it promptly; removing
  it from the latest commit is not sufficient.

## Least Privilege

Users, AI Agents, services, tools, credentials, and containers must receive only
the permissions and data access required for their current responsibility.
Prefer deny-by-default access, narrowly scoped credentials, isolated execution,
and time-limited authorization where practical.

Authorization must be checked at trust boundaries. Capability registration,
message receipt, or access to an internal network does not grant permission to
perform an action.

## External AI Providers

Data sent to an external AI provider crosses a trust boundary. Before sending
data:

- minimize and redact the input;
- exclude credentials and secrets;
- obtain authorization for confidential, personal, regulated, customer, or
  proprietary information;
- review applicable retention, training, residency, access, and deletion terms;
  and
- ensure the selected provider and model are permitted for the data
  classification and use case.

Model responses are untrusted output and must be validated before they affect
code, infrastructure, stored data, or external systems.

## Human Approval for High-Impact Actions

AI Agents and automation must obtain explicit human approval immediately before
performing a destructive, irreversible, or materially high-impact action. This
includes deleting or overwriting data, changing production infrastructure,
publishing externally, rotating or revoking active credentials, bypassing a
security control, or executing an operation that cannot be safely rolled back.

Approval must identify the action and its target. Earlier approval for a plan or
unrelated change is not sufficient.

**Narrow exception (ADR-0026):** an autonomous team-agent role operating under
[ADR-0026](docs/architecture/decisions/ADR-0026-autonomous-team-agents.md)'s
bounded, enumerated, per-role least-privilege, and durably audited action set
is exempt from this section's per-action approval requirement, but only for
the specific actions ADR-0026 explicitly grants that role. The exemption
requires, without exception: a fixed and enumerable action set the model
cannot expand (no raw tool/API access), a durable audit record of every
action taken, a platform-wide kill switch checked before every action, and a
hard spend/rate cap. Any action outside a role's explicitly granted set, any
new role, and every other AI Agent or automation in this platform remain
fully subject to this section's approval requirement unmodified.

## Prompt Injection and Untrusted Input

Treat user input, repository content, retrieved documents, external events,
model output, tool output, links, and generated instructions as potentially
hostile.

- Keep trusted instructions separate from untrusted data.
- Do not allow embedded content to expand authorization or override platform
  policy.
- Validate structured input and output against explicit contracts.
- Restrict tools, filesystem access, network access, and credentials to the
  minimum required scope.
- Review commands and side effects before execution, especially when content
  originated outside the repository.

## Dependencies and Container Images

- Use maintained dependencies from trusted sources and retain lockfiles where
  the ecosystem supports them.
- Review dependency provenance, licenses, known vulnerabilities, and transitive
  impact before adoption or upgrade.
- Remove unused dependencies and apply security updates deliberately.
- Use minimal, maintained base images and pin release artifacts to an immutable
  version or digest where practical.
- Run containers without elevated privileges unless a documented requirement
  justifies them.
- Do not bake credentials, private configuration, caches, or unnecessary tools
  into images.
- Scan dependencies and container images before release and periodically
  thereafter once scanning is configured.

The repository does not currently configure or endorse a particular dependency
or container image scanner.
