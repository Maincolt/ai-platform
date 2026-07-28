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
  use an adapter-resolved `idempotency_scope_id` and construct the logical key
  from environment, that scope, operation, and `request_id` to prevent one
  security scope from discovering or blocking another through a guessed
  identifier. Vertical Slice 01 has one synthetic local-development scope, so
  behavior is unchanged there. ADR-0010 remains Proposed until ADR-0004 and
  ADR-0006 are formally amended or superseded to define API semantics,
  persistence uniqueness, replay/conflict behavior, migration/compatibility,
  and security-safe external errors.
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
  defers runtime authentication. This ADR selects a generated,
  environment-scoped development readiness credential for Vertical Slice 01
  that authenticates the Orchestrator to the Agent. The Orchestrator performs
  bounded development-only Agent endpoint verification but does not
  cryptographically authenticate the Agent. Production requires mutually
  authenticated, environment-bound, cryptographically protected component
  identities.
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
boundary requirements are below. Effective reachability is evaluated across
the process or container listener, container network reachability, host
publication, reverse proxy or forwarding configuration, and every resulting
route. A container-internal listener is not itself a host exposure, but it is
not trusted merely because it is container-local.

| Boundary | Identity and authentication | Authorization, confidentiality, and integrity | Replay/spoofing and credential scope | Failure, evidence, and Vertical Slice 01 |
| --- | --- | --- | --- | --- |
| External client → Workflow API | Human/machine principal; production credential or trusted gateway assertion validated by API adapter | Submit/read permission by environment and resource; protected channel outside explicit local mode | Validate issuer/channel, audience, expiry, environment; client credential cannot become component credential | Fail closed; first slice has only an effective loopback host route, is single-developer, and uses one shared synthetic scope |
| Operator → administration | Distinct operator/security principal with stronger authentication class | Action/resource/environment permission, reason, approval, separation of duties | Short session, replay-resistant privileged operation, no shared admin credential | Fail closed and durably audit; no administrative interface in first slice |
| Workflow API/Orchestrator → PostgreSQL | Stable Orchestrator component principal with database credential | Only Orchestrator schemas/operations; protected connection | Credential scoped to environment and runtime, never migration/owner rights | Component not ready for writes; database audit/recovery evidence; selected logically |
| Agent → Agent persistence | Stable Agent deployment principal | Only its declared Agent data boundary | Separate from Orchestrator and other deployments; rotation overlap | Agent not ready/admitted; receipt/outcome evidence; selected logically |
| Orchestrator → Event Bus | Broker or protected-channel authentication establishes the transport principal; adapter policy maps it to expected Orchestrator class | Produce commands, consume terminal events only in environment | Broker ACL plus trusted-channel, contract, target, and domain checks; envelope/header claims never authenticate | Stop affected publication/consumption; outbox/inbox evidence; validate both brokers that expose and conceal producer identity |
| Agent → Event Bus | Broker or protected-channel authentication establishes the Agent transport principal where exposed | Consume intended command subscription; produce terminal events only | Scope by environment, channel, expected logical producer and `agent_id`; stable IDs distinguish redelivery | Fail admission/publication; when producer identity is not exposed, ACLs restrict before delivery and consumers validate configured channel plus domain semantics |
| Orchestrator → readiness | Generated development credential authenticates the Orchestrator to the Agent; the Orchestrator does not cryptographically authenticate the Agent in the first slice | Credential grants only `readiness.query`; bounded endpoint verification checks the configured loopback route, response contract, environment, `agent_id`, declaration digest, freshness/timeout, and safe response; production requires mutually authenticated, environment-bound, cryptographically protected component identities | Development/environment binding, rate limits, and credential separation from API/database/bus/telemetry; endpoint verification does not prove that the responder controls a credential-backed Agent principal | Agent becomes unavailable on failure; credential generated/injected outside source and removed at teardown; a local process can still take over the configured route or port |
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

For messaging, the authenticated transport principal established by broker
authentication or an equivalent protected-channel adapter is the runtime
identity source. Platform policy maps that principal to an expected logical
producer class and permissions. Payload `producer`, arbitrary headers, target
`agent_id`, topic, consumer-group membership, and trace context are claims or
routing data, not authentication.

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
development environment, an effective host route restricted to loopback, a
synthetic nonportable `local-development` principal, only workflow submit/read
permissions, and a visible reduced-security warning.

Deployment validation distinguishes the process or container listener,
container network reachability, host publication, reverse proxy or forwarding,
and the effective routes that result. A development container may listen on
`0.0.0.0:8080` internally and publish `127.0.0.1:8080` on the host only when:

- host publication is restricted to loopback, with no wildcard, LAN, public,
  or other external route;
- no reverse proxy, port forward, or equivalent route exposes the API;
- untrusted containers and processes cannot reach the container network;
- no production route or credential is present; and
- deployment and startup validation confirm effective exposure, not merely
  the container listener address.

A host listener on `0.0.0.0`, LAN or public reachability, an externally
reachable container network, reverse-proxy or forwarding exposure, shared-host
or multi-user use, and externally reachable CI remain prohibited.

All callers in this boundary are indistinguishable and share one ownership and
idempotency scope. It is suitable only for isolated single-developer Vertical
Slice 01 use, not a shared workstation, LAN, multi-user CI service, or
production-like environment. Access from another machine, shared host, CI
runner, or LAN requires an explicit development credential or future API
authentication adapter.

Startup refuses the synthetic policy when the environment is not development,
the effective host route is not restricted to loopback, an untrusted process
or container can reach the container network, forwarded/proxied traffic could
expose it, production credentials or routes are present, or it receives
administrative or sensitive-diagnostic permissions. It uses no client
credential or identity provider and is not proof that a local caller is a
particular human.

### 11. API Authorization and Workflow Ownership

Workflow acceptance durably records owner principal/security-domain reference,
`idempotency_scope_id`, environment, authorization decision, and policy
revision with the accepted request and workflow. The submitter receives read
permission through ownership, not merely because submission permission exists.
Additional principals may read only through explicit resource policy,
delegation, or operator permission.

Equivalent accepted-request replay requires the same idempotency security
scope and current permission to view the workflow. A request conflict reveals
no existing workflow data. Retrieval checks authorization before returning
content. Unauthorized and nonexistent workflows use the same safe external
response where policy requires enumeration resistance. Knowing
`workflow_id`, `request_id`, or `correlation_id` grants nothing. Correlation
group lookup authorizes every returned workflow or filters it without leaking
membership.

In local-development mode, every caller resolves to the same synthetic
principal and `idempotency_scope_id`. Those callers may read and replay every
workflow owned by that synthetic scope; no individual developer attribution or
isolation exists.

### 12. Request Idempotency and Security Context

The trusted API security adapter creates or resolves a normalized
`idempotency_scope_id`. It is stable across credential rotation,
environment-scoped, nonsecret, not directly controlled by arbitrary client
input, and able to represent an API client, machine principal, individual
principal, or tenant/security domain according to the accepted client model.
It is durably stored with accepted-request evidence.

`idempotency_scope_id` is never inferred from `request_id`, workflow ID,
correlation ID, token text, session ID, transient credential ID, or another
possession-only value. The target multi-principal uniqueness key is logically:

`environment + idempotency_scope_id + operation + request_id`.

Operation separates request families. The canonical request fingerprint remains
independently validated:

- same scope, operation, and `request_id` with an equivalent fingerprint
  returns existing identifiers and currently authorized state;
- the same key with a conflicting fingerprint returns the stable safe conflict;
- a different scope may use the same `request_id` without discovering or
  blocking the first mapping;
- credential rotation preserves scope and replay behavior;
- principal disablement preserves durable mapping/evidence but denies replay
  disclosure unless an explicit current permission applies;
- scope migration is an explicit versioned, audited migration that preserves
  old lookup/compatibility and cannot silently reassign ownership;
- an operator retrieves under operator permission and audit policy rather than
  changing or impersonating the idempotency scope; and
- local-development requests use one synthetic scope that cannot later be
  claimed by a production identity.

ADR-0004 and current ADR-0006/Vertical Slice language instead require global
uniqueness by `request_id`. ADR-0010 remains Proposed until those decisions are
formally amended or superseded to define API contract semantics, the
accepted-request key, persistence uniqueness, replay lookup, conflict behavior,
migration/compatibility, and security-safe external errors. The single-scope
first slice retains existing behavior until then.

### 13. Human User and Operator Separation

Normal API users own or receive explicit workflow access. Support/read-only
operators receive bounded diagnostic and workflow read permissions. Platform
operators manage runtime/Registry/recovery actions. Security administrators
manage policy and credentials. Deployment automation promotes artifacts.
Database administrators administer storage but do not gain application
impersonation. One person may hold multiple assignments, but each action uses
the effective role and separation-of-duties rules.

The synthetic local-development principal is not a human-user or operator
identity and provides no individual attribution. It receives no administrative
or sensitive-diagnostic permission.

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

Admission validates the trusted adapter's authenticated transport principal,
its policy mapping to the expected Orchestrator producer class, channel and
environment authorization, target `agent_id`, declaration digest,
capability/version, contract, workflow/task/attempt/message relationships,
deadline, deduplication, and effective policy. Payload or header producer claims
never replace that security context.

Ordinary expiry/rotation and deployment disablement preserve historical
selection and follow Section 30. Emergency revocation blocks commands not yet
admitted once its revision is known and explicitly governs future steps of
in-flight work. No revocation event alone proves cancellation or creates an
unsupported business failure.

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
domain services validate the intersection of authenticated transport principal,
channel/environment authorization, expected logical producer class, portable
contract, target/capability rules, and durable message identity/deduplication.

When a broker exposes authenticated producer identity to the trusted consumer
adapter, that identity participates directly in consumer-side validation. When
it does not, ACLs restrict production before delivery and the consumer
validates the configured trusted channel plus message/domain semantics; the
consumer must not claim access to producer credentials or connection identity
it was not given. Consumer-group membership, topic name, payload `producer`,
arbitrary headers, target `agent_id`, and trace context never establish
producer authority.

### 18. Message-Level Security

Consumers validate the exact contract and the available trusted transport/
adapter security context. Producer authorization is the intersection of
authenticated transport principal when exposed, channel/environment
authorization, expected logical producer class, portable envelope `producer`
claim,
target/capability rules, workflow/task/attempt/message identity,
correlation/causation relationships, timestamp/deadline, and deduplication.
The envelope producer and headers must agree with policy but cannot authenticate
the sender.

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

Only the Orchestrator readiness principal may query an Agent. Vertical Slice 01
uses an environment-scoped generated development credential, created outside
source control and injected through a protected file mount or equivalent
development secret boundary. It is separate from API, database, Event Bus, and
telemetry credentials; grants only `readiness.query`; identifies the expected
Orchestrator development component class; is validated by the Agent; is
replaceable without changing logical identity; is removed at teardown; and is
never accepted outside development.

The first slice uses one-way credential authentication: the Agent
authenticates the Orchestrator by validating the generated readiness
credential. The credential prevents unauthorized readiness callers from
receiving a response, but it does not prove the identity of the responder to
the Orchestrator.

The Orchestrator instead performs **bounded development-only Agent endpoint
verification**. It checks the configured loopback route, expected response
contract, environment, configured `agent_id`, declaration digest,
freshness/timeout, and safe response. These checks do not prove that the
responder controls a credential-backed Agent principal. A local process that
takes over the configured route or port can still impersonate the endpoint.
This residual risk is accepted only for isolated single-developer
development. Production requires mutually authenticated, environment-bound,
cryptographically protected component identities.

Unauthorized callers receive no capability, dependency, endpoint, credential,
or detailed health data. Caller-authentication failure or an endpoint
contract, environment, `agent_id`, digest, freshness, or timeout mismatch makes
that Agent unavailable for new selection without making workflow queries
unavailable. Unauthenticated readiness is never a production option.

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

UUID domain identifiers are designed to be globally collision-resistant, and
their canonical lowercase text is only a serialization rule—not an identity or
security property. Possession or encoded value confers no authority.
`agent_id`, `workflow_id`, `request_id`, and `correlation_id` may be globally
collision-resistant but are always authorization-scoped by environment and
security context.

The unauthenticated local API boundary exists only in isolated single-developer
development. Isolation is based on effective reachability, not the process or
container listener alone. A container-internal wildcard listener is allowed
only when host publication is loopback-only, the container network is
inaccessible to untrusted containers and processes, and no proxy, forward,
external route, production route, or production credential exists. Host
wildcard listeners, externally reachable container networks, shared hosts,
LAN/externally reachable CI access, and forwarded or proxied traffic require
authenticated isolation rather than the synthetic principal.

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

The first-slice readiness credential is generated outside source control,
injected through a protected file-mounted or equivalent development boundary,
scoped only to `readiness.query`, isolated from every other credential class,
and removed during teardown. It is rejected outside development.

### 24. Credential Lifecycle

Every credential class has an owner and documented issuance, distribution,
activation, validation, expiry, planned rotation, overlap, revocation,
emergency revocation, compromise response, destruction, and audit process.

Rolling rotation makes old and new credentials valid for a bounded overlap:
deploy validators/trust first, issue and activate new credentials, migrate
clients, verify, revoke old credentials, then remove old trust. Rotation does
not require synchronized restart or logical identity change. Shared credentials
across components or environments are prohibited.

Ordinary expiry or rotation prevents new authenticated connections after the
bounded validation window, does not reinterpret committed workflow selection,
does not automatically fail running work, and permits already admitted work to
finish while its authenticated execution context remains valid under the
recorded policy. Deployment disablement prevents new Registry selection but
does not rewrite accepted attempts and may allow dispatched work to drain.

Emergency revocation is a separate explicit, versioned, durably audited policy
action. It records revision, reason, actor, target, environment, and effective
time and selects behavior for not-yet-admitted commands, new dependency calls,
cooperative cancellation, safe completion, future-outcome quarantine, and
operator reconciliation. Compromise may bypass normal overlap, but neither
credential disappearance nor lifecycle shutdown proves an irreversible effect
was cancelled or justifies an unsupported `TaskFailed`.

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
still validates the trusted adapter context, expected logical producer, target,
capability, contract, environment, and attempt. If the broker exposes the
authenticated producer principal, the consumer adapter validates it directly;
otherwise consumer enforcement relies on pre-delivery ACLs, the configured
trusted channel, and domain semantics without inventing unavailable connection
identity. Persistence grants limit damage if application checks fail. No
single gateway or perimeter is authoritative for every action.

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

The authoritative runtime producer identity is the transport principal exposed
by broker authentication or equivalent protected-channel context. A normalized
header may describe that established context but cannot create it. When the
broker does not expose producer identity to consumers, no header or payload
field upgrades the configured trusted channel into per-message authentication.

### 30. Authorization at Agent Execution

Before admission, the Agent checks the trusted adapter security context and
available authenticated transport principal, expected logical producer,
intended `agent_id`, environment, declaration/capability/version, command
contract, attempt/message relationships, deadline, deployment
revocation/disablement, security classification, and recorded/current policy
rules. Payload or trace producer claims cannot satisfy this check.

A valid credential with wrong target or undeclared capability is rejected and
audited. Declaration changes and ordinary policy changes after dispatch do not
silently reinterpret an accepted command: the recorded
selection/declaration/policy revision remains historical authority.

At admission, the Agent checks the current emergency-revocation revision.
Not-yet-admitted commands are rejected when the revision requires it. For
already admitted work, that versioned policy explicitly chooses among stopping
new dependency calls, requesting cooperative cancellation, allowing safe
completion, quarantining future outcomes, or requiring reconciliation.

Cancellation, fencing, receipt, outcome, and acknowledgment follow ADR-0007.
There is no claim that an irreversible external effect was cancelled without
evidence. Process credential loss or lifecycle shutdown before a committed
outcome does not alone create durable `TaskFailed`. An authoritative outcome
committed before revocation remains valid unless a separate integrity process
determines otherwise. Stale replicas fail new admission once they cannot prove
an allowed security revision.

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
revocation is explicit, versioned, audited, and may override only the future
execution steps its policy names. Acceptance preserves the historical decision;
admission validates current emergency state. Ordinary credential expiry after
admission does not automatically invalidate that execution context.

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

Emergency revocation records policy revision, actor, reason, target,
environment, effective time, selected treatment of pending/in-flight/outcome
work, and reconciliation responsibility. Existing authoritative outcomes are
not rewritten by revocation.

### 33. Failure Behavior

| Failure | Behavior |
| --- | --- |
| API authentication/authorization failure | Fail closed with safe indistinguishable response where needed; never create workflow |
| Accepted-request lookup in another `idempotency_scope_id` | Treat as a separate scope without disclosure; current global ADR semantics block multi-principal production until reconciled |
| Identity provider/key unavailable | Never become anonymous; locally verifiable unexpired cached evidence may serve allowed reads within policy, otherwise fail closed |
| Ordinary component credential expiry/rotation | Stop new connections after the bounded window; admitted work may finish under recorded policy; liveness may remain true while affected readiness is false |
| Emergency revocation | Reject future admission and apply the recorded policy to future steps; never infer cancellation or business failure without ADR-0007 evidence |
| Database/Event Bus authentication or authorization | Stop affected writes/consumption/publication; preserve outbox/inbox state and expose not-ready; never trust envelope/header identity as fallback |
| Readiness authentication | Agent unavailable for new selection; workflow queries remain available |
| Invalid Registry provenance/policy unavailable/ambiguous | No activation or new selection/submission requiring it; retain last explicitly valid revision only within bounded policy |
| Audit unavailable | Business mutation rolls back; privileged action fails closed or records unknown external outcome and reconciles under ADR-0009 |
| Environment mismatch/spoofed Agent | Reject, security-audit, contain credential/channel, and require operator review |
| Clock outside skew | Reject time-sensitive credential/action; do not infer order; operator remediation |
| Break-glass unavailable | No implicit superuser fallback; use normal recovery or declare incident |

Security classification and operational log severity are independent. An
isolated contained integrity conflict is normally an operational error;
repeated, cross-record, systemic, or corruption-indicating integrity failure
may become a critical security/correctness incident.

Accepted workflow queries may operate in degraded read-only mode only with
locally verifiable principal, current read permission, and available
authoritative persistence. Accepted replay still requires current
authentication and disclosure authorization. Already-dispatched work follows
its recorded decision plus explicit emergency revocation rules. A valid outcome
committed before revocation remains authoritative; credential loss or
lifecycle shutdown alone creates no business failure. Liveness never implies
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
window is documented and never described as immediate unless proven. Ordinary
expiry/rotation may favor safe drain; emergency revocation may reduce
availability by rejecting admission, dependency calls, or outcomes exactly as
its audited policy specifies.

### 35. Administrative Actions

Registry activation/rollback, capability enable/disable, Agent drain/revoke,
credential rotation, policy activation, schema migration, restore, retention
override, quarantine redrive, outbox disposition, data repair, and future
break-glass require strong authenticated principal, semantic permission,
environment confirmation, reason, approval where required, preview/dry run
where safe, idempotency, and durable evidence.

Emergency revocation is an administrative policy action with explicit revision,
reason, actor, target, environment, effective time, approval where required,
and declared handling for admission, dependencies, cooperative cancellation,
completion, outcomes, and reconciliation.

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
| Spoofed readiness | Development credential authenticates the Orchestrator to the Agent; bounded endpoint verification checks route, response contract, environment, `agent_id`, digest, freshness/timeout, and safe response | Contract/environment/identity/digest/route/freshness mismatch | Mark unavailable, replace credential/route | The Orchestrator does not cryptographically authenticate the Agent; a local process can take over the route or port, accepted only in isolated single-developer development |
| Unauthorized Registry change | Git review, provenance, approval, digest | Activation/audit mismatch | Reject/rollback revision | Trusted pipeline compromise |
| Cross-environment routing | Separate credentials, ACLs, policy | Crossover security event | Reject, isolate, revoke, reconcile | Misconfiguration availability loss |
| Forged producer | Broker authentication/ACL, trusted adapter context, logical producer/domain checks | Transport/channel/claim mismatch | Reject/quarantine, revoke | Some brokers do not expose per-message producer identity to consumers |
| Replayed API request | Adapter-resolved idempotency scope, fingerprint, authentication | Replay/conflict/scope audit | Return existing safely or treat different scope independently | Global-key conflict until ADR-0004/ADR-0006 are reconciled |
| Replayed message | Immutable ID, inbox/receipt, target/auth | Duplicate/conflict disposition | Deduplicate/quarantine | Stolen valid credential within scope |
| Trace spoofing | ADR-0009 trust limits | Sanitization/drop metrics | Ignore context | Diagnostic confusion within accepted bounds |
| Secret leakage | No-contract/log rules, redaction, injection | Secret scanning once configured, audit | Revoke/rotate and purge safely | Detection may be delayed |
| Database misuse | Separate nonowner roles | Database/application audit | Revoke, isolate, restore/reconcile | Database-admin compromise |
| Poisoned configuration | Schema/provenance/digest/review | Startup/activation mismatch | Fail closed, rollback | Authorized malicious change |
| Supply-chain substitution | Pinning, provenance, review, controlled promotion | Artifact/digest/vulnerability checks | Block/rollback/rebuild | Upstream or build compromise |
| Denial of service | Bounds, rate limits, isolation | Saturation/security metrics | Shed/recover/scale within deployment | Availability remains attackable |
| Credential expiry or emergency revocation outage | Overlap rotation and explicit versioned emergency policy | Expiry/readiness/revision alerts | Rotate, drain, cancel safely, quarantine or reconcile as recorded | Emergency containment can reduce availability; irreversible effects remain uncertain |
| Policy rollback attack | Versioned approved activation | Revision/audit mismatch | Reject or restore approved revision | Compromised approver |
| Audit tampering | Append-only application behavior and access separation | Integrity/reconciliation checks | Isolate, restore, incident handling | Backend-admin compromise |
| Same-host lateral movement | Separate credentials/users/containers, no locality trust | Cross-principal access attempts | Revoke/redeploy/isolate host | Host-admin compromise |
| Untrusted local tooling | Effective loopback-only single-developer route, isolated container network, no proxy/forward or production routes/credentials | Visible mode and startup/deployment exposure validation | Stop, clean credentials/environment, remove route | Every permitted local caller shares all synthetic-scope workflows |

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
local principal and scope, an effective host route restricted to loopback,
visible warning, narrow submit/read permission, redacted logs, isolated
persistence/broker credentials, and cleanup on teardown. All callers are
indistinguishable and may read/replay workflows in that shared synthetic
ownership scope; there is no individual developer attribution.

This risk is accepted only for isolated single-developer Vertical Slice 01.
An internal container listener such as `0.0.0.0:8080` is allowed only with
host publication such as `127.0.0.1:8080`, no other effective route, no
proxy/forward, and a container network inaccessible to untrusted containers or
processes. Host wildcard, LAN, public, reverse-proxy, externally reachable
container-network, shared-workstation, shared-host, multi-user CI, and
externally reachable CI use is prohibited. Access from another machine, CI
runner, shared host, or LAN requires an explicit development API credential or
future authentication adapter.

Deployment and startup refuse the synthetic policy when the environment is
not development, effective exposure is not restricted to host loopback, an
untrusted process or container can reach the container network, forwarding or
proxying could expose the API, production credentials/routes are present, or
the synthetic policy has administrative or sensitive-diagnostic permissions.

Readiness uses its separate generated development credential, protected
injection, teardown removal, and bounded development-only Agent endpoint
verification. The Agent authenticates the Orchestrator; the Orchestrator checks
the route, response contract, environment, `agent_id`, declaration digest,
freshness/timeout, and safe response but does not cryptographically
authenticate the Agent. Fake identities/credentials support repeatable tests;
local convenience never becomes a production default.

### 42. Testing Strategy

Tests follow `docs/testing/README.md`:

- **Identity:** stable logical identity across restart, distinct deployments,
  process identity nonauthority, environment separation, missing/invalid
  principal, rotation.
- **API:** valid/missing/expired/wrong issuer-audience-environment credential,
  insufficient permission, owner/shared access, identifier guessing,
  same/different `idempotency_scope_id` replay, equivalent/conflicting
  fingerprint, rotation-stable scope, disablement, scope migration,
  operator retrieval, synthetic local scope, and changed authorization.
- **Agent/Registry:** trusted/tampered declaration, unauthorized activation,
  spoofed `agent_id`, digest mismatch, valid credential with undeclared
  capability, declared but unauthenticated Agent, stale policy.
- **Event Bus:** valid authenticated transport principal; correct payload
  producer with unauthorized transport principal; authorized channel with wrong
  logical producer claim; forged producer header; brokers that expose or hide
  producer identity; cross-environment and trace-carried false producer;
  wrong target; ACL plus domain enforcement; redelivery versus hostile replay.
- **Persistence:** least-privilege runtime, Agent/Orchestrator isolation,
  separate migration/backup/restore identities, credential failure and overlap.
- **Administration:** strong authentication, missing role/reason/approval,
  coupled-audit rollback, administrative audit failure/unknown outcome, future
  break-glass bounds.
- **Context/execution:** normalized principal, no raw token, policy revision,
  delegation fields, environment, Agent admission, decision timing; credential
  expires after admission; credential revoked before admission; deployment
  disabled after dispatch; emergency pre-execution rejection; cooperative
  cancellation;
  uncertain irreversible side effect; stale revocation revision; outcome
  committed before revocation; lifecycle shutdown without invented failure.
- **Failure:** unavailable identity/key/policy/secret/audit, revoked in-flight
  credential, skew, fail closed, selected read-only degradation.
- **Confidentiality:** no secret in logs/traces/Registry/messages, safe public
  errors, protected diagnostics and data classes.
- **Local/readiness:** generated credential scope/injection/removal and Agent
  authentication of the Orchestrator; proof that unauthorized callers receive
  no readiness response; bounded endpoint verification of configured loopback
  route, response contract, environment, `agent_id`, declaration digest,
  freshness/timeout, and safe response; explicit proof that this does not
  cryptographically authenticate the Agent; process/container listener versus
  host-publication validation; permitted container
  `0.0.0.0:8080` → host `127.0.0.1:8080`; rejection of host wildcard,
  LAN/public, proxy/forward, externally reachable container network, untrusted
  container/process network access, shared-host/multi-user, externally
  reachable CI, and production-route/credential configurations; effective
  route verification, shared synthetic ownership, and prohibited
  admin/sensitive permissions.

Fast tests use fake credentials and identities. Integration/resilience/security
tests are required to prove real certificate/token validation, broker ACLs,
database grants, network isolation, rotation/revocation timing, process and
cross-host behavior. Unit tests cannot prove those controls.

### 43. Technology Evaluation

All options can be adapted behind the normalized principal, authentication,
authorization, and secret ports. Product/provider types never cross them.

| Option | Fit for humans, machines, components, and local use | Portability, lifecycle, complexity, and decision |
| --- | --- | --- |
| Generated development credential | One-way machine/local caller authentication only; no human federation and no responder proof | Selected for first-slice readiness only: file-injected and `readiness.query` scoped, it authenticates the Orchestrator to the Agent but does not cryptographically authenticate the Agent to the Orchestrator; not selected for the first-slice API or production |
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
| File-mounted secrets | Good component/local injection | Portable/offline and permissionable; selected for the readiness credential or equivalent protected injection; rotation requires atomic mount/reload |
| Environment variables | Simple Docker/Windows/Linux/Unraid injection | Broad exposure to process/debug tooling and awkward rotation; bounded development fallback |
| Database roles | Strong persistence least privilege | Selected enforcement class; exact grants/schema ownership deferred to implementation |
| Event Bus ACLs | Strong channel-level defense | Selected enforcement class behind ADR-0005 adapter; exact ACL technology/configuration deferred |
| Application authorization | Understands semantic resources and context | Selected mandatory layer; local versioned policy initially, external engine not required |

The selected boundaries operate offline and on Windows, Linux, Docker, and
Unraid. Entra/cloud stores need connectivity; Keycloak, SPIRE, and Vault add
services unsuitable for the minimal one/two-machine slice. OAuth/OIDC and
SPIFFE preserve future migration through standards, but no provider, token,
PKI, workload-identity, or secret product is selected. The generated readiness
credential plus endpoint verification is a bounded development mechanism, not
mutual authentication or a production service identity standard.

### 44. Initial Vertical Slice Decision

Vertical Slice 01 uses:

- explicit development environment and stable local Orchestrator and Test Agent
  deployment identities, distinct from process IDs;
- `LocalDevelopmentAuthorizationPolicy` with no client credential, synthetic
  local principal and `idempotency_scope_id`, an effective host route
  restricted to loopback, visible warning, shared ownership/replay, and
  submit/read only; a container-internal wildcard listener is allowed only
  with loopback-only host publication, isolated container networking, and no
  proxy, forward, or other effective route;
- trusted Git/configuration-backed Registry with no Agent self-registration;
- distinct injected database and Event Bus credentials and logical
  producer/consumer permissions;
- application checks for expected producer, target `agent_id`,
  capability/version, contract, environment, and attempt;
- a generated, protected, file-injected development readiness credential,
  separate from every other credential and scoped only to `readiness.query`;
  the Agent authenticates the Orchestrator, while the Orchestrator performs
  bounded development-only Agent endpoint verification of the configured
  loopback route, response contract, environment, expected `agent_id`,
  declaration digest, freshness/timeout, and safe response without
  cryptographically authenticating the Agent;
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
  `environment + idempotency_scope_id + operation + request_id` once
  ADR-0004/ADR-0006 are formally amended or superseded;
- stable component principals with replaceable, scoped credentials;
- Registry/declaration trust intersected with authenticated Agent runtime;
- broker/database infrastructure controls plus independent domain checks;
- Event Bus producer authority derived from authenticated transport/adapter
  context when available, never payload or header claims;
- no initial message signing, provider-specific claims, raw token propagation,
  dynamic global policy engine, or enterprise identity product;
- versioned policy and durable principal/decision/audit evidence;
- bounded caches, explicit rotation overlap and revocation windows, no silent
  anonymous degradation;
- ordinary expiry/disablement preserving accepted history and explicit
  versioned emergency revocation governing future in-flight steps;
- separate business-coupled and administrative audit failure semantics under
  ADR-0009;
- no first-slice delegation or break-glass;
- classified data, protected channels, secret injection, and supply-chain
  provenance; and
- an explicit local-development exception that cannot start as production.

### 46. Security Guarantee and Evidence Table

| Guarantee | Authority/source | Credential/channel and validator | Permission/enforcement/scope | Staleness | Durable evidence | Failure and required test |
| --- | --- | --- | --- | --- | --- | --- |
| Authorized clients submit | Principal authority + active policy | Shared local-development context initially; future access credential validated by API | `workflow.submit`; API/Orchestrator; environment | Per request; cache bound | Accepted owner/scope/policy decision | No workflow; local-boundary and future credential tests |
| Retrieval controlled | Workflow owner/share + current policy | Authenticated request at API | `workflow.read`; workflow/environment | Per read | Access/denial audit where policy requires | Safe not-found; ownership/guessing tests |
| Replay cannot cross security scope | Adapter-resolved `idempotency_scope_id` + fingerprint policy | Authenticated/synthetic API context; API resolves scope | Environment/scope/operation/request key; API/Orchestrator | Stable across credential rotation | Mapping scope/fingerprint/revision | Separate scope without disclosure; equivalent/conflict/migration tests; ADR conflict blocks production |
| Only Orchestrator commands | Component principal + channel policy | Broker-exposed transport principal when available, otherwise pre-delivery ACL + configured trusted adapter channel | `command.produce`; expected logical producer/channel/environment plus domain checks | Credential/ACL cache bound | Orchestrator outbox + Agent receipt/rejection | Reject/quarantine; both broker-capability modes and forged claim tests |
| Intended Agent consumes | Agent principal + declaration | Broker credential validated by adapter and Agent | `command.consume`; channel/`agent_id`/environment | Credential/policy bound | Receipt/admission audit | Reject; wrong-agent/cross-env tests |
| Trusted Agent emits outcome | Agent principal + admitted attempt | Broker-exposed transport principal when available, otherwise ACL/trusted channel; Orchestrator validates domain claims | `terminal_event.produce`; expected Agent class/attempt/channel/env | Credential bound | Agent outcome/outbox + Orchestrator inbox | Reject/quarantine; unauthorized transport and forged producer tests |
| Agent cannot widen capability | Registry/deployment revision + policy | Authenticated Agent and validated command | Execute intersection; Agent admission | Recorded revision + emergency revocation | Selection/admission/outcome evidence | Reject; declared/authenticated mismatch tests |
| Registry activation controlled | Artifact provenance + admin policy | Automation/operator credential; loader validates | `registry.revision.manage`; environment | Immediate revision | Administrative audit | No activation; tamper/approval tests |
| First-slice readiness bounded | Generated credential proves the readiness caller is the expected development Orchestrator class; configured declaration supplies expected endpoint attributes | Agent validates the generated credential; Orchestrator verifies route, response contract, environment, `agent_id`, digest, freshness/timeout, and safe response but does not cryptographically authenticate the Agent | `readiness.query`; development only | Credential lifetime + short freshness | Caller-authentication and endpoint-verification evidence | Agent unavailable; credential/injection/scope/teardown, endpoint mismatch, and local route/port takeover tests |
| Environment crossover rejected | Environment trust policy | Every credential/adapter validates environment | All actions; all enforcement points | Credential/policy bound | Security crossover audit | Reject/contain; cross-env tests |
| Database least privilege | Database grants + component mapping | Database credential validated by PostgreSQL | Persistence permission/schema/env | Connection/credential bound | DB/application audit and records | Not-ready/denied; cross-schema tests |
| No secret in contracts/telemetry | Classification and emission policy | Boundary validators/redactors | No secret export; contract/telemetry adapters | Policy revision | Security audit for violations | Reject/drop/rotate; leakage tests |
| Rotation preserves continuity | Credential authority/lifecycle plan | Old/new credentials validated during overlap | Same principal/scope/env | Explicit overlap | Rotation audit | Rollback/recover; overlap tests |
| Revocation bounded without rewriting history | Credential authority + versioned emergency policy | Validators check current revision at connection/admission | Principal/credential/deployment/env and named future steps | Declared maximum window | Revocation revision/reason/actor/target/effect audit | Ordinary drain or explicit emergency action; pre/post-admission/cancellation/outcome tests |
| Admin actions attributable | Human/automation authority + approval policy | Strong credential validated at admin boundary | Semantic admin permission/resource/env | Per action/session bound | ADR-0009 admin audit | Fail closed/unknown reconcile; actor/approval tests |
| Audit failure prevents unrecorded mutation | Business state/audit or admin audit authority | Persistence/audit boundary validates durability | Mutation/admin permission | Transaction/action | Coupled or administrative evidence | Rollback or unknown reconciliation; audit outage tests |

### 47. Consequences

#### Positive Consequences

- Trust, identity, credentials, permissions, environment, and audit are
  explicit and independently testable.
- Compromise is constrained by component, channel, capability, and persistence
  scope.
- Provider-neutral security context permits future enterprise migration.
- Rotation, ordinary expiry/disablement, emergency revocation, replay, and
  restart behavior are defined.
- First-slice readiness has a concrete credential boundary instead of a
  deferred authentication requirement.

#### Negative Consequences

- Identity and policy evidence add storage, testing, and operational work.
- Local unauthenticated mode gives every local caller the same ownership and
  replay authority and is unusable on shared or remotely reachable hosts.
- Multiple enforcement layers can disagree and require careful diagnostics.
- Multi-principal `idempotency_scope_id` needs accepted API/persistence
  contract, migration, and error-semantics follow-up.

#### Migration Impact

No security implementation exists. Multi-principal production use requires
reconciling the `idempotency_scope_id` accepted-request key and compatibility,
adding normalized principal/policy evidence, and selecting production
credentials without changing domain identity.

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
drift. The first slice also manages generation, injection, replacement, and
teardown of the dedicated readiness credential.

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
| Network locality treated as trust | Validate effective reachability across listener, container network, host publication, proxy/forwarding, and routes; allow container-internal wildcard only with loopback host publication and isolation; refuse host wildcard, proxy/LAN/public/shared-host/externally reachable CI or container-network, and production exposure |
| Valid token treated as universal | Issuer/audience/environment/scope plus semantic permission |
| Request replay crosses security scopes | Trusted adapter resolves stable `idempotency_scope_id`; block multi-principal production until ADR-0004/ADR-0006 are reconciled |
| Workflow ID guessing | Authorization before disclosure and safe not-found |
| Overprivileged service credential | Separate DB/channel/action scopes and review |
| Credentials shared across environments | Separate issuance/trust/configuration and crossover rejection |
| Agent widens capability | Declaration/authenticated identity/policy intersection at admission |
| Unauthorized production | Authenticated transport principal or trusted channel, broker ACL, logical producer and domain checks |
| Broker capability overstated | Model separately whether consumer adapter receives producer identity; never invent connection identity |
| Producer claim/header treated as authentication | Treat payload, headers, topic, group, `agent_id`, and trace as claims only |
| Broker ACL considered sufficient | Repeat contract, target, capability, environment, logical producer, and identity validation |
| Readiness spoofing | Dedicated credential authenticates only the Orchestrator caller; bounded endpoint verification checks route/contract/environment/`agent_id`/digest/freshness/safe response, while explicitly accepting local route or port takeover risk only in isolated single-developer development |
| Registry tampering | Git review, provenance, complete revision, digest, approval |
| Stale credential/policy cache | Maximum age, readiness, fail closed, visible revocation window |
| Revocation delay or unsupported cancellation | Versioned emergency action defines admission/dependency/cancellation/completion/outcome/reconciliation; no inferred failure |
| Rotation outage | Old/new overlap, staged validation, rollback |
| Secret leakage | Injection, prohibition, redaction tests, immediate rotation |
| Development bypass reaches production | Deployment/startup validate effective exposure and refuse nondevelopment, host wildcard, external container-network, proxy/forwarding, shared/remote, production routes/credentials, and privileged synthetic policy |
| Shared local principal leaks workflows | Restrict to isolated single developer; authenticated adapter required for shared/remote access |
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
  API principal/`idempotency_scope_id`, one Orchestrator, and one Test Agent
  deployment on an isolated single-developer boundary whose only effective host
  API route is loopback.
- A container-internal wildcard listener is permitted only with loopback-only
  host publication, no proxy/forward/external route, and a container network
  inaccessible to untrusted containers and processes.
- The development deployment can generate, protect, inject, replace, and remove
  a readiness-only credential outside source control.
- That readiness credential authenticates the Orchestrator to the Agent only.
  Orchestrator endpoint verification does not cryptographically authenticate
  the Agent, and a local process may take over the configured route or port.
- PostgreSQL and the Event Bus can enforce distinct logical credentials and
  permissions selected in their accepted ADRs.
- Deployment can inject secrets outside source control.
- Host/container/network controls exist but are not authoritative identity.
- Identity provider, authorization server, gateway, CA/PKI, secrets manager,
  service mesh, SIEM, workload-identity platform, multi-tenancy, final human
  model, and production topology remain unresolved.

### 50. Open Questions

1. How will formal ADR-0004/ADR-0006 amendment or supersession define
   `idempotency_scope_id`, accepted-request uniqueness, replay/conflict
   behavior, persistence lookup, migration/compatibility, and safe external
   errors? This is the only remaining blocker to accepting ADR-0010.
2. What environment-bound, cryptographically protected mutual component
   authentication mechanism replaces the one-way readiness credential and
   bounded endpoint verification for production?
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
- [ ] First-slice unauthenticated API is single-developer, has only an effective
      loopback host route and one shared synthetic scope, and cannot start with
      production routes/credentials or privileged permissions.
- [ ] Effective exposure validation distinguishes process/container listener,
      container network reachability, host publication, proxy/forwarding, and
      the resulting routes.
- [ ] A container-internal `0.0.0.0:8080` listener is permitted only with host
      publication on `127.0.0.1:8080`, no other effective route, no
      proxy/forward, and no untrusted container or process network access.
- [ ] Future API access uses access credentials, never ID tokens as access
      tokens.
- [ ] Workflow ownership, sharing, safe not-found, and correlation-group access
      are explicit.
- [ ] `idempotency_scope_id` is trusted-adapter-resolved, stable across
      credential rotation, nonsecret, environment scoped, durably stored, and
      never derived from client/domain/session/credential identifiers.
- [ ] Equivalent, conflicting, different-scope, disablement, scope-migration,
      operator, and local-development replay semantics are explicit.
- [ ] The accepted-request conflict with ADR-0004/ADR-0006 is the only blocker
      to ADR-0010 acceptance and remains so until `idempotency_scope_id`,
      accepted-request uniqueness, replay/conflict behavior, persistence
      lookup, migration/compatibility, and safe external errors are formally
      amended or superseded.
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
- [ ] Runtime producer authority comes from authenticated transport/adapter
      context; envelope/header/topic/group/`agent_id`/trace claims never
      authenticate.
- [ ] Broker modes that expose or hide producer identity are modeled without
      claiming unavailable consumer-side credential context.
- [ ] Message validation, redelivery, hostile replay, and no-signing decision
      are clear.
- [ ] First-slice readiness uses a generated, protected, readiness-only
      development credential that the Agent validates to authenticate the
      Orchestrator and that unauthorized callers cannot use to obtain a
      readiness response.
- [ ] The Orchestrator performs bounded development-only Agent endpoint
      verification of the configured loopback route, response contract,
      environment, `agent_id`, declaration digest, freshness/timeout, and safe
      response, without claiming cryptographic Agent authentication.
- [ ] The accepted readiness residual risk—that a local process can take over
      the configured route or port—is isolated to single-developer
      development; production requires mutually authenticated,
      environment-bound, cryptographically protected component identities.
- [ ] Registry author/provenance/approval/activation/rollback trust is explicit.
- [ ] Environment credentials, data, Registry, bus, policy, and approval are
      isolated.
- [ ] Runtime, migration, backup, restore, read-only, and admin persistence
      identities are distinct.
- [ ] Secrets never enter source, contracts, messages, Registry, telemetry, or
      images.
- [ ] Credential issuance, overlap rotation, revocation, compromise, and
      destruction are defined.
- [ ] Ordinary expiry/rotation and deployment disablement preserve accepted
      history and permit safe admitted-work drain where policy allows.
- [ ] Token validation includes issuer, audience, type, time, algorithm,
      environment, principal, scope, and revocation policy.
- [ ] API, credential, message, readiness, activation, and rotation replay
      controls are explicit.
- [ ] Delegation/impersonation is unsupported initially and future context is
      attributable.
- [ ] Decision and enforcement points repeat critical checks in depth.
- [ ] Security context uses normalized references and no bearer credentials.
- [ ] Emergency revocation is versioned/audited and explicitly selects
      rejection, dependency stop, cooperative cancellation, safe completion,
      outcome quarantine, or reconciliation.
- [ ] Agent admission and in-flight revocation align with ADR-0007 and never
      infer cancellation, external-effect reversal, or `TaskFailed` without
      authoritative evidence.
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
- [ ] Local development refuses host wildcard, LAN/public, proxy/forward,
      externally reachable container-network, untrusted container/process
      network access, shared-host/multi-user, externally reachable CI,
      production credential/route, and privileged synthetic policy
      configurations.
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
