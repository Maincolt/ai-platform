# ADR-0010: Security, Identity, Authorization, and Trust Boundaries

- **Status:** Proposed
- **Date:** 2026-07-27
- **Supersedes:** None
- **Superseded by:** None

## Context

ADR-0001 through ADR-0009 establish modular boundaries, portable contracts,
at-least-once messaging, authoritative component persistence, stable Agent and
Registry identities, and durable audit. Vertical Slice 01 adds an explicit
`LocalDevelopmentAuthorizationPolicy`, local/internal API binding,
configuration-backed Agent discovery, and least-privilege intent, but does not
select production identity, authentication, authorization, credential, or
secrets technology.

Identifiers, valid contracts, network reachability, readiness, Registry
declarations, Event Bus membership, and trace context are all claims or
operational facts. None proves that the presenter controls an authorized
principal. The platform needs a security model that survives process restart,
works on one or two local machines, and can later integrate with enterprise
identity without putting provider types or secrets in domain contracts.

### Existing Documentation Alignments and Conflicts

- ADR-0004 makes the accepted-request mapping unique by `request_id`.
  Vertical Slice 01 repeats that global uniqueness. A multi-principal API must
  scope idempotency by environment, security domain or principal, operation,
  and `request_id` to prevent one principal from discovering or blocking
  another through a guessed identifier. Vertical Slice 01 has one synthetic
  local-development principal, so behavior is unchanged there. ADR-0010 cannot
  be Accepted for multi-principal use until ADR-0004 and ADR-0006 are
  reconciled through a later decision or explicit contract revision.
- Vertical Slice 01 permits an unauthenticated local API only through
  `LocalDevelopmentAuthorizationPolicy`. This is compatible with an explicit
  development exception when it also requires development environment,
  constrained binding, narrow permissions, visible warning, and startup
  refusal outside that scope. It is not a production authentication model and
  accepts residual risk from other local processes.
- ADR-0007 and ADR-0008 call `agent_id` a stable logical deployment identity.
  This ADR clarifies that it is an authorization resource and expected
  identity, not proof that a process controls that identity.
- ADR-0008 trusts configured readiness routes and declaration digests but
  defers runtime authentication. This ADR requires authenticated,
  environment-bound readiness while leaving its exact credential mechanism
  open.
- ADR-0005 permits broker authentication and authorization but does not define
  logical permissions. This ADR defines the application authorization model
  without selecting or configuring Event Bus ACL syntax.
- ADR-0009 defers an administrative audit backend. This ADR depends on its
  durability, failure, uncertainty, and reconciliation boundary without
  selecting storage.

## Decision Drivers

The decision prioritizes correctness, deny-by-default behavior, least
privilege, explicit trust, recoverability, stable logical identity, environment
isolation, replay resistance, rotation, revocation, auditability, backend
portability, local Windows/Linux/Docker/Unraid operation, and future enterprise
integration. Convenience, network locality, identifier possession, and
provider-specific features do not override these drivers.

## Decision

### 1. Security Architecture Definition

Platform security is the coordinated control of identity, authentication,
authorization, confidentiality, integrity, availability, required
nonrepudiation, auditability, credentials, secrets, environment isolation, and
secure failure behavior across every trust boundary.

OAuth, OpenID Connect, JWT, API keys, mutual TLS, certificates, Active
Directory, Microsoft Entra ID, Keycloak, LDAP, a secrets manager, segmentation,
an API gateway, Kubernetes RBAC, a service mesh, Event Bus ACLs, a firewall,
encryption, or authentication middleware may implement part of that
architecture. No one of them defines platform security or replaces
application-level authorization.

### 2. Security Principles

The mandatory principles are:

- deny by default and fail closed on missing, invalid, stale beyond policy, or
  ambiguous security state;
- least privilege and no ambient authority or silent privilege inheritance;
- explicit human or machine principal identity at every nondevelopment trust
  boundary;
- separate human, operator, automation, component, process, Agent deployment,
  capability, and environment identities;
- separate authentication, authorization, policy decision, and enforcement;
- separate stable logical identity from replaceable credentials;
- no trust based solely on network location, `agent_id`, service name,
  hostname, IP address, process ID, container ID, consumer group, identifier,
  Registry entry, or trace context;
- environment- and capability-scoped permissions with defense in depth;
- short-lived or independently rotatable credentials where practical;
- no credentials in source control, portable contracts, messages, Registry
  declarations, logs, traces, images, or state snapshots;
- bounded exposure, secure defaults, explicit privileged approval, and durable
  audit; and
- no privilege widening through unknown fields, provider claims, delegation,
  configuration, or capability declarations.

### 3. Trust Boundary Model

Processes sharing a host or network are separate trust subjects. The selected
boundary requirements are:

| Boundary | Identity and authentication | Authorization, confidentiality, and integrity | Replay/spoofing and credential scope | Failure, evidence, and Vertical Slice 01 |
| --- | --- | --- | --- | --- |
| External client → Workflow API | Human/machine principal; production credential or trusted gateway assertion validated by API adapter | Submit/read permission by environment and resource; protected channel outside explicit local mode | Validate issuer/channel, audience, expiry, environment; client credential cannot become component credential | Fail closed; safe security log/audit as policy requires; first slice uses explicit local-development principal |
| Operator → administration | Distinct operator/security principal with stronger authentication class | Action/resource/environment permission, reason, approval, separation of duties | Short session, replay-resistant privileged operation, no shared admin credential | Fail closed and durably audit; no administrative interface in first slice |
| Workflow API/Orchestrator → PostgreSQL | Stable Orchestrator component principal with database credential | Only Orchestrator schemas/operations; protected connection | Credential scoped to environment and runtime, never migration/owner rights | Component not ready for writes; database audit/recovery evidence; selected logically |
| Agent → Agent persistence | Stable Agent deployment principal | Only its declared Agent data boundary | Separate from Orchestrator and other deployments; rotation overlap | Agent not ready/admitted; receipt/outcome evidence; selected logically |
| Orchestrator → Event Bus | Authenticated Orchestrator component | Produce commands, consume terminal events only in environment | Broker ACL plus producer adapter policy; message/domain validation remains independent | Stop affected publication/consumption; outbox/inbox evidence; logical permissions selected |
| Agent → Event Bus | Authenticated expected Agent deployment | Consume intended command subscription; produce terminal events only | Scope by environment, channel, `agent_id`; stable IDs distinguish redelivery | Fail admission/publication; Agent receipt/outbox evidence; logical permissions selected |
| Orchestrator → readiness | Orchestrator authenticates; Agent proves expected component/deployment identity | Query only configured Agent and safe readiness contract over protected channel | Environment binding, declaration digest, bounded freshness/rate | Agent becomes unavailable, not globally trusted; readiness evidence; exact mechanism deferred |
| Deployment pipeline → Registry | Automation principal and controlled artifact provenance | Author/create/promote/approve/activate are separate permissions | Revision/digest, environment promotion, rollback control | Invalid provenance fails activation; administrative audit; Git-backed flow selected |
| Registry → Orchestrator | Trusted configured artifact loaded by authenticated component context | Loader validates complete revision, environment, provenance, schema, and approval | No self-registration; digest prevents unnoticed substitution | Core/selection readiness fails closed; load/activation evidence; selected |
| Deployment configuration → Agent | Controlled artifact/injection boundary | Agent may load only its environment and deployment declaration | Digest, expected `agent_id`, no raw secret in declaration | Agent not ready on mismatch; startup evidence; selected |
| Component → telemetry exporter | Component identity if exporter is privileged | Emit only allowed/redacted signal classes | Export credential cannot authorize business action | Telemetry failure is nonblocking; security audit remains durable elsewhere; exporter optional |
| Component → external dependency | Component or delegated principal according to contract | Explicit dependency action/data classification permission | Audience, expiry, egress/data policy, replay controls | Fail affected operation safely; classified audit/log; provider deferred |
| Development → production | Separate human/automation principals and trust roots | Explicit promotion; no implicit access or credential reuse | No production secret locally; artifact identity and approval | Cross-environment attempt fails and audits; selected |
| Host/container/process | Stable component principal is not host/process identity | OS/container controls are defense in depth, not authorization source | Credential isolation limits lateral movement | Compromise containment depends on deployment controls; exact isolation deferred |
| Environment boundary | Explicit environment in principal, policy, credentials, data, broker, Registry, and persistence | No cross-environment operation by default | Separate credentials and trust configuration; globally unique IDs grant no access | Fail closed and audit crossover; selected |

### 4. Identity Categories

| Identity | Durable/portable | Credential-backed principal | Authorization/audit use | Exposure |
| --- | --- | --- | --- | --- |
| Human user/API consumer | Durable in identity authority; normalized internally | Yes outside explicit local mode | Owner/delegate and audit actor | Stable opaque reference only when authorized |
| Operator | Durable | Yes, with operator authentication class | Read/admin permissions and security audit | Internal; not public by default |
| Automation | Durable logical identity | Yes | Build, deploy, migrate, backup, restore, rotate | Internal audit reference |
| Component | Stable across restart; technology-neutral | Yes outside bounded development exception | Service permission principal | Internal logs/audit; not public |
| Process instance | Ephemeral, operational | No independent authority | Diagnostics only | Restricted operational data |
| Agent deployment (`agent_id`) | Stable logical deployment identity | Expected resource mapped to an authenticated component principal | Target, scope, declaration, audit | Portable where ADR-0004 requires; never proof |
| Capability/version | Portable semantic identity | No | Permission/resource attribute and declaration limit | Contract-safe when authorized |
| Environment | Durable trust scope | Not alone | Mandatory scope on every decision | Safe bounded classification |

Workflow, task, message, request, correlation, and trace identifiers are
resources or diagnostic identities, never principals or credentials.

### 5. Authentication Versus Authorization

Authentication establishes which principal controls a presented credential or
trusted channel. Authorization decides whether that principal may perform one
semantic action on one resource in one environment under one policy revision.

Authentication never implies capability permission. Registry declaration does
not authenticate a runtime. Broker membership does not authorize production.
A valid access token is not universal permission. Reachable readiness does not
make an Agent eligible. An authenticated operator still needs action-specific
permission and any required approval.

### 6. Principal Model

A normalized platform security context contains:

- stable principal ID and category;
- issuing trust domain and environment;
- authentication method/class and safe credential/session reference;
- granted role assignments and resolved semantic permissions;
- effective policy identity/revision;
- optional security-domain or tenant scope when later adopted;
- original and effective actor for explicit delegation; and
- authentication and authorization times.

An authentication adapter validates provider input and normalizes allowlisted
claims into this context. Domain services receive platform types, never raw
tokens, certificates, provider claim maps, middleware objects, or credentials.
Unknown claims grant nothing.

### 7. Authorization Model

The platform selects a hybrid policy model:

- coarse roles group permissions for humans and operators;
- semantic action/resource/environment permissions are authoritative;
- bounded attributes refine decisions using principal category, environment,
  workflow ownership, capability, `agent_id`, channel, data class, declaration
  revision, and action context;
- infrastructure ACLs and database grants enforce additional least privilege;
  and
- a technology-neutral authorization port evaluates versioned policy.

Pure RBAC is rejected because roles alone cannot express workflow ownership,
environment, channel, capability, or data classification. Pure ABAC is
rejected initially because unrestricted attributes are difficult to review.
Pure capability tokens are rejected because bearer possession risks authority
leakage. Per-resource ACLs are useful but insufficient across messaging and
components. Hard-coded checks are not evolvable or auditable. A distributed
general-purpose policy engine is not required for the first slice; policy is
local, deterministic, versioned, and behind a port.

### 8. Permission Taxonomy

Permission names are stable platform actions, not provider role names:

| Domain | Semantic permissions |
| --- | --- |
| Workflow | `workflow.submit`, `workflow.read`, `workflow.group.read`, future `workflow.cancel`, `task.read` |
| Diagnostics | `diagnostics.read`, `diagnostics.sensitive.read` |
| Registry/Agent | `registry.revision.manage`, `capability.enable`, `capability.disable`, `agent.drain`, `agent.revoke`, `readiness.query` |
| Recovery | `quarantine.redrive`, `outbox.disposition`, `workflow.repair`, `recovery.repair` |
| Data operations | `schema.migrate`, `backup.trigger`, `restore.trigger`, `retention.manage` |
| Security | `credential.rotate`, `authorization.policy.admin`, `break_glass.activate` |
| Messaging | `command.produce`, `command.consume`, `terminal_event.produce`, `terminal_event.consume`, separate quarantine/admin channel actions |
| Persistence | `orchestrator.persistence.access`, `agent.persistence.access`, migration/backup/restore/read-only variants |

Exact serialized names remain policy format, not wire-contract, details.

### 9. Resource and Scope Model

Permissions are evaluated against environment plus the applicable workflow,
owner/security domain, capability/version, Agent deployment, logical message
channel, administrative operation, persistence boundary, diagnostic data
classification, Registry revision, or controlled deployment class.
`correlation_id` is never sufficient authorization scope.

Evaluation occurs before workflow creation and retrieval, administrative
mutation, Event Bus production/consumption, Registry activation, Agent
selection/admission/execution, readiness query, persistence access, and
diagnostic export. Infrastructure enforcement is repeated by application
validation where domain meaning is required.

### 10. External API Authentication

Options:

| Approach | Human/machine and lifecycle fit | Local/portable trade-off | Decision |
| --- | --- | --- | --- |
| Unauthenticated | No attributable client, revocation, or scope | Simplest offline local use; unsafe for shared/production interfaces | Only explicit first-slice local-development mode |
| API key | Machine-friendly; weak human identity and delegation | Easy Windows/Linux/Unraid operation; rotation/revocation is manual and keys are bearer secrets | Not selected as production model |
| Signed service access token | Strong audience/expiry/claims when correctly validated | Portable, but issuer/key/revocation operations required | Supported future credential class |
| OAuth 2.0 access token | Strong human/machine delegation ecosystem and scopes | Adds authorization-server dependency; provider-neutral at protocol boundary | Preferred future external API class, provider deferred |
| OpenID Connect ID token | Establishes authentication event/user identity | Broad provider support | Never used as API authorization token |
| Mutual TLS | Strong machine/channel identity and sender constraint | Certificate lifecycle and local Windows/Unraid operation add complexity | Future machine-client option, not first slice |
| Reverse proxy/gateway assertion | Central human/machine integration | Must authenticate the proxy and bind/validate normalized assertion | Future adapter option; never blindly trusted |
| Local-only interface | Useful containment only | Other local processes remain hostile | Defense in depth, never sole production trust |

Vertical Slice 01 retains `LocalDevelopmentAuthorizationPolicy`: explicit
development environment, explicitly configured loopback/local binding, a
synthetic nonportable `local-development` principal, only workflow submit/read
permissions, visible reduced-security warning, and startup refusal if enabled
for a production environment or unsafe bind. It uses no client credential,
identity provider, admin permission, or sensitive-diagnostic permission. This
is a bounded development exception, not proof that a local caller is a human.

### 11. API Authorization and Workflow Ownership

Workflow acceptance durably records owner principal/security-domain reference,
environment, authorization decision, and policy revision with the accepted
request and workflow. The submitter receives read permission through ownership,
not merely because submission permission exists. Additional principals may
read only through explicit resource policy, delegation, or operator permission.

Equivalent accepted-request replay requires the same idempotency security
scope and current permission to view the workflow. A request conflict reveals
no existing workflow data. Retrieval checks authorization before returning
content. Unauthorized and nonexistent workflows use the same safe external
response where policy requires enumeration resistance. Knowing
`workflow_id`, `request_id`, or `correlation_id` grants nothing. Correlation
group lookup authorizes every returned workflow or filters it without leaking
membership.

### 12. Request Idempotency and Security Context

The target multi-principal key is:

`environment + security_domain_or_principal + operation + request_id`.

Endpoint/operation separates future request families. Credential rotation does
not change the stable principal, so a valid replay remains in scope.
Authorization changes are applied to data disclosure: a disabled or currently
unauthorized principal does not receive the stored workflow even though the
mapping remains durable. A privileged operator retrieves through an explicit
operator permission and audit policy, not by impersonating the owner.

Another principal may use the same opaque `request_id` in its own scope and
cannot discover the first mapping. An unauthenticated local mapping belongs to
the synthetic local-development principal and cannot later be claimed by a
production identity.

ADR-0004 and current ADR-0006/Vertical Slice language instead require global
uniqueness by `request_id`. The first slice has one principal and retains that
behavior. Multi-principal deployment is blocked until a follow-up decision
reconciles the accepted contract and persistence key.

### 13. Human User and Operator Separation

Normal API users own or receive explicit workflow access. Support/read-only
operators receive bounded diagnostic and workflow read permissions. Platform
operators manage runtime/Registry/recovery actions. Security administrators
manage policy and credentials. Deployment automation promotes artifacts.
Database administrators administer storage but do not gain application
impersonation. One person may hold multiple assignments, but each action uses
the effective role and separation-of-duties rules.

Sensitive diagnostics, destructive actions, production changes, credential
rotation/revocation, and security-control bypass require explicit permission
and the human approval required by `SECURITY.md`. Privileged decisions are
durably audited.

### 14. Machine and Component Identity

Workflow API/Orchestrator, each Agent deployment, Registry/deployment
automation, migration, backup/restore, and privileged telemetry exporters use
stable logical component or automation principals. Credentials are
environment-specific and replaceable without changing logical identity.
Process instance remains diagnostic only.

Replicas may share a logical component principal only when their permissions
and deployment identity are identical; separate deployments use separate
identities. Hostname, IP address, container ID, Kafka member ID, and process ID
are not principals.

### 15. Agent Identity and Authorization

An Agent proves control of a credential mapped by the trusted authentication
adapter to the expected environment-scoped component principal and `agent_id`.
It must also load the expected deployment declaration identity/digest. Runtime
authentication and trusted Registry/deployment declarations intersect:
neither can widen the other.

The Agent may consume only its intended command subscription, execute only
declared capability/version and supported contract combinations, write only
its persistence boundary, and produce only terminal events for admitted
attempts. It cannot access another Agent's or Orchestrator's data.

Admission validates authenticated producer context, target `agent_id`,
environment, declaration digest, capability/version, contract, workflow/task/
attempt/message relationships, deadline, deduplication, and effective policy.
Revocation blocks new admission immediately when known. In-flight work follows
Section 30 and cannot silently widen permissions.

### 16. Orchestrator Identity and Authorization

The Orchestrator may access its persistence, load trusted Registry
declarations, query configured Agent readiness, produce commands, consume
terminal events, and emit allowed telemetry. It never directly mutates Agent
business state and cannot read Agent persistence except through a future
explicit, approved recovery procedure.

The first slice may use one logical platform-service identity with distinct
database, broker, readiness, and secret scopes. Later separation into API,
Registry loader, publisher, consumer, migration, and recovery principals is a
least-privilege review trigger. Broad owner, superuser, broker-admin, or
security-admin access is prohibited.

### 17. Event Bus Trust Model

Logical permissions are environment and channel scoped:

- only the Orchestrator produces `ExecuteTask`;
- only authorized target Agent deployments consume intended command
  subscriptions;
- only the admitted Agent deployment produces `TaskCompleted` or `TaskFailed`;
- only Orchestrator consumers consume terminal events;
- quarantine, dead-letter, redrive, and broker administration have separate
  principals and permissions; and
- cross-environment production/consumption is denied.

Broker authentication and ACLs are one layer. Producer/consumer adapters and
domain services validate authenticated principal, expected producer,
environment, target, contract, and identities again. Consumer-group membership,
topic access, headers, payload `producer`, `agent_id`, and trace context do not
grant authority.

### 18. Message-Level Security

Consumers validate the exact contract, authenticated producer authorization,
environment/trust scope supplied by the trusted adapter, logical producer,
target `agent_id`, capability/version, workflow/task/attempt/message identity,
correlation/causation relationships, timestamp/deadline, deduplication, and
disposition.

At-least-once redelivery with the same immutable `message_id` is expected, not
by itself a malicious replay. A duplicate with changed content, unexpected
producer, wrong target/environment, invalid relationship, or expired policy is
rejected and durably classified. Inbox and receipt uniqueness provide replay
resistance for valid redelivery.

Message signing is not required initially. Authenticated protected transport,
broker ACLs, trusted adapters, immutable identity, domain validation, and
durable deduplication meet the current boundary. Signing would require contract
versioning, signer identity, canonicalization, key distribution, rotation,
revocation, replay policy, and compromise recovery; a future cross-trust-domain
requirement triggers a new ADR.

### 19. Readiness Endpoint Security

Only the Orchestrator readiness principal may query an Agent. The channel
mutually authenticates the Orchestrator and expected Agent component classes,
binds both to the environment and configured `agent_id`, protects
confidentiality/integrity, compares the loaded declaration digest, and applies
bounded timeout/rate limits.

Unauthorized callers receive no capability, dependency, endpoint, credential,
or detailed health data. Authentication, environment, identity, digest, or
freshness failure makes that Agent unavailable for new selection without
making workflow queries unavailable. The exact first-slice authentication
credential is deferred, but unauthenticated readiness is not a production
option.

### 20. Registry Declaration Trust

Trusted Registry/deployment declarations record author, capability,
implementation and deployment owners, controlled pipeline, approver,
environment, complete revision, provenance, digest/tamper evidence, activation
authority, and rollback authority.

Vertical Slice 01 loads a reviewed Git-backed configuration artifact through a
controlled deployment boundary. Agents cannot self-register, and an Agent
credential cannot modify the Registry. The loader validates provenance,
environment, schema, complete revision, approval, and digest before atomic
activation. Untrusted or altered declarations fail closed. Production
enablement may require an approver distinct from author/build identity.
Activation/rollback uses ADR-0009 administrative audit. No signing platform is
selected.

### 21. Deployment and Environment Isolation

Development, test, acceptance, and production use separate credentials,
Registry bindings, Event Bus authorization, persistence permissions,
administrative approvals, policy revisions, and secret material. Cross-
environment trust, routing, consumption, data access, and identity reuse are
denied by default. Promotion moves reviewed artifact identity through an
authorized process; it does not copy runtime credentials.

UUID domain identifiers are designed to be globally collision-resistant, but
their possession and encoded value confer no authority. `agent_id`,
`workflow_id`, `request_id`, and `correlation_id` are always interpreted within
an environment/security scope for authorization.

### 22. Persistence Security

Distinct logical identities exist for Orchestrator runtime, each Agent
deployment or identical-permission replica set, migrations, backup, restore,
read-only operations, and database administration. Runtime credentials are
never owner or superuser credentials. Migration and restore permissions are
not granted to normal processes.

Orchestrator and Agent may share the physical PostgreSQL service selected by
ADR-0006 while using isolated schemas/data ownership, separate credentials,
explicit grants, and tests that prevent cross-access. Connections use
deployment-appropriate integrity/confidentiality. Backups and credentials are
protected; SQL and binds never enter telemetry. Rotation uses bounded overlap.

### 23. Secrets and Credentials

A secret is material that grants authentication, decryption, signing, or
privileged access, including passwords, private keys, API/client secrets,
access/refresh tokens, database/broker credentials, certificate private
material, and encryption keys.

Secrets are never committed, placed in portable contracts/messages/Registry
declarations, logged/traced, baked into images, or stored in snapshots. Trusted
configuration carries references, never raw values. Deployment injects
environment-specific, least-scope, bounded-lifetime material through a
replaceable secret boundary. Command-line exposure is prohibited; in-memory
exposure is minimized. File-mounted secrets are preferred where permissions
and atomic replacement are reliable; environment injection is a bounded local
fallback with documented process/environment leakage risk. No secrets manager
is selected.

### 24. Credential Lifecycle

Every credential class has an owner and documented issuance, distribution,
activation, validation, expiry, planned rotation, overlap, revocation,
emergency revocation, compromise response, destruction, and audit process.

Rolling rotation makes old and new credentials valid for a bounded overlap:
deploy validators/trust first, issue and activate new credentials, migrate
clients, verify, revoke old credentials, then remove old trust. Rotation does
not require synchronized restart or logical identity change. Shared credentials
across components or environments are prohibited. Compromise bypasses normal
overlap and invokes emergency revocation plus reconciliation of affected work.

### 25. Token and Credential Validation

When bearer or signed credentials are later used, the trusted adapter validates
issuer/trust domain, intended audience, signature/channel integrity, approved
algorithm/key, token type, expiry, not-before, bounded clock skew, environment,
principal, scope/permission, and revocation/session policy. Syntax alone is
never acceptance, untrusted input cannot choose the algorithm, and identity
tokens are not API access tokens.

Validation keys and status may be cached only for a bounded documented period.
The cache's maximum age is the declared credential/policy staleness and
revocation window; immediate revocation is not claimed.

### 26. Replay Protection

| Surface | Protection |
| --- | --- |
| API request | Protected channel, credential expiry/audience, scoped `request_id`, canonical fingerprint, database uniqueness |
| Bearer credential | Short life, audience/environment/scope, bounded revocation; future sender constraint when risk requires |
| Privileged request | Strong authenticated session, operation idempotency, reason/approval, optional nonce/one-time approval |
| Event Bus message | Broker authorization, immutable `message_id`, inbox/receipt, `task_attempt_id`, target/environment checks |
| Readiness | Authenticated channel, bounded freshness/timeouts, rate limit, expected identity/digest |
| Registry/policy activation | Monotonic or explicit revision, artifact digest/provenance, approval and durable audit |
| Credential rotation | Unique credential identity, activation/revocation state, audit and overlap bounds |

Transport redelivery is distinguished from changed-content, wrong-principal,
wrong-environment, or expired-authority replay.

### 27. Delegation and Impersonation

Vertical Slice 01 supports no impersonation or delegation. The Agent acts on an
authorized Orchestrator command as itself, not as the API user. Automation acts
as its own principal. Operators access workflows under operator permission,
not owner impersonation.

Future delegation must carry normalized original actor, effective actor,
reason, scope, expiry, environment, policy revision, and durable audit. Silent
impersonation is prohibited. Support impersonation and break-glass require
explicit activation and cannot reuse ordinary user sessions.

### 28. Policy Decision and Enforcement Points

The local policy decision port is invoked at the API boundary/application
service, Registry loader/activation, selection where security participates,
Event Bus producer and consumer adapters, Agent command admission/execution,
readiness endpoint, persistence adapter, administrative interface, and
deployment pipeline.

Enforcement is repeated in depth: API authenticates/authorizes submission;
Orchestrator stores decision evidence; broker ACL checks channel access; Agent
still validates producer, target, capability, contract, environment, and
attempt. Persistence grants limit damage if application checks fail. No single
gateway or perimeter is authoritative for every action.

### 29. Security Context Propagation

API application context carries the normalized principal and policy decision.
Durable accepted workflow/audit stores stable principal/security-domain,
environment, delegation references, authorization outcome, and policy revision.
Event Bus transport headers may carry bounded normalized producer/security
references only when protected by the authenticated adapter. Portable payloads
retain ADR-0004 contracts and do not carry raw provider claims.

Agents receive only stable identity/decision references needed for admission.
Logs/traces use redacted references under ADR-0009. Bearer tokens, passwords,
keys, and raw credentials never enter messages. Consumers trust the
authenticated channel and their own authorization decision, not copied header
claims alone.

### 30. Authorization at Agent Execution

Before admission, the Agent checks authenticated delivery source, intended
`agent_id`, environment, declaration/capability/version, command contract,
attempt/message relationships, deadline, deployment revocation/disablement,
security classification, and recorded/current policy rules.

A valid credential with wrong target or undeclared capability is rejected and
audited. Declaration changes after dispatch do not silently reinterpret an
accepted command: the recorded selection/declaration/policy revision remains
historical authority unless a compatible policy explicitly permits execution.
Emergency deployment/credential revocation blocks new admission. For in-flight
work, the revocation policy states whether safe cancellation is required;
irreversible or uncertain effects are classified and reconciled rather than
reported as clean cancellation. A stale replica fails admission when it cannot
prove an allowed revision.

### 31. Authorization Decision Timing

- submission and accepted replay are authenticated/authorized at each API
  request; acceptance stores the decision and policy revision;
- retrieval is authorized at read time, even for an owner;
- Agent selection and command creation use one recorded point-in-time
  declaration and policy decision in the acceptance transaction;
- producer/consumer channel authorization is checked on each connection/action
  within bounded credential/cache validity;
- Agent admission rechecks environment, target, declaration, revocation, and
  execution permission while preserving historical decision meaning;
- outcome production/consumption checks the admitted attempt and current
  component authority; and
- operator mutation is authorized immediately before action and approval.

Ordinary policy changes do not rewrite historical outcomes. Emergency
revocation is explicit, audited, and may stop future steps of accepted work.

### 32. Policy Versioning and Audit

Security policy has stable identity, immutable revision, environment,
activation/effective time, approver, compatibility statement, rollback
authority, and durable administrative audit. Components load a complete
revision atomically and expose bounded readiness for it.

Workflow acceptance records policy revision; retrieval denial is audited where
enumeration, privilege, or policy requires it. Agent security selection,
privileged actions, Registry activation, Agent disablement, quarantine redrive,
and data repair record the applicable revision. Ordinary authorized reads need
not create heavy durable audit unless classification/policy requires it.
Rollback is a new audited activation, not history mutation.

### 33. Failure Behavior

| Failure | Behavior |
| --- | --- |
| API authentication/authorization failure | Fail closed with safe indistinguishable response where needed; never create workflow |
| Identity provider/key unavailable | Never become anonymous; locally verifiable unexpired cached evidence may serve allowed reads within policy, otherwise fail closed |
| Component credential expired/revoked | Stop new protected operations; component liveness may remain true but affected readiness is false |
| Database/Event Bus authentication or authorization | Stop affected writes/consumption/publication; preserve outbox/inbox state and expose not-ready |
| Readiness authentication | Agent unavailable for new selection; workflow queries remain available |
| Invalid Registry provenance/policy unavailable/ambiguous | No activation or new selection/submission requiring it; retain last explicitly valid revision only within bounded policy |
| Audit unavailable | Business mutation rolls back; privileged action fails closed or records unknown external outcome and reconciles under ADR-0009 |
| Environment mismatch/spoofed Agent | Reject, security-audit, contain credential/channel, and require operator review |
| Clock outside skew | Reject time-sensitive credential/action; do not infer order; operator remediation |
| Break-glass unavailable | No implicit superuser fallback; use normal recovery or declare incident |

Accepted workflow queries may operate in degraded read-only mode only with
locally verifiable principal, current read permission, and available
authoritative persistence. Accepted replay still requires current
authentication and disclosure authorization. Already-dispatched work follows
recorded policy plus emergency revocation rules. Liveness never implies
security readiness.

### 34. Security and Availability Trade-offs

External identity, policy, secret, certificate, broker-ACL, audit, and
revocation dependencies can reduce availability. The first slice avoids an
external identity/policy service. Future adapters may cache validation keys,
nonsecret policy, and revocation data only with explicit startup behavior,
maximum age, stale-state classification, and environment scope.

New privileged actions and workflow submissions fail closed when required
security state exceeds its cache lifetime. Read-only operation may continue
only when authorization is locally provable. Emergency revocation invalidates
the relevant cache as quickly as the selected mechanism supports; the bounded
window is documented and never described as immediate unless proven.

### 35. Administrative Actions

Registry activation/rollback, capability enable/disable, Agent drain/revoke,
credential rotation, policy activation, schema migration, restore, retention
override, quarantine redrive, outbox disposition, data repair, and future
break-glass require strong authenticated principal, semantic permission,
environment confirmation, reason, approval where required, preview/dry run
where safe, idempotency, and durable evidence.

Business/recovery mutations commit audit in the same transaction. External
administrative actions use ADR-0009 prepare/apply/audit or unknown-outcome
reconciliation. Destructive, irreversible, credential, production, or
security-bypass actions require the explicit human approval in `SECURITY.md`.

### 36. Break-Glass Access

Break-glass is unsupported in Vertical Slice 01. Database superuser, shared
root credential, disabled middleware, or local-development mode is not
break-glass.

If later required, it uses a narrowly scoped environment-specific emergency
principal, independent credential, short expiry, explicit activation, reason,
approval or mandatory post-review, enhanced durable audit, alerting,
revocation, and prohibition on ordinary use. Its implementation requires a
separate reviewed decision.

### 37. Data Confidentiality and Integrity

Protected transport is required across production API, database, Event Bus,
readiness, administrative, telemetry, and external-dependency boundaries
according to data classification. Sensitive data at rest, Event Bus retention,
backups, configuration artifacts, and secret material require deployment-
appropriate encryption and access control. Integrity/provenance controls apply
to Registry, policy, migrations, images, and promoted artifacts.

Local single-host plaintext transport is permitted only when explicit
development classification and host isolation accept the risk; it is not a
production default. Encryption does not establish authorization, identity,
provenance, replay protection, or correct target.

### 38. Data Classification and Access

| Class | Read/write authority and content | Messages/telemetry | Protection/retention/export |
| --- | --- | --- | --- |
| Public operational | Designated components write; any caller reads only fields explicitly approved as public, such as bounded health/version | Bounded safe fields | Integrity; short operational retention |
| Internal operational | Components write their own signals; authorized operators/components read topology-safe diagnostics | Allowed in authorized logs/traces; bounded messages when contractual | Access controlled; environment-limited export |
| Sensitive workflow | Authorized workflow components write; owner, explicit delegates, and privileged operators read inputs/outcomes/relationships | Only required contract fields; excluded from logs/traces by default | Encryption/access/retention by workflow policy |
| Security-sensitive | Security/policy/audit authorities write; specifically authorized security/platform operators read principal, policy, vulnerability, or restricted diagnostics | Redacted references only in ordinary telemetry | Strong access, durable audit, restricted export |
| Personal | Authorized business components write; data-subject/authorized business or privacy principals read as policy permits | Minimized and authorized; no default telemetry | Privacy policy, residency/retention/export control |
| Regulated | Explicitly approved components write/read under external obligations | Only approved paths and fields | Deployment-specific encryption, audit, retention |
| Secrets | Credential/secret authority writes; only the scoped runtime or administrator reads when required | Never in portable messages/logs/traces/Registry | Secret boundary only; minimum lifetime; no ordinary export |

Unknown classification fails closed for telemetry, external AI use, privileged
export, and administrative disclosure.

### 39. Threat Model

| Threat | Prevention | Detection | Containment and recovery | Residual risk |
| --- | --- | --- | --- | --- |
| Stolen API credential | Short life, audience/scope/environment, protected channel | Authentication anomalies/audit | Revoke, rotate, review workflows | Valid-window misuse remains |
| Stolen component credential | Least channel/data scope, isolation | Cross-scope failures, component audit | Revoke identity credential, stop deployment, reconcile | In-scope actions before detection |
| Compromised Agent | No Orchestrator/peer data access; target/capability limits | Outcome/integrity/readiness anomalies | Revoke/drain, quarantine, replace, reconcile | Authorized capability side effects |
| Compromised Orchestrator | Agent admission and persistence separation | Unexpected channel/policy/audit behavior | Revoke, stop, restore/reconcile | Command authority is high impact |
| Malicious operator | Separation, approval, least privilege | Durable administrative audit/alerts | Revoke role/session, reconcile | Collusion or approved misuse |
| Spoofed readiness | Mutual identity, environment/digest checks | Identity/digest mismatch | Mark unavailable, revoke route/credential | DoS remains |
| Unauthorized Registry change | Git review, provenance, approval, digest | Activation/audit mismatch | Reject/rollback revision | Trusted pipeline compromise |
| Cross-environment routing | Separate credentials, ACLs, policy | Crossover security event | Reject, isolate, revoke, reconcile | Misconfiguration availability loss |
| Forged producer | Broker auth plus adapter/domain checks | Producer/message mismatch | Reject/quarantine, revoke | Broker compromise |
| Replayed API request | Scoped idempotency/fingerprint/auth | Replay/conflict audit | Return existing safely or reject | Global-key conflict until reconciled |
| Replayed message | Immutable ID, inbox/receipt, target/auth | Duplicate/conflict disposition | Deduplicate/quarantine | Stolen valid credential within scope |
| Trace spoofing | ADR-0009 trust limits | Sanitization/drop metrics | Ignore context | Diagnostic confusion within accepted bounds |
| Secret leakage | No-contract/log rules, redaction, injection | Secret scanning once configured, audit | Revoke/rotate and purge safely | Detection may be delayed |
| Database misuse | Separate nonowner roles | Database/application audit | Revoke, isolate, restore/reconcile | Database-admin compromise |
| Poisoned configuration | Schema/provenance/digest/review | Startup/activation mismatch | Fail closed, rollback | Authorized malicious change |
| Supply-chain substitution | Pinning, provenance, review, controlled promotion | Artifact/digest/vulnerability checks | Block/rollback/rebuild | Upstream or build compromise |
| Denial of service | Bounds, rate limits, isolation | Saturation/security metrics | Shed/recover/scale within deployment | Availability remains attackable |
| Credential expiry outage | Monitored expiry and overlap rotation | Expiry/readiness alerts | Activate replacement/rollback | Operational error |
| Policy rollback attack | Versioned approved activation | Revision/audit mismatch | Reject or restore approved revision | Compromised approver |
| Audit tampering | Append-only application behavior and access separation | Integrity/reconciliation checks | Isolate, restore, incident handling | Backend-admin compromise |
| Same-host lateral movement | Separate credentials/users/containers, no locality trust | Cross-principal access attempts | Revoke/redeploy/isolate host | Host-admin compromise |
| Untrusted local tooling | No production credentials, local-only scope | Visible mode/logs | Stop, clean credentials/environment | Local data can be exposed |

### 40. Supply-Chain and Artifact Trust

Source, locked dependencies, Python packages, base/container images,
configuration, migrations, deployment artifacts, and Agent implementations are
versioned, reviewed, built through controlled identities, assigned immutable
artifact/revision identity, promoted explicitly by environment, and
rollback-capable.

Dependencies and images are pinned to reproducible versions or digests where
practical, with provenance/license/vulnerability review and deliberate
response under `SECURITY.md`. Migrations require separate approval/identity.
Unreviewed dynamic plugin, Agent, or skill loading cannot gain execution or
credentials. No signing or vulnerability-scanning platform is selected.

### 41. Local Development Security

Local development uses no production credential, route, Registry binding,
policy, or data. Vertical Slice 01 selects the explicit unauthenticated
`LocalDevelopmentAuthorizationPolicy` described in Section 10, with synthetic
local principal, loopback/local bind, visible warning, narrow submit/read
permission, redacted logs, isolated persistence/broker credentials, and
cleanup on teardown.

Arbitrary local processes are not authenticated; this residual risk is accepted
only for the explicit development environment. Production configuration must
fail startup if the bypass is enabled or the interface is unsafe. Fake
identities/credentials support repeatable tests; local convenience never
becomes a production default.

### 42. Testing Strategy

Tests follow `docs/testing/README.md`:

- **Identity:** stable logical identity across restart, distinct deployments,
  process identity nonauthority, environment separation, missing/invalid
  principal, rotation.
- **API:** valid/missing/expired/wrong issuer-audience-environment credential,
  insufficient permission, owner/shared access, identifier guessing,
  same/different-principal replay, changed authorization.
- **Agent/Registry:** trusted/tampered declaration, unauthorized activation,
  spoofed `agent_id`, digest mismatch, valid credential with undeclared
  capability, declared but unauthenticated Agent, stale policy.
- **Event Bus:** authorized producer/consumer, wrong channel/environment/target,
  broker ACL plus domain enforcement, redelivery versus hostile replay,
  revocation.
- **Persistence:** least-privilege runtime, Agent/Orchestrator isolation,
  separate migration/backup/restore identities, credential failure and overlap.
- **Administration:** strong authentication, missing role/reason/approval,
  coupled-audit rollback, administrative audit failure/unknown outcome, future
  break-glass bounds.
- **Context/execution:** normalized principal, no raw token, policy revision,
  delegation fields, environment, Agent admission, decision timing.
- **Failure:** unavailable identity/key/policy/secret/audit, revoked in-flight
  credential, skew, fail closed, selected read-only degradation.
- **Confidentiality:** no secret in logs/traces/Registry/messages, safe public
  errors, protected diagnostics and data classes.

Fast tests use fake credentials and identities. Integration/resilience/security
tests are required to prove real certificate/token validation, broker ACLs,
database grants, network isolation, rotation/revocation timing, process and
cross-host behavior. Unit tests cannot prove those controls.

### 43. Technology Evaluation

All options can be adapted behind the normalized principal, authentication,
authorization, and secret ports. Product/provider types never cross them.

| Option | Fit for humans, machines, components, and local use | Portability, lifecycle, complexity, and decision |
| --- | --- | --- |
| Static local credential | Machine/local only; no human federation | Offline and portable, but manual rotation/revocation and bearer risk; optional future local alternative, not selected for first-slice API |
| HTTP Basic | Human/machine password on every request | Portable but weak lifecycle/delegation and broad replay impact; rejected |
| API keys | Simple machine client | Portable/offline, weak identity/delegation, manual rotation; rejected as production standard |
| Signed bearer tokens | Human/machine claims, audience/expiry | Portable and offline validation, but key/revocation/replay complexity; supported class, format deferred |
| OAuth 2.0 | Human delegation and machine clients | Mature migration path; authorization-server availability/operations; preferred future API authorization protocol |
| OpenID Connect | Human authentication and identity claims | Broad enterprise support; ID token is not API access token; future authentication integration |
| Mutual TLS | Strong machine/channel identity | Windows/Linux/Unraid capable but PKI/renewal operational cost; future component/client option |
| Microsoft Entra ID | Managed enterprise human/workload integration | Cloud/provider coupling and connectivity; future adapter, not selected |
| Keycloak | Self-hosted OIDC/OAuth human/machine provider | Portable but adds operated state/updates; future adapter, not selected |
| LDAP | Directory authentication source | Limited modern API token/delegation semantics; possible upstream source, not API security model |
| Reverse proxy authentication | Central boundary for humans/machines | Easy migration if signed/bound assertions are validated; optional adapter, not sole enforcement |
| API gateway authentication | Central auth/rate/policy features | Product and topology dependency; future defense layer, not required |
| Workload identity | Strong component identity concept | Issuer/attestation platform required; architectural fit, implementation deferred |
| Certificate service identity | Strong mutual machine proof | PKI, renewal, revocation burden; supported future class |
| SPIFFE/SPIRE | Portable workload IDs and short-lived SVIDs | Strong heterogeneous workload model, but adds control plane/attestation; future option, not first slice |
| Vault | Dynamic/static secrets, identity, leases, audit | Self-hosted/cloud operations and product dependency; future secret adapter, not selected |
| Cloud secret stores | Managed rotation/integration | Cloud lock-in/offline limits; future adapters |
| File-mounted secrets | Good component/local injection | Portable/offline and permissionable; rotation requires atomic mount/reload; preferred generic mechanism where reliable |
| Environment variables | Simple Docker/Windows/Linux/Unraid injection | Broad exposure to process/debug tooling and awkward rotation; bounded development fallback |
| Database roles | Strong persistence least privilege | Selected enforcement class; exact grants/schema ownership deferred to implementation |
| Event Bus ACLs | Strong channel-level defense | Selected enforcement class behind ADR-0005 adapter; exact ACL technology/configuration deferred |
| Application authorization | Understands semantic resources and context | Selected mandatory layer; local versioned policy initially, external engine not required |

The selected boundaries operate offline and on Windows, Linux, Docker, and
Unraid. Entra/cloud stores need connectivity; Keycloak, SPIRE, and Vault add
services unsuitable for the minimal one/two-machine slice. OAuth/OIDC and
SPIFFE preserve future migration through standards, but no provider, token,
PKI, workload-identity, or secret product is selected.

### 44. Initial Vertical Slice Decision

Vertical Slice 01 uses:

- explicit development environment and stable local Orchestrator and Test Agent
  deployment identities, distinct from process IDs;
- `LocalDevelopmentAuthorizationPolicy` with no client credential, synthetic
  local principal, local bind, visible warning, and submit/read only;
- trusted Git/configuration-backed Registry with no Agent self-registration;
- distinct injected database and Event Bus credentials and logical
  producer/consumer permissions;
- application checks for expected producer, target `agent_id`,
  capability/version, contract, environment, and attempt;
- authenticated, environment-bound readiness as an architectural requirement,
  with exact development credential deferred;
- no raw token or secret in message, contract, Registry, log, or trace;
- file/injected local secrets, mandatory redaction and ADR-0009 audit
  boundaries;
- no production identity provider, dynamic policy engine, service mesh,
  message signature, or break-glass path; and
- fail-closed startup outside explicit local-development mode.

### 45. Coherent Security Decision

The platform adopts deny-by-default, least-privilege, environment-scoped,
defense-in-depth security with:

- distinct normalized human, operator, automation, component, process, Agent,
  capability, and environment identities;
- authentication separated from a hybrid role/permission/context authorization
  model behind technology-neutral ports;
- semantic permissions enforced at API, domain, Registry, messaging, Agent,
  readiness, persistence, administration, and deployment boundaries;
- ownership-based workflow access and multi-principal idempotency scoped by
  environment/principal/operation once ADR-0004/ADR-0006 are reconciled;
- stable component principals with replaceable, scoped credentials;
- Registry/declaration trust intersected with authenticated Agent runtime;
- broker/database infrastructure controls plus independent domain checks;
- no initial message signing, provider-specific claims, raw token propagation,
  dynamic global policy engine, or enterprise identity product;
- versioned policy and durable principal/decision/audit evidence;
- bounded caches, explicit rotation overlap and revocation windows, no silent
  anonymous degradation;
- separate business-coupled and administrative audit failure semantics under
  ADR-0009;
- no first-slice delegation or break-glass;
- classified data, protected channels, secret injection, and supply-chain
  provenance; and
- an explicit local-development exception that cannot start as production.

### 46. Security Guarantee and Evidence Table

| Guarantee | Authority/source | Credential/channel and validator | Permission/enforcement/scope | Staleness | Durable evidence | Failure and required test |
| --- | --- | --- | --- | --- | --- | --- |
| Authorized clients submit | Principal authority + active policy | Local dev context initially; future access credential validated by API | `workflow.submit`; API/Orchestrator; environment | Per request; cache bound | Accepted owner/policy decision | No workflow; valid/missing/expired/permission tests |
| Retrieval controlled | Workflow owner/share + current policy | Authenticated request at API | `workflow.read`; workflow/environment | Per read | Access/denial audit where policy requires | Safe not-found; ownership/guessing tests |
| Replay cannot cross principal | Accepted-request security scope | Authenticated API principal | Scoped idempotency key; API/Orchestrator | Per request | Mapping owner/scope/revision | No disclosure; same/different-principal tests; ADR conflict blocks production |
| Only Orchestrator commands | Component principal + policy | Broker credential/channel, validated by adapter/Agent | `command.produce`; channel/environment | Credential/ACL cache bound | Orchestrator outbox + Agent receipt/rejection | Reject/quarantine; forged producer test |
| Intended Agent consumes | Agent principal + declaration | Broker credential validated by adapter and Agent | `command.consume`; channel/`agent_id`/environment | Credential/policy bound | Receipt/admission audit | Reject; wrong-agent/cross-env tests |
| Trusted Agent emits outcome | Agent principal + admitted attempt | Broker credential, Orchestrator validates | `terminal_event.produce`; attempt/channel/env | Credential bound | Agent outcome/outbox + Orchestrator inbox | Reject/quarantine; spoofed outcome test |
| Agent cannot widen capability | Registry/deployment revision + policy | Authenticated Agent and validated command | Execute intersection; Agent admission | Recorded revision + emergency revocation | Selection/admission/outcome evidence | Reject; declared/authenticated mismatch tests |
| Registry activation controlled | Artifact provenance + admin policy | Automation/operator credential; loader validates | `registry.revision.manage`; environment | Immediate revision | Administrative audit | No activation; tamper/approval tests |
| Readiness not spoofed | Expected Agent/Orchestrator principals + route/digest | Authenticated protected channel; both endpoints validate | `readiness.query`; `agent_id`/environment | Short bounded freshness | Readiness identity/digest evidence | Agent unavailable; spoof tests |
| Environment crossover rejected | Environment trust policy | Every credential/adapter validates environment | All actions; all enforcement points | Credential/policy bound | Security crossover audit | Reject/contain; cross-env tests |
| Database least privilege | Database grants + component mapping | Database credential validated by PostgreSQL | Persistence permission/schema/env | Connection/credential bound | DB/application audit and records | Not-ready/denied; cross-schema tests |
| No secret in contracts/telemetry | Classification and emission policy | Boundary validators/redactors | No secret export; contract/telemetry adapters | Policy revision | Security audit for violations | Reject/drop/rotate; leakage tests |
| Rotation preserves continuity | Credential authority/lifecycle plan | Old/new credentials validated during overlap | Same principal/scope/env | Explicit overlap | Rotation audit | Rollback/recover; overlap tests |
| Revocation bounded | Credential authority + cache policy | Validators check status/key within maximum age | Principal/credential/env | Declared maximum window | Revocation and affected-work audit | Stop new actions; timing tests |
| Admin actions attributable | Human/automation authority + approval policy | Strong credential validated at admin boundary | Semantic admin permission/resource/env | Per action/session bound | ADR-0009 admin audit | Fail closed/unknown reconcile; actor/approval tests |
| Audit failure prevents unrecorded mutation | Business state/audit or admin audit authority | Persistence/audit boundary validates durability | Mutation/admin permission | Transaction/action | Coupled or administrative evidence | Rollback or unknown reconciliation; audit outage tests |

### 47. Consequences

#### Positive Consequences

- Trust, identity, credentials, permissions, environment, and audit are
  explicit and independently testable.
- Compromise is constrained by component, channel, capability, and persistence
  scope.
- Provider-neutral security context permits future enterprise migration.
- Rotation, revocation, replay, and restart behavior are defined.

#### Negative Consequences

- Identity and policy evidence add storage, testing, and operational work.
- Local unauthenticated mode retains risk from other local processes.
- Multiple enforcement layers can disagree and require careful diagnostics.
- Multi-principal idempotency needs an accepted-contract follow-up.

#### Migration Impact

No security implementation exists. Multi-principal production use requires
reconciling the `request_id` key, adding normalized principal/policy evidence,
and selecting deployment credentials without changing domain identity.

#### Developer Impact

Developers pass normalized security context, declare semantic permission
checks, avoid provider types/secrets, preserve audit transaction boundaries,
and test failure at each enforcement point.

#### CI Impact

Fast fake-identity tests remain local. Real token/certificate, ACL, database
grant, rotation, revocation, and cross-host tests require controlled
integration/security environments. No unconfigured CI capability is claimed.

#### Operational Impact

Operators manage identity mappings, policy revisions, credential expiry/
rotation, environment separation, audit reconciliation, and least-privilege
drift.

#### Security Impact

The model reduces ambient trust and capability widening but cannot eliminate
damage by a compromised principal within its legitimate scope.

#### Availability Impact

Fail-closed dependencies reduce write availability. Bounded validated caches
and authorized read-only degradation may preserve safe reads without anonymous
fallback.

#### Privacy Impact

Principal, ownership, delegation, and security audit become protected data.
Access, minimization, retention, and export rules apply.

#### Cost Impact

The first slice adds concepts and tests but no mandatory identity service.
Future providers, PKI, secret stores, and audit systems add compute, storage,
licensing, and operational cost.

#### Future Review Triggers

Review for multi-principal API, production exposure, multi-tenancy, external
IdP, workload identity/PKI, secret manager, service mesh, cross-trust messaging,
message signing, dynamic policy service, regulated data, break-glass, or
multiple production environments.

### 48. Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| Component identity confused with process | Stable logical principal; process ID diagnostics only |
| `agent_id` treated as authentication | Credential-to-principal proof plus declaration intersection |
| Network locality treated as trust | Application authorization; local exception explicitly bounded |
| Valid token treated as universal | Issuer/audience/environment/scope plus semantic permission |
| Request replay crosses principals | Scoped idempotency; block multi-principal production until ADR conflict resolved |
| Workflow ID guessing | Authorization before disclosure and safe not-found |
| Overprivileged service credential | Separate DB/channel/action scopes and review |
| Credentials shared across environments | Separate issuance/trust/configuration and crossover rejection |
| Agent widens capability | Declaration/authenticated identity/policy intersection at admission |
| Unauthorized production | Broker ACL plus adapter/domain producer checks |
| Broker ACL considered sufficient | Repeat contract, target, environment, and principal validation |
| Readiness spoofing | Mutual component authentication, digest and environment binding |
| Registry tampering | Git review, provenance, complete revision, digest, approval |
| Stale credential/policy cache | Maximum age, readiness, fail closed, visible revocation window |
| Revocation delay | Short life, bounded cache, emergency invalidation; no immediate claim |
| Rotation outage | Old/new overlap, staged validation, rollback |
| Secret leakage | Injection, prohibition, redaction tests, immediate rotation |
| Development bypass reaches production | Environment/bind validation and startup refusal |
| Operator escalation | Separate roles, semantic permissions, approval, audit |
| Missing separation of duties | Author/build/approve/activate distinctions for high impact |
| Audit failure ignored | Transaction rollback or fail-closed/unknown reconciliation |
| External admin effect uncertain | Prepare/apply/audit and mandatory reconciliation |
| Compromised Agent moves laterally | No peer/Orchestrator persistence, scoped broker and secrets |
| Runtime database superuser | Dedicated nonowner roles and grant tests |
| Signing without lifecycle | No initial signing; future ADR covers key/replay/version lifecycle |
| IdP outage blocks safe reads | Bounded local validation and authorized read-only mode |
| Policy service becomes correctness dependency | Local deterministic versioned policy first |
| Provider claims leak | Normalize through adapter; platform types only |
| Cross-environment deployment error | Separate credentials/bindings/policy and promotion checks |
| Artifact substitution | Immutable identity/digest/provenance and controlled promotion |
| Break-glass becomes routine | Unsupported initially; future short-lived audited emergency principal |

### 49. Assumptions

- ADR-0001 through ADR-0009 remain Accepted.
- Vertical Slice 01 remains explicitly development-only and has one synthetic
  API principal, one Orchestrator, and one Test Agent deployment.
- PostgreSQL and the Event Bus can enforce distinct logical credentials and
  permissions selected in their accepted ADRs.
- Deployment can inject secrets outside source control.
- Host/container/network controls exist but are not authoritative identity.
- Identity provider, authorization server, gateway, CA/PKI, secrets manager,
  service mesh, SIEM, workload-identity platform, multi-tenancy, final human
  model, and production topology remain unresolved.

### 50. Open Questions

1. How will ADR-0004/ADR-0006 version the multi-principal accepted-request key?
2. Which exact development credential authenticates readiness?
3. What token format, issuer/audience, and authentication adapter are selected
   for the first nonlocal API?
4. What exact permission/role/policy document and revision naming formats apply?
5. What credential lifetimes, rotation overlaps, validation-key cache age, and
   revocation windows meet measured deployment needs?
6. What Registry artifact provenance/tamper mechanism is required for
   production?
7. Which administrative audit backend and secret injection mechanism are used?
8. What CA/workload identity, future identity provider, and production
   encryption requirements apply by data class?
9. Is break-glass required, and if so what separately reviewed implementation
   satisfies Section 36?

### 51. Explicitly Out of Scope

Final enterprise identity/OAuth server, PKI/CA, secrets manager, service mesh,
Kubernetes identity, SIEM, API gateway, firewall rules, exact network topology,
multi-tenancy, billing, HR identity lifecycle, organization-wide roles,
incident-response process, legal retention, DLP, endpoint security, malware
scanning, final vulnerability platform, penetration-test process,
cryptographic ledger, message signing, production key-management service, and
implementation configuration are out of scope.

### 52. Acceptance Checklist

- [ ] Security includes identity, authorization, confidentiality, integrity,
      availability, audit, credentials, isolation, and secure failure.
- [ ] Deny-by-default, least privilege, no ambient authority, and no
      network/identifier-only trust are approved.
- [ ] Every major trust boundary identifies principals, authentication,
      authorization, replay/spoofing, scope, failure, audit, and slice status.
- [ ] Human, operator, automation, component, process, Agent, capability, and
      environment identities remain distinct.
- [ ] The normalized principal model excludes raw/provider credentials.
- [ ] Authentication and authorization remain separate.
- [ ] Hybrid roles, semantic permissions, bounded attributes, and local
      versioned policy are approved.
- [ ] Permission taxonomy and environment/resource scopes are stable.
- [ ] First-slice local unauthenticated access is explicitly bounded and cannot
      start as production.
- [ ] Future API access uses access credentials, never ID tokens as access
      tokens.
- [ ] Workflow ownership, sharing, safe not-found, and correlation-group access
      are explicit.
- [ ] Multi-principal request-id scope conflict with ADR-0004/ADR-0006 is
      acknowledged and blocks production acceptance.
- [ ] User, support, operator, security, automation, DBA, and break-glass
      responsibilities are separate.
- [ ] Stable component principal survives restart and credentials are
      replaceable.
- [ ] `agent_id` and capability declarations never prove authentication.
- [ ] Agent authority is the intersection of runtime identity, declaration,
      command, environment, and policy.
- [ ] Orchestrator permissions exclude direct Agent-state mutation and broad
      administration.
- [ ] Event Bus producer/consumer permissions are channel/environment scoped
      and reinforced by domain validation.
- [ ] Message validation, redelivery, hostile replay, and no-signing decision
      are clear.
- [ ] Readiness uses authenticated expected identities, environment, digest,
      freshness, and safe responses.
- [ ] Registry author/provenance/approval/activation/rollback trust is explicit.
- [ ] Environment credentials, data, Registry, bus, policy, and approval are
      isolated.
- [ ] Runtime, migration, backup, restore, read-only, and admin persistence
      identities are distinct.
- [ ] Secrets never enter source, contracts, messages, Registry, telemetry, or
      images.
- [ ] Credential issuance, overlap rotation, revocation, compromise, and
      destruction are defined.
- [ ] Token validation includes issuer, audience, type, time, algorithm,
      environment, principal, scope, and revocation policy.
- [ ] API, credential, message, readiness, activation, and rotation replay
      controls are explicit.
- [ ] Delegation/impersonation is unsupported initially and future context is
      attributable.
- [ ] Decision and enforcement points repeat critical checks in depth.
- [ ] Security context uses normalized references and no bearer credentials.
- [ ] Agent admission and in-flight revocation behavior are explicit.
- [ ] Authorization timing preserves historical meaning and emergency
      revocation.
- [ ] Policy identity, revision, activation, rollback, and audit are durable.
- [ ] Every security dependency fails closed without anonymous fallback.
- [ ] Bounded caches declare staleness and do not claim immediate revocation.
- [ ] Administrative controls align with ADR-0009 transaction/uncertainty
      boundaries and `SECURITY.md` approval.
- [ ] Break-glass is unsupported in the first slice and is not a database
      superuser.
- [ ] Confidentiality/integrity requirements do not replace authorization.
- [ ] Data classes define access, message/telemetry, encryption, retention, and
      export behavior.
- [ ] Threat controls state detection, containment/recovery, and residual risk.
- [ ] Supply-chain trust covers source, dependencies, images, configuration,
      migrations, artifacts, and Agents.
- [ ] Local development has no production credentials or accidental external
      binding.
- [ ] Tests distinguish fast policy proof from real credential, ACL, network,
      process, and revocation proof.
- [ ] Technology evaluation selects boundaries and first-slice behavior without
      selecting enterprise products.
- [ ] Reviewers confirm consistency with ADR-0001 through ADR-0009, Vertical
      Slice 01, testing guidance, `SECURITY.md`, and `AGENTS.md`.
- [ ] Remaining open questions are bounded except the explicitly identified
      accepted-request scope blocker.

## Related Decisions

- [ADR-0001: Core Design Principles](ADR-0001-core-design-principles.md)
- [ADR-0002: Platform Communication and State](ADR-0002-platform-communication-and-state.md)
- [ADR-0003: Runtime and Development Tooling](ADR-0003-runtime-and-development-tooling.md)
- [ADR-0004: API and Contract Standards](ADR-0004-api-and-contract-standards.md)
- [ADR-0005: Event Bus and Messaging Infrastructure](ADR-0005-event-bus-and-messaging-infrastructure.md)
- [ADR-0006: Persistence, State, and Recovery](ADR-0006-persistence-state-and-recovery.md)
- [ADR-0007: Agent Execution Model and Lifecycle](ADR-0007-agent-execution-model-and-lifecycle.md)
- [ADR-0008: Capability Registry and Agent Discovery](ADR-0008-capability-registry-and-agent-discovery.md)
- [ADR-0009: Observability, Telemetry, and Audit Correlation](ADR-0009-observability-telemetry-and-audit-correlation.md)

## References

- [Platform Architecture](../README.md)
- [Vertical Slice 01](../../implementation/vertical-slice-01.md)
- [Platform test strategy](../../testing/README.md)
- [Repository security policy](../../../SECURITY.md)
- [Repository Agent guidance](../../../AGENTS.md)
- [OAuth 2.0 Security Best Current Practice (RFC 9700)](https://www.rfc-editor.org/rfc/rfc9700.html)
- [OAuth 2.0 Bearer Token Usage (RFC 6750)](https://www.rfc-editor.org/rfc/rfc6750.html)
- [OpenID Connect Core 1.0](https://openid.net/specs/openid-connect-core-1_0-35.html)
- [SPIFFE overview](https://spiffe.io/docs/latest/spiffe-about/overview/)
- [SPIFFE concepts](https://spiffe.io/docs/latest/spiffe/concepts/)
- [Microsoft identity platform: authentication versus authorization](https://learn.microsoft.com/en-us/entra/identity-platform/authentication-vs-authorization)
- [Vault documentation](https://developer.hashicorp.com/vault/docs)
