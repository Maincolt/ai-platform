# ADR-0011: Principal-Scoped API Idempotency and Accepted-Request Ownership

- **Status:** Proposed
- **Date:** 2026-07-28
- **Supersedes:** Upon acceptance, only the global `request_id` uniqueness and
  related replay assumptions identified in Section 16 of ADR-0004 and ADR-0006
- **Superseded by:** None

## Context

ADR-0004 defines `request_id` as the identity of one logical workflow
submission. It requires the accepted-request mapping and workflow to be
created atomically and uniquely by `request_id`. ADR-0006 carries that decision
into persistence through a database uniqueness constraint, replay lookup, the
workflow-submission transaction, and a guarantee of one workflow per accepted
`request_id`.

Those decisions implicitly assume one API principal and one authorization
scope. Under that assumption, a globally unique `request_id` is sufficient to
find the only possible accepted request, and returning a conflict or existing
workflow cannot disclose another principal's data.

ADR-0010 introduces authenticated principals, authorization, workflow
ownership, principal isolation, credential rotation, and future security
domains or tenants. It proposes the logical accepted-request key:

`environment + idempotency_scope_id + operation + request_id`.

The decisions therefore conflict:

| Subject | ADR-0004 and ADR-0006 | ADR-0010 |
| --- | --- | --- |
| Accepted-request identity | Globally unique `request_id` | Security-scoped composite identity |
| Replay lookup | Lookup by `request_id` | Lookup only inside a trusted internal idempotency scope |
| Duplicate use by another principal | Conflict with the global mapping | Independent request when the scopes differ |
| Ownership and disclosure | Not part of idempotency identity | Authorization must prevent cross-owner discovery |
| Credential lifecycle | Not represented | Rotation must preserve replay while disablement may deny disclosure |
| Persistence uniqueness | Unique `request_id` | Unique environment, operation, scope, and `request_id` |

Globally unique `request_id` is no longer sufficient or secure. A guessed
identifier could otherwise reveal that another principal submitted a request,
block the guesser's legitimate request, or return another principal's workflow
identifiers. This ADR resolves only that inconsistency. It does not change the
wire format, fingerprint semantics unrelated to version identity, workflow
state model, transaction grouping, persistence technology, authentication
provider, authorization model, or audit architecture.

## Purpose

This ADR defines the authoritative architecture for accepted-request identity,
API idempotency and replay, request and workflow ownership, authorization and
disclosure, persistence uniqueness, request-fingerprint identity, principal
lifecycle, and migration from the earlier global request model.

It narrowly amends ADR-0004 and ADR-0006. Until this ADR is Accepted, their
global uniqueness rules remain binding and multi-principal production API use
remains blocked as described by ADR-0010.

## Decision Drivers

The decision is evaluated against:

- correctness before convenience;
- deterministic replay and conflict classification;
- replay safety and principal isolation;
- authorization correctness and least privilege;
- stable ownership independent of credential representation;
- stability across credential rotation and principal lifecycle changes;
- persistence simplicity and enforceable uniqueness;
- safe migration and historical compatibility;
- prevention of identifier discovery across ownership boundaries;
- durable, attributable audit evidence;
- future security-domain and tenant evolution; and
- backward compatibility where it does not weaken correctness or isolation.

## Decision

### 1. Accepted-Request Identity

The evaluated candidates are:

| Candidate | Advantages | Disadvantages and rejection rationale |
| --- | --- | --- |
| Globally unique `request_id` | Smallest key and matches the original single-principal model | Allows one principal to collide with, discover, or block another; rejected for multi-principal use |
| `request_id` plus principal | Strong per-principal isolation | Couples replay to the current principal representation and does not naturally support shared API clients, security domains, ownership transfer, or tenant evolution |
| `request_id` plus tenant | Natural shared tenant replay | Assumes tenancy before it is architecturally selected and is too broad for individually isolated clients |
| `request_id` plus API client | Stable for machine integrations | Does not cover human principals, shared security domains, or clients whose credentials and registrations change |
| `request_id` plus security domain | Supports organization-level sharing | May be broader than intended and still assumes one future ownership model |
| Normalized idempotency scope | Separates replay partitioning from credentials, principals, roles, owners, and future tenant representation | Adds internal mapping, persistence, lifecycle, migration, and audit responsibilities |

The selected logical accepted-request identity is:

`(environment, operation, idempotency_scope_id, request_id)`.

All four values are required for identity and uniqueness:

- `environment` is trusted deployment/security context, not client input;
- `operation` is a stable, version-aware semantic API operation identity
  resolved by the API adapter, not an arbitrary URL or client-supplied value;
- `idempotency_scope_id` is the trusted internal replay partition described in
  Section 2; and
- `request_id` remains the client-visible identity for one intended submission
  within that partition.

The request fingerprint is not part of the uniqueness key. It determines
whether reuse of an existing key is an equivalent replay or a conflict.
`workflow_id` and `correlation_id` are also not accepted-request identity.

The current Workflow API has one workflow-submission operation. A future
operation or incompatible operation generation receives a distinct stable
operation identity when sharing `request_id` values could otherwise create
false replay equivalence.

### 2. `idempotency_scope_id`

`idempotency_scope_id` is a stable, opaque internal identifier used only to
partition accepted-request identity and replay.

It is:

- internal to the trusted API, Orchestrator, and accepted-request persistence
  boundary;
- never supplied, selected, overridden, or learned by an API client;
- not a principal, credential, role, tenant, owner, security domain,
  authorization policy, or authorization grant;
- not derived from `request_id`, `workflow_id`, `correlation_id`, token text,
  session ID, credential ID, transient process identity, or another
  possession-only value;
- not portable in public API, event, command, Agent, Registry, or telemetry
  contracts; and
- nonsecret but protected as internal security metadata.

After successful authentication, the trusted API security adapter resolves the
normalized principal and active security policy to one stable replay
partition. On first authorized provisioning of that partition, the trusted
adapter boundary creates an opaque platform identifier and durably associates
it with the stable normalized subject or security-domain mapping selected by
policy. Creation and concurrent first resolution are atomic. Subsequent
requests look up the persisted mapping; they do not regenerate the identifier.

The selected mapping may represent one human principal, machine principal, API
client, or deliberately shared security domain. Sharing is explicit policy,
not an inference from equal roles, tenant-looking claims, email domains,
credential issuers, or request contents.

The scope must:

- remain stable for the lifetime of accepted requests in that replay
  partition;
- survive credential refresh, key rotation, certificate renewal, provider
  token changes, and replacement credentials that preserve the normalized
  principal mapping;
- remain durably reserved when a principal is disabled or deleted so
  historical identity cannot be reassigned;
- use a tombstoned historical mapping rather than recycling an identifier;
- be changed, split, merged, or aliased only by an explicit versioned and
  audited migration;
- retain enough historical resolution information to replay every retained
  accepted request under its original key; and
- record creation, mapping revision, migration, disablement effect, and
  administrative actor or policy evidence without storing credentials.

The first local-development slice uses one explicit synthetic
`idempotency_scope_id` for its one synthetic principal. That scope can never be
claimed, inherited, or silently converted into a production principal's
scope.

### 3. API Contract

Clients remain unaware of `idempotency_scope_id`.

The external API continues to expose only:

- `request_id`;
- `correlation_id`; and
- `workflow_id`.

No scope identifier, owner persistence reference, principal mapping, or
fingerprint version becomes a public field. Existing request and success
representations remain unchanged.

ADR-0004 response semantics are refined as follows:

- a new key produces `202 Accepted` after successful atomic acceptance;
- an equivalent replay in the same key returns the existing identifiers and
  currently authorized workflow state with `200 OK`;
- a conflicting fingerprint in the same key returns the stable safe
  `REQUEST_ID_CONFLICT` response only when revealing that classification is
  authorized under Section 8;
- the same `request_id` in another scope is unrelated and may create another
  workflow; and
- authentication, authorization, unavailable-Agent, validation, and
  pre-acceptance rejection rules remain unchanged.

API problem responses never include the internal key, scope, owner,
fingerprint, mapping history, or another principal's identifiers.

### 4. Accepted-Request Key and Uniqueness

The authoritative logical persistence key and database-enforced uniqueness
boundary is:

`(environment, operation, idempotency_scope_id, request_id)`.

Uniqueness applies to the complete tuple, not to `request_id` alone and not to
`(principal_id, request_id)`.

Replay lookup must receive environment, operation, and
`idempotency_scope_id` from trusted adapter context. Client data can supply
only `request_id`. A normal API lookup never searches all scopes and then
filters the result; scope is part of the lookup predicate and authorization
boundary from the start.

Concurrent first submissions for the same complete key arbitrate through
database uniqueness. The transaction loser reads the committed mapping inside
that same trusted key and applies the historical fingerprint comparison.
Different scopes may concurrently accept the same `request_id`.

The accepted-request mapping and workflow remain one integrity unit. No
accepted key may identify two workflows, no workflow created by submission may
lack its accepted mapping, and no retained mapping may point to a missing
workflow or insufficient replay tombstone.

Physical column, index, constraint, and repository method names are
implementation details. Their semantics must enforce the logical key.

### 5. Request Fingerprint

ADR-0004 remains authoritative for semantic request projection, default
materialization, RFC 8785 canonicalization, SHA-256 digesting, excluded
transport/correlation data, and safe historical comparison.

An accepted replay requires all of:

- the same environment;
- the same stable operation identity;
- the same `idempotency_scope_id`;
- the same `request_id`; and
- an equivalent fingerprint evaluated under the accepted request's historical
  fingerprint profile.

The operation is checked in both the accepted-request key and the fingerprint
profile's semantic definition. This intentional defense prevents one
operation's request body from being treated as another operation's replay.

The same complete key with a different fingerprint is a conflict. A matching
fingerprint in a different key is not a replay. Fingerprints never grant
authorization and cannot be used to search across scopes.

### 6. Fingerprint Versioning

Every accepted request stores an immutable fingerprint and the immutable
`fingerprint_policy_version` required by ADR-0004. That version resolves a
complete historical profile containing:

- the semantic fingerprint-policy version, including included fields,
  normalization, default materialization, and operation meaning;
- the canonical serialization version and profile;
- the digest algorithm version and parameters; and
- any compatibility adapter needed to evaluate later representations against
  that historical profile.

This ADR does not replace ADR-0004's version concept. It clarifies that one
`fingerprint_policy_version` must explicitly resolve all three dimensions. An
implementation may persist their identifiers within one referenced profile or
as additional fields, provided the historical profile remains unambiguous,
immutable, and recoverable.

Replay always evaluates the incoming validated request using the stored
historical profile. Stored fingerprints are never silently recomputed or
rewritten after an upgrade. A new semantic policy, canonical serialization
rule, or digest algorithm creates a new `fingerprint_policy_version` for new
acceptances while historical profiles remain supported for the full
replay-retention horizon.

A compatibility adapter may translate a later representation into historical
semantics, but it cannot reinterpret the original request. If the historical
profile or required adapter is unavailable, ambiguous, or unsafe, replay fails
closed and no second workflow is created.

Migration may add explicit version metadata to older mappings, but only when
the exact historical ADR-0004 behavior is known. Ambiguous historical
fingerprints are quarantined for operator reconciliation rather than assigned
an assumed version.

### 7. Ownership Model

Accepted-request ownership and workflow ownership are recorded together at
acceptance and refer to the same normalized authorization subject. The owner
may be an individual principal or an explicitly modeled security-domain
subject according to active policy.

The durable ownership evidence contains:

- the stable owner subject reference and subject category;
- the owner environment and applicable security-domain scope;
- the authenticated submitter/actor reference when different from the owner;
- the authorization decision and policy revision that permitted acceptance;
  and
- immutable original-owner evidence plus additive ownership-change history.

Ownership is independent of access-token text, key ID, session, certificate,
provider token subject syntax, or any other credential representation.
Credential rotation and replacement therefore do not transfer or recreate
ownership.

Ownership grants no authority by itself. Current authorization policy decides
whether an owner, delegated principal, shared-domain member, or operator may
read or administer the workflow.

An ownership transfer is an explicit authorized administrative or domain
operation. It changes current ownership and records the previous owner, new
owner, actor, reason, approval where required, policy revision, and effective
time. It does not silently change the accepted-request key or
`idempotency_scope_id`.

Future tenant support maps a stable tenant/security-domain subject into the
same ownership model. It does not redefine `request_id` or expose
`idempotency_scope_id`.

### 8. Disclosure Rules

Workflow ownership controls disclosure. Idempotency scope controls the replay
partition. They are related evidence but are never interchangeable.

The API applies these rules:

- lookup in another `idempotency_scope_id` is not performed for a normal
  request and another scope's existence is not disclosed;
- the same `request_id` in another scope is treated as new within the caller's
  scope;
- an equivalent replay returns identifiers and state only after current
  authorization permits workflow disclosure;
- a fingerprint conflict returns no existing workflow, owner, scope,
  fingerprint, acceptance time, or security evidence;
- when the caller lacks permission to learn that a same-scope mapping exists,
  equivalent and conflicting cases use the same safe authorization/not-found
  behavior required by policy and do not create a second workflow;
- unauthorized and nonexistent workflow retrieval remain externally
  indistinguishable where enumeration resistance is required; and
- an operator may cross ownership boundaries only through an explicit
  permission and auditable operator path.

The platform does not claim perfect timing-side-channel elimination. It does
require normalized errors, bounded response detail, no cross-scope identifiers,
and tests that prevent direct existence disclosure.

### 9. Replay Semantics

| Situation | Required behavior |
| --- | --- |
| Same scope, operation, `request_id`, and fingerprint | Return existing identifiers and current state only if currently authorized; never create another workflow |
| Same scope, operation, and `request_id`, different fingerprint | Return safe `REQUEST_ID_CONFLICT` only when authorized to learn the mapping classification; never create another workflow |
| Different scope, same operation and `request_id` | Treat as an independent identity without discovering or blocking the first scope |
| Same scope and `request_id`, different operation | Treat as a different accepted-request identity; operation-specific authorization and validation still apply |
| Credential rotation or replacement | Resolve the same scope and ownership; replay behavior is unchanged |
| Principal disablement | Retain mapping, ownership, fingerprint, and audit; deny new submission or replay disclosure unless an explicit current policy permits it |
| Principal deletion | Tombstone the principal/scope mapping; never recycle the scope; historical records remain interpretable and inaccessible without authorized recovery |
| Ownership transfer | Change current disclosure authority, not the original accepted-request key; a new owner's normal request in another scope is not automatically a replay |
| Scope migration | Preserve the original key and resolve only through explicit versioned aliases or mapping history; preflight collisions and fail closed on ambiguity |
| Operator replay or retrieval | Use explicit operator permission and durable audit; never impersonate the original scope or silently change ownership |
| Future tenant migration | Explicitly migrate ownership and scope mappings, preserve original key/history, check collisions, and retain historical replay compatibility |
| Historical fingerprint profile unavailable | Fail closed without creating another workflow |
| Lost original API response | Retry in the same resolved scope returns the committed workflow when fingerprint and authorization checks pass |

Operator access does not turn an operator's normal `POST` into a replay of
another scope. Any future administrative replay operation is a distinct
authorized operation and is out of scope as an API contract here.

### 10. Persistence Model

The authoritative logical accepted-request record stores at minimum:

- `request_id`;
- environment;
- stable operation identity;
- `idempotency_scope_id`;
- immutable request fingerprint;
- `fingerprint_policy_version`, resolving semantic policy,
  canonical serialization, and digest algorithm versions;
- current owner subject reference and owner scope;
- immutable original-owner and authenticated acceptance-actor references;
- normalized security evidence, including authorization decision/policy
  revision and scope-mapping revision, without raw credentials;
- workflow reference and initial acceptance result;
- acceptance time and correlation reference needed for audit; and
- migration, tombstone, or compatibility references needed to preserve
  historical lookup.

The accepted-request mapping, workflow, task, first attempt, logical
transitions, and command outbox keep the ADR-0006 ownership and transaction
boundaries. Scope mapping is created or resolved in its own atomic trusted
security-adapter persistence boundary before submission arbitration. An unused
scope mapping is harmless reserved identity; it grants no authority and is
retained under its lifecycle policy. Database details remain outside the
domain.

ADR-0006's workflow-submission transaction is refined only at its first step:
it creates or resolves the unique complete accepted-request key and historical
fingerprint profile rather than a globally unique `request_id`. The remaining
workflow, task, transition, snapshot, and outbox steps are unchanged.

Persistence lookup ports accept trusted environment, operation, scope, and
`request_id` context. They do not expose global-by-`request_id` lookup to the
normal API path. Cross-scope search is restricted to explicitly authorized
migration, reconciliation, or operator capabilities.

Accepted-request retention remains at least as long as the API duplicate
horizon and workflow-retention obligation. A tombstone must preserve the
complete key, fingerprint profile, owner/security evidence required for safe
disclosure, workflow or terminal replay reference, and migration history.

### 11. Audit

Audit aligns with ADR-0009 and remains separate from operational logs and
traces.

Durable evidence is required for:

- first acceptance, including complete accepted-request key references,
  fingerprint version, owner, authenticated actor, authorization decision,
  policy revision, workflow reference, and outcome;
- equivalent replay, including actor, resolved scope reference, operation,
  request reference, fingerprint profile, authorization outcome, and returned
  or denied disposition;
- conflicting replay, including safe fingerprint/profile references,
  authorization/disclosure outcome, and no raw request content;
- scope creation, aliasing, split, merge, migration, disablement effect, and
  tombstone;
- ownership transfer or tenant migration, including previous/new owner, actor,
  reason, approval where required, policy revision, and effective time; and
- operator lookup, override, replay, repair, or migration action.

Acceptance evidence commits with the accepted-request and workflow transaction.
Ownership or scope mutation and their business audit commit together or
neither commits. Equivalent replay and conflict evidence must be durable before
existing identifiers or a mapping-specific conflict classification is
disclosed; if required audit is unavailable, the request fails safely without
creating or changing a workflow.

Privileged operator or migration actions use ADR-0009 administrative security
audit. They fail closed when the action can still be stopped. Corrections are
additive; audit history, original ownership, original key, and historical
fingerprint evidence are never rewritten.

Logs and traces may reference safe identifiers but cannot replace this audit.
Raw credentials, token claims, full workflow input, raw request bodies, and
fingerprint source material are excluded.

### 12. Authorization

The security adapter must authenticate the caller, authorize the semantic
operation, and resolve trusted environment and `idempotency_scope_id` before
accepted-request lookup or creation.

Authorization responsibilities are:

- `idempotency_scope_id` partitions replay and uniqueness;
- workflow ownership and current policy control disclosure;
- operation permission controls submission or operator action;
- environment limits every decision;
- fingerprint comparison classifies content but grants no permission; and
- operator or migration permission permits narrowly scoped cross-owner access
  without converting the operator into the owner or idempotency principal.

No permission is inferred from knowledge of `request_id`, `workflow_id`,
`correlation_id`, fingerprint, scope, tenant-looking claim, or owner reference.
An idempotency scope must never appear as the authenticated principal in policy
or audit.

### 13. Principal Lifecycle

Principal and credential lifecycle follow these rules:

- credential refresh, rotation, renewal, and like-for-like replacement retain
  the normalized principal, owner, and `idempotency_scope_id`;
- principal disablement prevents new actions and replay disclosure under
  ordinary policy but preserves accepted mappings and ownership evidence;
- re-enablement of the same stable principal restores the same scope mapping
  subject to current policy;
- principal deletion creates a durable tombstone and never frees the scope or
  owner reference for reuse;
- a replacement that represents a different principal does not inherit scope
  or ownership merely because it uses the same name, email, client label, role,
  or credential issuer;
- ownership transfer changes authorization ownership through an explicit
  audited operation but does not rekey historical accepted requests;
- scope migration changes replay resolution only through an explicit,
  versioned, collision-checked, audited mapping;
- tenant migration coordinates scope mapping, current ownership, authorization
  policy, and historical aliases without rewriting original evidence; and
- historical accepted requests remain valid records even when no current
  principal may retrieve them.

Deletion, disablement, or transfer never makes an accepted `request_id`
available for reuse inside its retained original key.

### 14. Migration from the Global Request Model

The external API is backward compatible: clients continue sending
`request_id` and receiving `request_id`, `correlation_id`, and `workflow_id`.
The behavioral change is that the same `request_id` may be accepted
independently in different trusted scopes.

The logical migration sequence is:

1. Add trusted environment, stable operation, `idempotency_scope_id`, complete
   fingerprint-version, ownership, and security-evidence capabilities without
   removing the global key.
2. Create durable scope mappings. Existing single-principal local-development
   records map to an explicit legacy synthetic scope for their known
   environment and workflow-submission operation.
3. Backfill historical owner and fingerprint-version evidence only from
   authoritative deployment, contract, and acceptance facts. Ambiguous records
   are blocked for reconciliation rather than guessed.
4. Validate that every retained accepted mapping has a complete composite key,
   fingerprint profile, owner reference, and workflow/tombstone integrity.
5. Add and verify composite uniqueness and scoped lookup behavior while a
   compatibility deployment can still read the earlier model.
6. Deploy scoped arbitration and dual-version historical replay support before
   permitting multi-principal submissions.
7. Remove the global `request_id` uniqueness requirement only after all active
   components use the scoped model and rollback no longer depends on it.
8. Retain migration revision, alias/tombstone, collision, and reconciliation
   evidence for the historical replay horizon.

If no schema or accepted-request data exists when implementation begins, the
initial schema implements the composite model directly and records that no
data migration was required.

An environment containing records whose original principal, environment,
operation, or fingerprint profile cannot be established must not enable
multi-principal acceptance. Recovery requires an authorized, audited
classification or isolation decision.

Rollback must not discard new-scope mappings or accept duplicate workflows.
Once different scopes have accepted the same `request_id`, software that
assumes global lookup is incompatible and cannot safely be restored without an
explicit compatibility plan.

### 15. Consequences

#### Positive Consequences

- One principal or security scope cannot block or discover another by guessing
  `request_id`.
- Replay identity survives credential rotation without making credentials part
  of persistence keys.
- Ownership and replay partitioning have separate, testable meanings.
- Database uniqueness still arbitrates concurrent first acceptance.
- Existing public API fields and request fingerprints remain compatible.
- Historical fingerprint behavior becomes explicit across semantic,
  serialization, and digest evolution.
- Future tenant/security-domain models can be introduced without redefining
  `request_id`.

#### Negative Consequences

- Scope mappings, ownership evidence, composite uniqueness, historical
  fingerprint profiles, and migrations add storage and application complexity.
- Shared scopes require careful policy because one member can consume a
  `request_id` for the whole scope even when disclosure is denied.
- Ownership transfer does not automatically transfer replay lookup; a separate
  scope migration may be required.
- Durable replay/conflict audit adds write load to otherwise read-oriented
  requests.
- Rollback becomes constrained after duplicate `request_id` values exist in
  different scopes.

#### Migration Impact

- Global uniqueness is replaced by composite uniqueness after additive
  backfill and compatibility validation.
- Existing single-principal records receive a known legacy synthetic scope and
  ownership only when authoritative facts support that mapping.
- Historical fingerprint metadata may require explicit profile backfill.
- Multi-principal API enablement waits until scoped lookup, uniqueness,
  disclosure, audit, and rollback compatibility are proven.

#### Developer Impact

- API code receives scope only from trusted security context.
- Domain logic keeps ownership, authorization, fingerprint, and idempotency
  concepts separate.
- Persistence adapters must classify scoped equivalent replay, scoped
  conflict, unauthorized hidden mapping, and new request deterministically.
- Tests require multiple principals, scopes, operations, credential versions,
  ownership changes, fingerprint profiles, and migration states.

#### Operational Impact

- Operators manage scope and owner mappings, migration revisions, ambiguous
  historical rows, audit retention, and collision reconciliation.
- Scope split, merge, transfer, and tenant migration are privileged changes,
  not direct database edits.
- Deployments must prevent rollback to globally scoped software after
  cross-scope duplicate identifiers exist.

#### Security Impact

- Identifier confidentiality and principal isolation improve.
- Scope mapping and operator migration become privileged trust boundaries.
- Incorrectly broad shared scopes can cause denial of service within that
  scope, although they do not authorize workflow disclosure.
- Audit and retention contain protected ownership and security metadata.

### 16. Amendments to ADR-0004 and ADR-0006

Upon acceptance, this ADR supersedes only the following earlier requirements.
Every unrelated decision in ADR-0004 and ADR-0006 remains Accepted and
unchanged.

#### ADR-0004 Amendments

- Section 6's statement that `request_id` identifies one logical submission is
  scoped to one `(environment, operation, idempotency_scope_id)` partition.
  Client generation, omission behavior, format, and immutability remain
  unchanged.
- Section 8 submission replay and conflict behavior applies only after trusted
  scoped lookup and current disclosure authorization. The same `request_id` in
  another scope is independent.
- Section 12's global unique mapping and "never two workflows for one accepted
  `request_id`" language becomes one workflow per complete accepted-request
  key. Its semantic fingerprint, canonicalization, historical-policy, and
  conflict rules remain; Section 6 clarifies the information resolved by its
  existing `fingerprint_policy_version`.
- Section 9's `REQUEST_ID_CONFLICT` remains stable but cannot disclose another
  owner or scope. Authorization may require a non-disclosing response instead.
- No API wire field, JSON Schema authority, identifier encoding, error format,
  message contract, or other contract decision changes.

#### ADR-0006 Amendments

- Section 1's accepted-request record gains environment, operation,
  `idempotency_scope_id`, complete fingerprint version, owner, and normalized
  security evidence.
- Section 5's submission transaction resolves the composite accepted-request
  key rather than a globally unique `request_id`; its atomic workflow, task,
  transitions, snapshot, and outbox behavior is unchanged.
- Section 11's unique `request_id` within the Orchestrator acceptance domain is
  replaced by uniqueness of
  `(environment, operation, idempotency_scope_id, request_id)`.
- Section 12's reservation, lookup, equivalence, conflict, retention, and
  tombstone rules apply within that complete key and current disclosure
  authorization.
- Section 30's guarantee becomes one workflow per complete accepted-request
  key, not per globally unique `request_id`.
- Section 31's migration preservation requirements include scope, ownership,
  security evidence, and complete fingerprint-version history.
- PostgreSQL, persistence ownership, transaction isolation, repository
  boundaries, state transitions, outbox/inbox behavior, recovery, retention,
  backup, and every unrelated persistence decision remain unchanged.

### 17. Security Guarantee and Evidence Table

| Guarantee | Authoritative source | Enforcement point | Durable audit evidence | Failure behavior | Required tests |
| --- | --- | --- | --- | --- | --- |
| Accepted replay is deterministic | Complete accepted-request key plus stored historical fingerprint profile | API security adapter, Orchestrator arbitration, persistence uniqueness | Acceptance and replay disposition with key/profile references | Fail closed; never create a second workflow | Equivalent, conflicting, concurrent, lost-response, and unavailable-profile tests |
| Ownership isolation controls disclosure | Current owner and versioned authorization policy | Workflow API and authorization port | Owner, actor, policy revision, allowed/denied disposition | Safe denial/not-found; no identifiers returned | Owner, delegate, shared-domain, disabled-owner, and unauthorized tests |
| Identifier confidentiality crosses no scope | Trusted scoped lookup and safe error policy | API adapter and accepted-request repository | Cross-scope attempt classification without other-scope data | Treat caller's scope independently or deny safely | Same `request_id` across scopes, guessing, conflict, and timing-shape tests |
| Principals cannot collide accidentally | Adapter-resolved scope mapping plus composite uniqueness | Security adapter and database constraint | Scope creation/mapping revision and acceptance | Transaction conflict resolved only inside the same complete key | Multi-principal concurrent-acceptance and broad-scope misconfiguration tests |
| Credential rotation preserves replay | Stable principal-to-scope and owner mapping | Authentication/security adapter | Credential lifecycle reference and unchanged scope mapping | Deny if mapping is ambiguous; never create a replacement scope silently | Token/key/certificate rotation and replacement tests |
| Historical replay survives evolution | Immutable original key, fingerprint profile, aliases, and tombstones | Compatibility adapter and persistence lookup | Profile/migration revision and replay disposition | Fail closed without duplicate creation | Old semantic/default/canonical/digest profile and retained-tombstone tests |
| Operator access is explicit | Operator permission, target, reason, and approval policy | Administrative/recovery boundary | ADR-0009 actor/action/target/reason/outcome evidence | Fail closed; no impersonation or ownership mutation | Authorized/unauthorized operator lookup, replay, transfer, and audit-outage tests |
| Migration preserves compatibility | Reviewed migration revision and validated backfill | Deployment migration boundary and startup compatibility check | Backfill counts, ambiguity/collision disposition, activation and rollback evidence | Block multi-principal startup or rollback on ambiguity | Empty, legacy, ambiguous, collision, mixed-version, and rollback tests |

### 18. Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| Global `request_id` uniqueness survives accidentally | Remove it only through reviewed migration; require composite constraint and cross-scope concurrency tests |
| Identifier guessing reveals another request | Scope the lookup before persistence access, authorize disclosure, and normalize safe errors |
| Ownership leaks through replay or conflict | Return identifiers/classification only when authorized; store no owner or scope in public problems |
| Ownership is derived from a credential | Persist stable normalized owner subject and original actor; credential lifecycle never rewrites ownership |
| Fingerprint evolution creates false replay or conflict | Store immutable semantic, canonicalization, and digest profile identity; retain historical adapters |
| Scope migration creates duplicate or unreachable mappings | Preserve original keys, use explicit aliases/history, preflight collisions, audit, and fail closed on ambiguity |
| Tenant evolution broadens a scope silently | Require explicit policy and migration; never infer tenant sharing from provider claims or roles |
| Operator misuse crosses ownership boundaries | Separate permission, reason/approval, durable audit, no impersonation, and least-privilege recovery port |
| Historical replay meaning is ambiguous | Preserve immutable profile and original key evidence; quarantine unresolved legacy records |
| Shared scope member consumes an identifier | Make sharing deliberate, authorize disclosure independently, and use scoped client policy |
| Principal deletion permits identity reuse | Tombstone principal/scope mappings and prohibit identifier recycling |
| Rollback software assumes global uniqueness | Compatibility gate deployment and prohibit unsafe rollback after cross-scope duplicates exist |
| Audit outage hides replay or mutation | Commit business mutation with audit and fail safely before mapping-specific disclosure |
| Scope is mistaken for an authorization principal | Keep it internal, exclude it from policy principal fields, and test authorization independently |

### 19. Open Questions

The architectural model is complete. These implementation choices remain:

1. What physical table, column, index, and uniqueness-constraint names
   represent the logical model?
2. What migration tool and exact expand-and-contract sequence implement the
   additive backfill and compatibility gate?
3. Is the complete fingerprint version stored as one profile reference or as
   separate semantic-policy, canonical-serialization, and digest-algorithm
   fields?
4. What exact canonical fingerprint-profile identifiers and compatibility
   artifact format are used?
5. What exact ADR-0009 business and administrative audit record schemas store
   acceptance, replay, conflict, ownership, scope migration, and operator
   evidence?
6. What bounded retention and rate controls apply to replay and conflict audit
   records?
7. What repository query names and database transaction statements implement
   scoped arbitration without exposing global lookup to the API path?

These choices cannot weaken the complete key, internal-scope boundary,
ownership/disclosure separation, historical fingerprint behavior, audit
durability, or migration guarantees.

### 20. Acceptance Checklist

- [ ] ADR-0004/ADR-0006 single-principal and global-`request_id` assumptions are
      explicitly identified.
- [ ] Accepted-request identity is
      `(environment, operation, idempotency_scope_id, request_id)`.
- [ ] Every key element comes from the correct trusted or client boundary.
- [ ] Database uniqueness and concurrent arbitration apply to the complete
      key, not global `request_id`.
- [ ] `idempotency_scope_id` is internal, opaque, stable, adapter-resolved, and
      never client supplied.
- [ ] Idempotency scope is not a principal, role, tenant, owner, credential, or
      authorization policy.
- [ ] Scope creation, credential rotation, disablement, deletion, migration,
      tombstone, and audit behavior are explicit.
- [ ] Public API fields remain limited to `request_id`, `correlation_id`, and
      `workflow_id`.
- [ ] Equivalent replay requires the same complete key and historical
      fingerprint profile.
- [ ] Conflicting fingerprints never create another workflow.
- [ ] Different scopes may use the same `request_id` without discovery or
      blocking.
- [ ] Credential rotation preserves scope, ownership, and replay.
- [ ] Principal disablement/deletion preserves history while denying
      unauthorized disclosure.
- [ ] Ownership and original actor are stable normalized references independent
      of credentials.
- [ ] Ownership transfer and tenant migration are explicit, versioned, and
      audited without silently rekeying accepted requests.
- [ ] Workflow ownership controls disclosure; idempotency scope controls replay
      partitioning.
- [ ] Unauthorized equivalent and conflict cases do not reveal mapping
      existence or identifiers.
- [ ] Operator access requires separate permission and audit and never
      impersonates the target scope.
- [ ] `fingerprint_policy_version` explicitly resolves semantic policy,
      canonical serialization, digest algorithm, compatibility, and
      fail-closed history.
- [ ] The accepted-request persistence record contains the complete key,
      fingerprint/profile, owner, security evidence, workflow reference, and
      migration history.
- [ ] Acceptance, replay, conflict, ownership migration, scope migration, and
      operator override have durable ADR-0009-aligned evidence.
- [ ] The migration preserves existing API fields and known historical
      semantics and does not guess ambiguous ownership or fingerprint data.
- [ ] Composite uniqueness is proven before global uniqueness is removed.
- [ ] Mixed-version startup and rollback are blocked when they could create
      duplicates or misroute replay.
- [ ] ADR-0004 amendments are limited to request identity and scoped
      replay/conflict/disclosure; existing fingerprint versioning is clarified,
      not replaced.
- [ ] ADR-0006 amendments are limited to accepted-request persistence,
      uniqueness, transaction lookup, guarantee wording, and migration.
- [ ] No unrelated API, contract, persistence, workflow, Event Bus,
      authentication, authorization, or audit architecture changes.
- [ ] ADR-0010's idempotency, ownership, disclosure, lifecycle, and safe-error
      requirements are satisfied.
- [ ] Remaining questions are implementation choices and do not leave the
      architectural model undecided.

The architectural model in this ADR is internally complete. If ADR-0011 is
Accepted, it resolves the sole accepted-request scope blocker identified by
ADR-0010. ADR-0010 may then move through acceptance review without another
idempotency architecture decision, provided its own remaining checklist is
approved.

## Related Decisions

- [ADR-0004: API and Contract Standards](ADR-0004-api-and-contract-standards.md)
- [ADR-0006: Persistence, State, and Recovery](ADR-0006-persistence-state-and-recovery.md)
- [ADR-0009: Observability, Telemetry, and Audit Correlation](ADR-0009-observability-telemetry-and-audit-correlation.md)
- [ADR-0010: Security, Identity, Authorization, and Trust Boundaries](ADR-0010-security-identity-authorization-and-trust-boundaries.md)

## References

- [Architecture overview](../README.md)
- [Vertical Slice 01](../../implementation/vertical-slice-01.md)
- [Testing strategy](../../testing/README.md)
- [Security policy](../../../SECURITY.md)
- [Agent guidance](../../../AGENTS.md)
