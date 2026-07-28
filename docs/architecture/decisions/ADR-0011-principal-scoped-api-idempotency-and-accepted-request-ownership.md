# ADR-0011: Principal-Scoped API Idempotency and Accepted-Request Ownership

- **Status:** Accepted
- **Date:** 2026-07-28
- **Supersedes:** Only the global `request_id` uniqueness and
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

It narrowly amends ADR-0004 and ADR-0006. Its acceptance supersedes their
global uniqueness rules only as identified in Section 16 and resolves the
multi-principal accepted-request blocker described by ADR-0010.

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
- `operation` is a stable semantic command identity resolved from trusted
  application/API configuration, not client input or a technical route;
- `idempotency_scope_id` is the trusted internal replay partition described in
  Section 2; and
- `request_id` remains the client-visible identity for one intended submission
  within that partition.

Five normalized references have separate meanings:

- `idempotency_scope_id` partitions accepted-request uniqueness and replay;
- `acceptance_actor_id` identifies the authenticated actor whose request caused
  the original acceptance;
- `current_actor_id` identifies the authenticated actor of the current API or
  administrative request;
- `accepted_owner_subject_id` identifies the owner intent resolved and
  authorized at original acceptance; and
- `current_owner_subject_id` identifies the workflow owner after zero or more
  explicit ownership transfers.

These references may resolve to the same subject, but they are not required to.
Equality is an authorization-policy result, never a persistence invariant. A
service or API client may be authorized to submit for another owner, and a
tenant- or client-scoped replay partition may coexist with user-level workflow
ownership. No actor or owner identity is inferred from
`idempotency_scope_id`.

The request fingerprint is not part of the uniqueness key. It determines
whether reuse of an existing key is an equivalent replay or a conflict.
`workflow_id` and `correlation_id` are also not accepted-request identity.

The current Workflow API has the semantic `workflow.submit` operation.
Compatible API or schema evolution retains that identity; request-shape
evolution is normally handled by `fingerprint_policy_version`. For example,
`POST /v1/workflows` and `POST /v2/workflows` may both resolve to
`workflow.submit` when they represent the same logical submission. A genuinely
independent `workflow.simulate` command uses a different operation identity.

Operation identity is not derived directly from a URL, HTTP path, handler name,
media type, deployment version, or API-version string. Aliases between old and
new routes may resolve to the same semantic operation. A new identity is
introduced only when the platform intentionally defines an independently
idempotent business operation. Changing it requires explicit contract review,
migration, and compatibility analysis and must never be used merely to avoid
an existing request conflict.

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
authenticated principal and active security policy to one stable replay
partition. On first authorized provisioning of that partition, the trusted
adapter boundary creates an opaque platform identifier and durably associates
it with the replay-scope mapping selected by policy. Creation and concurrent
first resolution are atomic. Subsequent requests look up the persisted
mapping; they do not regenerate the identifier.

The selected mapping may represent a shared API client, machine integration,
individual security scope, or deliberately shared security domain. Sharing is
explicit policy, not an inference from equal roles, tenant-looking claims,
email domains, credential issuers, owners, actors, or request contents. It does
not itself grant disclosure or workflow authority.

The scope must:

- remain stable for the lifetime of accepted requests in that replay
  partition;
- survive credential refresh, key rotation, certificate renewal, provider
  token changes, and replacement credentials that preserve the trusted
  replay-scope mapping;
- remain durably reserved when its mapped subject is disabled or deleted so
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

The original complete accepted-request key is immutable. A scope migration or
alias is an internal, versioned lookup-resolution rule, not a rewrite of that
historical identity. Every record retains its original environment, operation,
scope, and `request_id`, with exactly one canonical accepted-request record for
each historical complete key.

Alias resolution is deterministic, environment-scoped, and audited. Aliases
are never public. Cycles are prohibited; chains are bounded or normalized to
one canonical target. Conflicting or ambiguous aliases fail closed. Split,
merge, and tenant migrations preflight collisions and cannot make two
historical workflows canonical for one resolved replay identity. Multiple
active scopes cannot silently acquire replay rights to one historical key.
Ownership transfer creates no alias, and scope migration transfers no
ownership unless a separate authorized ownership operation is included.

### 3. API Contract

Clients remain unaware of `idempotency_scope_id`.

The external API continues to expose only:

- `request_id`;
- `correlation_id`; and
- `workflow_id`.

No scope identifier, owner persistence reference, principal mapping, or
fingerprint version becomes a public field. Existing request and success
representations remain unchanged.

Routes and API versions are adapters for the configured semantic operation.
Compatible aliases such as `POST /v1/workflows` and `POST /v2/workflows` may
both resolve to `workflow.submit`; route or version changes do not themselves
create a new idempotency partition.

ADR-0004 response semantics are refined as follows:

- a new key produces `202 Accepted` after successful atomic acceptance;
- an equivalent replay in the same key returns the existing identifiers and
  currently authorized workflow state with `200 OK` only when resolved owner
  intent also matches the immutable accepted owner intent;
- a conflicting fingerprint in the same key returns the stable safe
  `REQUEST_ID_CONFLICT` response only when revealing that classification is
  authorized under Section 8;
- an owner-intent mismatch returns a safe non-disclosing authorization or
  request-conflict response according to policy, never the existing workflow;
- the same `request_id` in another scope is unrelated and may create another
  workflow; and
- authentication, authorization, unavailable-Agent, validation, and
  pre-acceptance rejection rules remain unchanged.

API problem responses never include the internal key, scope, owner,
fingerprint, mapping history, or another principal's identifiers.
`OWNER_INTENT_MISMATCH` is a stable internal classification. It remains
internal when a distinct public error would weaken enumeration resistance.

### 4. Accepted-Request Key and Uniqueness

The authoritative logical persistence key and database-enforced uniqueness
boundary is:

`(environment, operation, idempotency_scope_id, request_id)`.

Uniqueness applies to the complete tuple, not to `request_id` alone and not to
`(principal_id, request_id)`.

Replay lookup must receive environment, operation, and
`idempotency_scope_id` from trusted adapter context. Client data can supply
only `request_id`. Operation comes from trusted application/API configuration,
not the URL, handler, media type, deployment version, API-version string, or
client choice. A normal API lookup never searches all scopes and then filters
the result; scope is part of the lookup predicate and authorization boundary
from the start.

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
  fingerprint profile; and
- the same resolved owner intent as immutable `accepted_owner_subject_id`,
  after any explicit replay-right migration rule has been applied.

The operation is checked in both the accepted-request key and the fingerprint
profile's semantic definition. Compatible request-shape evolution stays under
the same semantic operation and is compared through the historical
`fingerprint_policy_version`. A genuinely independent business operation uses
a separate identity. This prevents one operation's request body from being
treated as another operation's replay without using route or schema changes to
evade a conflict.

The same complete key with a different fingerprint is a conflict. A matching
fingerprint with different resolved owner intent is also not an equivalent
replay. Owner intent is an explicit replay-equivalence dimension but is not
part of database uniqueness. A matching fingerprint in a different key is not
a replay. Fingerprints never grant authorization and cannot be used to search
across scopes.

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

A fingerprint-policy change does not change or rekey the semantic operation.
Introducing a new operation identity is a separate contract decision with
explicit migration and compatibility analysis.

A compatibility adapter may translate a later representation into historical
semantics, but it cannot reinterpret the original request. If the historical
profile or required adapter is unavailable, ambiguous, or unsafe, replay fails
closed and no second workflow is created.

Migration may add explicit version metadata to older mappings, but only when
the exact historical ADR-0004 behavior is known. Ambiguous historical
fingerprints are quarantined for operator reconciliation rather than assigned
an assumed version.

### 7. Ownership Model

The model uses five independent normalized references:

| Reference | Meaning | Authority |
| --- | --- | --- |
| `idempotency_scope_id` | Internal uniqueness and replay partition | Trusted API security adapter and scope-mapping policy |
| `acceptance_actor_id` | Authenticated actor whose request caused original acceptance | Immutable authentication evidence recorded once at acceptance |
| `current_actor_id` | Authenticated actor making the current API or administrative request | Authentication evidence resolved independently for each call |
| `accepted_owner_subject_id` | Owner intent resolved and authorized for the original submission | Immutable acceptance evidence |
| `current_owner_subject_id` | Current workflow owner after explicit transfers | Current ownership policy and transfer history |

An owner subject may represent an individual principal, business subject, or
explicitly modeled security-domain subject. Owner identity controls no access
by itself; current authorization policy interprets current ownership for
disclosure and administration. Accepted and current owner may differ from the
subject represented by the replay scope and from either actor.

`acceptance_actor_id` records who submitted the request. It is immutable
acceptance evidence, set once on first acceptance to that call's
`current_actor_id`. It is never overwritten by replay, retrieval, ownership or
scope transfer, migration, operator access, or recovery. It does not represent
the caller of later requests.

`current_actor_id` is resolved independently on every API or administrative
call. It drives current authorization, disclosure, replay, conflict, operator,
and migration decisions. It may equal or differ from `acceptance_actor_id` and
is not part of immutable accepted-request identity or a durable property of
the accepted-request record.

Before accepted-request arbitration, the trusted authorization/application
boundary resolves the owner subject for whom `current_actor_id` is attempting
the submission. This **resolved owner intent** is not trusted merely because a
client supplied or guessed an identifier. Current policy must permit the actor
to submit for that owner. Owner intent may equal the current actor or differ
for delegated, machine-to-user, shared-client, or domain-level submissions.
On first acceptance it becomes immutable `accepted_owner_subject_id`; current
ownership initially receives the same value. This ADR adds no public owner
field.

Durable evidence retains:

- immutable `accepted_owner_subject_id` and owner subject category;
- current `current_owner_subject_id` and applicable ownership scope;
- immutable `acceptance_actor_id`;
- environment;
- authorization decision and policy revision;
- scope-mapping revision; and
- reason, delegation, approval, and additive ownership-change evidence where
  applicable.

Scope, accepted owner, current owner, original actor, and current actor may
resolve to the same subject, but equality is a policy result rather than a
storage invariant. A service actor may submit for an authorized user or
business owner. A shared client or tenant replay scope may contain workflows
with distinct user-level accepted and current owners.

Ownership is independent of access-token text, key ID, session, certificate,
provider token subject syntax, or any other credential representation.
Credential rotation and replacement therefore do not transfer or recreate
ownership.

Ownership grants no authority by itself. Current authorization policy decides
whether an owner, delegated principal, shared-domain member, or operator may
read or administer the workflow.

An ownership transfer is an explicit authorized administrative or domain
operation. It changes `current_owner_subject_id`, current disclosure, and
administrative authority and records the previous owner, new owner,
`current_actor_id`, reason, approval where required, policy revision, and
effective time. The accepted-request current-owner reference, workflow
ownership, ownership history, and coupled audit change atomically or none
changes.

Transfer does not change `accepted_owner_subject_id`, `acceptance_actor_id`,
the accepted-request key, original fingerprint, or `idempotency_scope_id`.
Replay with the original accepted owner intent remains subject to current
authorization. Replay using the new current owner as owner intent is not
automatically equivalent to the historical submission. Deliberate transfer of
replay rights requires a separate explicit, versioned, collision-checked, and
audited scope/request migration rule.

A scope migration does not change accepted or current ownership unless a
separate authorized ownership operation is included, and neither scope nor
ownership migration rewrites `acceptance_actor_id`. Future tenant support may
use a tenant/security-domain subject for scope, ownership, or both, but those
remain separately recorded decisions. It does not redefine `request_id` or
expose `idempotency_scope_id`.

### 8. Disclosure Rules

Workflow ownership controls disclosure. Idempotency scope controls the replay
partition. They are related evidence but are never interchangeable.
`acceptance_actor_id` supplies immutable attribution and does not grant later
access. `current_actor_id` is the only actor used for current authorization.

The API applies these rules:

- lookup in another `idempotency_scope_id` is not performed for a normal
  request and another scope's existence is not disclosed;
- the same `request_id` in another scope is treated as new within the caller's
  scope;
- an equivalent replay returns identifiers and state only after current
  authorization permits `current_actor_id` to act for the resolved owner intent
  and disclose the workflow under `current_owner_subject_id`;
- workflows in the same idempotency scope may have different owners, and
  same-scope membership never bypasses owner-based authorization;
- resolved owner intent must match immutable `accepted_owner_subject_id` for
  equivalence unless an explicit replay-right migration resolves it to that
  historical intent;
- an owner-intent mismatch never returns the existing workflow and never
  creates a second workflow under the occupied key;
- a fingerprint conflict returns no existing workflow, owner, scope,
  fingerprint, acceptance time, or security evidence;
- when the caller lacks permission to learn that a same-scope mapping exists,
  equivalent and conflicting cases use the same safe authorization/not-found
  behavior required by policy and do not create a second workflow;
- unauthorized and nonexistent workflow retrieval remain externally
  indistinguishable where enumeration resistance is required; and
- an operator may cross ownership boundaries only through an explicit
  permission and auditable operator path.

Ordinary authorized replay may emit structured operational/security telemetry
and any access audit required by policy or data classification. Optional
telemetry failure does not block a correct replay. When policy requires
security audit for a conflict, owner-intent mismatch, or denied/hidden mapping
access, that evidence must be durable before the protected classification is
disclosed. Audit failure never permits duplicate workflow creation.

The platform does not claim perfect timing-side-channel elimination. It does
require normalized errors, bounded response detail, no cross-scope identifiers,
and tests that prevent direct existence disclosure.

### 9. Replay Semantics

| Situation | Required behavior |
| --- | --- |
| Same scope, operation, `request_id`, fingerprint, and resolved owner intent | Return existing identifiers and current state only if `current_actor_id` is currently authorized for the resolved intent and `current_owner_subject_id`; never create another workflow |
| Same scope, operation, and `request_id`, different fingerprint | Return safe `REQUEST_ID_CONFLICT` only when authorized to learn the mapping classification; never create another workflow |
| Same key and fingerprint, different resolved owner intent | Classify internally as `OWNER_INTENT_MISMATCH`; never return the workflow or create another; return only a safe policy-selected authorization/conflict response |
| Same key, different owner intent and fingerprint | Treat as owner-intent mismatch plus content conflict internally; expose neither classification nor existing data unless policy permits, and never create another workflow |
| Different scope, same operation and `request_id` | Treat as an independent identity without discovering or blocking the first scope |
| Same scope and `request_id`, independently defined operation | Treat as a different accepted-request identity; operation-specific authorization and validation still apply |
| Compatible API version or renamed route | Resolve to the same semantic operation and preserve replay |
| Fingerprint-policy evolution | Keep the same operation and compare through the stored historical profile |
| Unauthorized or accidental operation-identity change | Reject or fail compatibility validation; never rekey to evade a conflict |
| Same scope with different owners | Require unique `request_id` values per intended owner unless explicit replay-right migration exists; owner mismatch fails safely |
| Service actor submitting for another owner | Permit only through explicit current policy; store `acceptance_actor_id` and `accepted_owner_subject_id` separately on first acceptance |
| Replay by a different authorized actor | Resolve a new `current_actor_id`, preserve `acceptance_actor_id`, require matching owner intent and current disclosure authorization |
| Credential rotation or replacement | Resolve `current_actor_id` independently while retaining stable principal/scope mapping; accepted actor/owner evidence and current ownership remain unchanged |
| Acceptance-actor disablement | Deny that principal when it is `current_actor_id`; retain immutable acceptance evidence, key, scope, and current owner |
| Owner disablement | Apply current disclosure policy; retain accepted identity, replay scope, and actor evidence |
| Replay-scope subject disablement | Retain the scope mapping and history but deny new resolution as policy requires |
| Principal deletion | Tombstone actor, owner, and scope relationships independently; never recycle historical references |
| Ownership transfer, replay with original accepted owner intent | Owner intent may still match historical acceptance, but return the workflow only when `current_actor_id` is authorized under current ownership policy |
| Ownership transfer, replay with new current owner as intent | Not equivalent by default; fail safely unless an explicit replay-right migration resolves the new intent to the historical acceptance |
| One old scope to one new scope | Add one versioned alias to the immutable historical key after collision preflight; ownership is unchanged |
| Scope split | Define explicit request-resolution rules for each target, prohibit overlapping rights to one historical key, and fail closed on ambiguity |
| Scope merge | Preflight all complete-key collisions; never make two workflows canonical for one resolved identity |
| Tenant migration | Coordinate versioned scope lookup and, only when separately authorized, ownership migration; preserve original evidence |
| Alias collision, ambiguity, or cycle | Reject activation and fail closed without changing canonical records |
| Partially applied migration | Keep the previous complete mapping revision active or mark resolution unavailable; never expose a mixed revision |
| Stale component mapping revision | Reject scoped lookup/acceptance or require refresh; never resolve under stale rules |
| Mapping rollback | Preserve all newer mappings and canonical records; activate only a compatible audited revision and never restore global lookup |
| Tombstoned source scope | Preserve historical lookup only for explicitly authorized migration/recovery; never reactivate or recycle it implicitly |
| Operator replay or retrieval | Resolve operator as `current_actor_id`, use explicit permission and durable audit, and never overwrite `acceptance_actor_id`, impersonate the original scope, or silently change ownership |
| Historical fingerprint profile unavailable | Fail closed without creating another workflow |
| Policy-required replay/conflict audit unavailable | Deny the relevant disclosure or privileged action; preserve existing workflow and never create a duplicate |
| Optional replay telemetry unavailable | Return an otherwise authorized equivalent replay; correctness and state remain unchanged |
| Lost original API response | Retry in the same resolved scope returns the committed workflow when fingerprint and authorization checks pass |

Operator access does not turn an operator's normal `POST` into a replay of
another scope. Any future administrative replay operation is a distinct
authorized operation and is out of scope as an API contract here.

Normal API lookup cannot enumerate aliases, migration history, other owners,
or other scopes. Alias resolution yields at most one canonical historical key
under one active mapping revision before fingerprint and disclosure checks.
Owner-intent comparison is then performed against immutable
`accepted_owner_subject_id`; it is not folded into the persistence key or
fingerprint.

### 10. Persistence Model

The authoritative logical accepted-request record stores at minimum:

- `request_id`;
- environment;
- configured semantic operation identity;
- `idempotency_scope_id`;
- immutable request fingerprint;
- `fingerprint_policy_version`, resolving semantic policy,
  canonical serialization, and digest algorithm versions;
- immutable `accepted_owner_subject_id`;
- the current `current_owner_subject_id` and complete historical ownership
  evidence;
- immutable `acceptance_actor_id`;
- normalized security evidence, including authorization decision/policy
  revision, scope-mapping revision, environment, and reason/delegation evidence
  where applicable, without raw credentials;
- workflow reference and initial acceptance result;
- acceptance time and correlation reference needed for audit; and
- immutable original-key, alias/mapping-revision, tombstone, collision, or
  compatibility references needed to preserve historical lookup.

`current_actor_id` is current-request context and is never a durable property
of the accepted-request record. It appears only in audit or operational
evidence required for that current action.

The uniqueness key remains
`(environment, operation, idempotency_scope_id, request_id)`. Neither immutable
accepted owner intent nor mutable current ownership is added to it. The
accepted-request record retains owner intent so arbitration can distinguish
equivalent replay from `OWNER_INTENT_MISMATCH` after resolving the unique key.

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

Every accepted-request record keeps its original complete key. There is
exactly one canonical record per historical key. Internal alias records name
an environment, mapping revision, source scope/key rule, and one canonical
target. Persistence constraints or equivalent activation validation prohibit
cycles, unbounded chains, ambiguous targets, and two canonical workflows for
one resolved replay identity. Active mapping revisions are atomic; normal
requests never observe a partially applied revision.

Scope split, merge, one-to-one migration, tenant migration, rollback, and
tombstone resolution are performed through versioned mapping records rather
than accepted-request updates. Ownership records change only through their
separate authorized transaction, which keeps the accepted-request
current-owner reference and workflow ownership consistent.

Accepted-request retention remains at least as long as the API duplicate
horizon and workflow-retention obligation. A tombstone must preserve the
complete key, fingerprint profile, owner/security evidence required for safe
disclosure, workflow or terminal replay reference, and migration history.

### 11. Audit

Audit aligns with ADR-0009 and remains separate from operational logs and
traces.

Mandatory durable coupled audit is required for:

- first acceptance, including complete accepted-request key references,
  `fingerprint_policy_version`, `accepted_owner_subject_id`,
  `current_owner_subject_id`, `acceptance_actor_id`, authorization decision,
  policy revision, scope-mapping revision, workflow reference, and outcome;
- every accepted-request or workflow-state mutation;
- ownership mutation, including previous/current owner, `current_actor_id`,
  reason, delegation or approval where required, policy revision, and
  effective time;
- security-relevant scope creation or migration, including aliasing, split,
  merge, mapping revision, disablement effect, and tombstone mutation; and
- operator lookup, override, replay, repair, or migration action.

Acceptance evidence commits with the accepted-request and workflow transaction.
Ownership or scope mutation and their business audit commit together or
neither commits. Failure of acceptance or mutation audit rolls back the
transaction.

First-acceptance audit records `acceptance_actor_id = current_actor_id` and the
resolved owner intent as `accepted_owner_subject_id`. Later replay, retrieval,
transfer, migration, operator, and recovery audit distinguishes the immutable
acceptance actor from the action's independently resolved `current_actor_id`.
No later audit or mutation rewrites original actor attribution or accepted
owner intent. Operator actions record the operator as `current_actor_id`, never
as `acceptance_actor_id`.

An ordinary authorized equivalent replay may rely on the immutable original
acceptance evidence, the current authorization decision, structured
operational/security telemetry, and an access audit when required by data
classification or policy. It need not create a new business-coupled durable
record before returning existing identifiers.

A conflict, `OWNER_INTENT_MISMATCH`, or denied/hidden mapping access creates
durable security audit when policy, classification, abuse-detection rules, or
operator access requires it. That evidence uses `current_actor_id` and safe
classification references without rewriting acceptance evidence. The external
response never depends on exposing protected owner, scope, actor, fingerprint,
alias, or workflow information.

Privileged operator or migration actions use ADR-0009 administrative security
audit. They fail closed when the action can still be stopped. Corrections are
additive; audit history, original ownership, original key, and historical
fingerprint evidence are never rewritten.

Failure of optional or best-effort replay telemetry does not block correctness.
Failure of policy-required security audit blocks the relevant disclosure or
privileged action. Existing workflow state is never changed because replay
audit failed, and no duplicate workflow is created when replay cannot be
disclosed.

Logs and traces may reference safe identifiers but cannot replace required
audit. Raw credentials, token claims, full workflow input, raw request bodies,
and fingerprint source material are excluded.

### 12. Authorization

For every call, the security adapter authenticates the caller as
`current_actor_id`. The trusted application/API boundary resolves the semantic
operation, environment, `idempotency_scope_id`, and owner intent, then
authorizes `current_actor_id` to attempt that operation for the resolved owner
under current policy before accepted-request arbitration. This adds no
client-controlled owner or operation field.

On first acceptance, the transaction stores
`acceptance_actor_id = current_actor_id`,
`accepted_owner_subject_id = resolved owner intent`, and
`current_owner_subject_id = accepted_owner_subject_id`. On replay, it never
changes those immutable acceptance fields. After lookup, replay equivalence
checks accepted owner intent and the historical fingerprint, and disclosure
authorization evaluates `current_actor_id` against
`current_owner_subject_id`, environment, operation, and current policy.

Authorization responsibilities are:

- `idempotency_scope_id` partitions replay and uniqueness;
- `accepted_owner_subject_id` participates in replay equivalence;
- `current_owner_subject_id` and current policy control workflow disclosure;
- `acceptance_actor_id` records who caused original acceptance but grants no
  later access;
- `current_actor_id` identifies who is requesting the current action;
- operation permission controls submission or operator action;
- environment limits every decision;
- fingerprint comparison classifies content but grants no permission; and
- operator or migration permission permits narrowly scoped cross-owner access
  without converting the operator into the owner or idempotency principal.

No permission is inferred from knowledge of `request_id`, `workflow_id`,
`correlation_id`, fingerprint, scope, tenant-looking claim, or owner reference.
An idempotency scope must never appear as the authenticated principal or owner
in policy or audit. Accepted owner, current owner, acceptance actor, and current
actor are never inferred from the scope.

### 13. Principal Lifecycle

Principal and credential lifecycle follow these rules:

- credential refresh, rotation, renewal, and like-for-like replacement retain
  stable principal and scope mappings; each call still resolves
  `current_actor_id` independently, while `acceptance_actor_id`,
  `accepted_owner_subject_id`, and current ownership remain unchanged;
- acceptance-actor disablement prevents that actor's new actions but changes
  neither immutable `acceptance_actor_id` nor accepted/current ownership;
- owner disablement changes disclosure and administration only through current
  policy and leaves accepted owner intent, accepted key, scope, and actor
  evidence unchanged;
- disablement of a subject mapped to a replay scope prevents new authorized
  scope resolution as policy requires but preserves the mapping and accepted
  records;
- re-enablement of the same stable subject restores only its applicable actor,
  owner-policy, or scope-mapping relationship under current policy;
- principal deletion tombstones its actor, owner, and scope relationships
  independently and never frees any historical reference for reuse;
- a replacement that represents a different principal does not inherit scope
  or ownership merely because it uses the same name, email, client label, role,
  or credential issuer;
- ownership transfer changes authorization ownership through an explicit
  audited operation by `current_actor_id`; it changes only
  `current_owner_subject_id` and does not rekey historical accepted requests,
  change `accepted_owner_subject_id` or `acceptance_actor_id`, or create a scope
  alias;
- scope migration changes replay resolution only through an explicit,
  deterministic, versioned, collision-checked, audited alias mapping and does
  not change accepted/current ownership or original acceptance attribution;
- scope aliases prohibit cycles, ambiguous targets, unbounded chains, partial
  active revisions, and silent replay-right acquisition;
- tenant migration coordinates scope mapping and, only through a separate
  authorized operation, current ownership, without rewriting original
  `acceptance_actor_id` or `accepted_owner_subject_id`;
- stale components must refresh to the active mapping revision or fail closed;
- rollback preserves mappings introduced by newer revisions and never restores
  global lookup assumptions; and
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

1. Add trusted environment, configured semantic operation,
   `idempotency_scope_id`, immutable `accepted_owner_subject_id`, separate
   `current_owner_subject_id`, immutable `acceptance_actor_id`, complete
   fingerprint-version, scope-mapping revision, and security-evidence
   capabilities without removing the global key. `current_actor_id` remains
   per-request context and is not backfilled as accepted-request state.
2. Create durable scope mappings. Existing single-principal local-development
   records map to an explicit legacy synthetic scope for their known
   environment and configured `workflow.submit` operation.
3. Backfill historical accepted owner, current owner, acceptance actor,
   operation, and fingerprint-version evidence only from authoritative
   deployment, contract, authentication, transfer, and acceptance facts. Do
   not infer owner or actor from the scope. Ambiguous records are blocked for
   reconciliation rather than guessed.
4. Validate that every retained accepted mapping has a complete composite key,
   fingerprint profile, accepted/current owner, immutable acceptance actor,
   mapping revision, and workflow/tombstone integrity.
5. Add and verify composite uniqueness and scoped lookup behavior while a
   compatibility deployment can still read the earlier model.
6. Deploy scoped arbitration and dual-version historical replay support before
   permitting multi-principal submissions.
7. Remove the global `request_id` uniqueness requirement only after all active
   components use the scoped model and rollback no longer depends on it.
8. Retain migration revision, alias/tombstone, collision, and reconciliation
   evidence for the historical replay horizon.

Operation migration maps routes and API versions to reviewed semantic commands.
Compatible route renames and API/schema versions keep `workflow.submit` and
use fingerprint-policy compatibility. A new operation identity is activated
only for an independently idempotent business command after contract,
collision, replay, and rollback review.

Scope migration preserves the original key and follows these behaviors:

| Migration case | Required behavior |
| --- | --- |
| One old scope to one new scope | Add one deterministic, versioned internal alias after collision preflight; retain the old canonical record, accepted owner, current owner, and acceptance actor |
| Scope split | Define nonoverlapping resolution rules; no two target scopes gain silent rights to the same historical key |
| Scope merge | Preflight every environment/operation/`request_id` collision; reject if two historical workflows would become canonical for one resolved identity |
| Tenant migration | Migrate scope lookup independently from ownership and acceptance attribution; a separate authorized ownership operation is required when current ownership also changes |
| Collision or ambiguous target | Fail closed, keep the prior mapping revision active, and require audited reconciliation |
| Partially applied migration | Never activate partial rules; atomically retain or restore the previous complete revision |
| Stale component | Reject startup or lookup/acceptance under the stale revision until refreshed |
| Mapping rollback | Activate only a compatible audited revision while preserving newer mappings and canonical records |
| Tombstoned source scope | Preserve historical recovery resolution but prohibit implicit reactivation, reuse, or new acceptance |

Aliases are internal and environment-scoped. Resolution is deterministic,
cycle-free, bounded or normalized to one canonical target, and produces at
most one canonical historical key. Normal API lookup cannot enumerate alias or
migration history.

Ownership transfer alone grants no replay equivalence to a new owner intent.
A deliberate transfer of replay rights uses a separate explicit, versioned,
collision-checked, and audited scope/request migration rule. That rule may
resolve an authorized incoming owner intent to immutable historical
`accepted_owner_subject_id` for replay comparison, but it never rewrites the
accepted owner, acceptance actor, fingerprint, or original key.

If no schema or accepted-request data exists when implementation begins, the
initial schema implements the composite model directly and records that no
data migration was required.

An environment containing records whose original environment, semantic
operation, scope, accepted/current owner, acceptance actor, or fingerprint
profile cannot be established must not enable multi-principal acceptance.
Recovery requires an authorized, audited classification or isolation decision.

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
- Scope, immutable acceptance actor, per-call current actor, immutable accepted
  owner intent, and mutable current owner have separate, testable meanings.
- Owner-intent comparison prevents a shared scope from returning one owner's
  workflow for another owner's intended submission.
- Database uniqueness still arbitrates concurrent first acceptance.
- Existing public API fields and request fingerprints remain compatible.
- Compatible route and schema evolution preserves semantic operation identity.
- Historical fingerprint behavior becomes explicit across semantic,
  serialization, and digest evolution.
- Future tenant/security-domain models can be introduced without redefining
  `request_id`.

#### Negative Consequences

- Scope mappings, ownership evidence, composite uniqueness, historical
  fingerprint profiles, and migrations add storage and application complexity.
- Shared scopes require careful policy because one member can consume a
  `request_id` for the whole scope even when owner mismatch prevents
  disclosure. Callers therefore use unique request IDs per intended owner
  unless replay rights were explicitly migrated.
- Ownership transfer does not automatically change historical replay
  equivalence; a separate replay-right migration may be required.
- Required security audit for classified conflicts, denied access, or
  privileged replay adds write load, while ordinary equivalent replay does not
  require an unconditional durable write.
- Alias revisions, collision preflight, cycle prevention, and stale-component
  gating add migration complexity.
- Rollback becomes constrained after duplicate `request_id` values exist in
  different scopes.

#### Migration Impact

- Global uniqueness is replaced by composite uniqueness after additive
  backfill and compatibility validation.
- Existing single-principal records receive a known legacy synthetic scope and
  separate acceptance actor, accepted owner, and current owner references only
  when authoritative facts support those mappings.
- Historical fingerprint metadata may require explicit profile backfill.
- Historical routes and versions require reviewed semantic-operation mapping;
  they are not used directly as key values.
- Scope migration retains immutable keys and adds versioned alias resolution
  rather than rewriting accepted-request records.
- Multi-principal API enablement waits until scoped lookup, uniqueness,
  disclosure, audit, and rollback compatibility are proven.

#### Developer Impact

- API code receives scope only from trusted security context.
- Domain logic keeps acceptance actor, current actor, accepted owner intent,
  current owner, authorization, fingerprint, idempotency scope, and operation
  identity separate.
- Persistence adapters must classify scoped equivalent replay, scoped
  conflict, owner-intent mismatch, unauthorized hidden mapping, and new request
  deterministically.
- Tests require multiple principals, actors, owners, scopes, route versions,
  operations, credential versions, fingerprint profiles, alias revisions, and
  migration states.

#### Operational Impact

- Operators manage separate scope and owner mappings, actor evidence, semantic
  operation mappings, migration revisions, ambiguous historical rows,
  policy-required audit retention, and collision reconciliation.
- Scope split, merge, transfer, and tenant migration are privileged changes,
  not direct database edits.
- Deployments must prevent rollback to globally scoped software after
  cross-scope duplicate identifiers exist.

#### Security Impact

- Identifier confidentiality and principal isolation improve.
- Scope mapping and operator migration become privileged trust boundaries.
- Incorrectly broad shared scopes can cause denial of service within that
  scope, although they do not authorize workflow disclosure.
- Incorrect owner resolution can disclose data or attribute work to the wrong
  subject; actor-for-owner authorization and immutable owner-intent comparison
  are mandatory.
- Audit and retention contain protected ownership and security metadata.

### 16. Amendments to ADR-0004 and ADR-0006

This ADR supersedes only the following earlier requirements.
Every unrelated decision in ADR-0004 and ADR-0006 remains Accepted and
unchanged.

#### ADR-0004 Amendments

- Section 6's statement that `request_id` identifies one logical submission is
  scoped to one `(environment, operation, idempotency_scope_id)` partition.
  Operation means the trusted configured semantic command, not a route or API
  version. Client generation, omission behavior, format, and immutability
  remain unchanged.
- Section 8 submission replay and conflict behavior applies only after trusted
  scoped lookup, resolved-owner-intent comparison, and current disclosure
  authorization. The same `request_id` in another scope is independent.
  Compatible routes or API versions may resolve to the same semantic
  operation.
- Section 12's global unique mapping and "never two workflows for one accepted
  `request_id`" language becomes one workflow per complete accepted-request
  key. Its semantic fingerprint, canonicalization, historical-policy, and
  conflict rules remain. Equivalent replay additionally requires resolved owner
  intent to match immutable `accepted_owner_subject_id`; Section 6 clarifies
  the information resolved by the existing `fingerprint_policy_version`.
  Fingerprint-policy evolution does not rekey the operation.
- Section 9's `REQUEST_ID_CONFLICT` remains stable but cannot disclose another
  owner or scope. Authorization may require a non-disclosing response instead.
- No API wire field, JSON Schema authority, identifier encoding, error format,
  message contract, or other contract decision changes.

#### ADR-0006 Amendments

- Section 1's accepted-request record gains environment, operation,
  `idempotency_scope_id`, complete fingerprint version, immutable
  `accepted_owner_subject_id`, separate `current_owner_subject_id`, immutable
  `acceptance_actor_id`, mapping revision, and normalized security evidence.
  `current_actor_id` remains per-request context rather than accepted-request
  state.
- Section 5's submission transaction resolves the composite accepted-request
  key and configured semantic operation rather than a globally unique
  `request_id`; its atomic workflow, task, transitions, snapshot, and outbox
  behavior is unchanged.
- Section 11's unique `request_id` within the Orchestrator acceptance domain is
  replaced by uniqueness of
  `(environment, operation, idempotency_scope_id, request_id)`.
- Section 12's reservation, lookup, equivalence, conflict, retention, and
  tombstone rules apply within that complete key and current disclosure
  authorization. Historical keys stay immutable; versioned internal aliases
  resolve migration without rewriting canonical records. Owner intent is an
  additional equivalence dimension after unique-key lookup but not a key
  column.
- Section 30's guarantee becomes one workflow per complete accepted-request
  key, not per globally unique `request_id`.
- Section 31's migration preservation requirements include scope, immutable
  acceptance actor, accepted/current owner evidence, semantic-operation
  mapping, alias/mapping revisions, security evidence, and complete
  fingerprint-version history.
- PostgreSQL, persistence ownership, transaction isolation, repository
  boundaries, state transitions, outbox/inbox behavior, recovery, retention,
  backup, and every unrelated persistence decision remain unchanged.

### 17. Security Guarantee and Evidence Table

| Guarantee | Authoritative source | Enforcement point | Durable audit evidence | Failure behavior | Required tests |
| --- | --- | --- | --- | --- | --- |
| Accepted replay is deterministic | Complete accepted-request key, immutable accepted owner intent, and stored historical fingerprint profile | API security adapter, Orchestrator arbitration, persistence uniqueness | Immutable acceptance evidence; policy-required current-actor access/security audit | Optional telemetry failure does not block; required audit failure blocks disclosure; mismatch never returns or duplicates a workflow | Same/different actor, same/different owner intent, conflicting content, lost-response, unavailable-profile, and audit-outage tests |
| Original and current actors stay distinct | Immutable `acceptance_actor_id`, per-call `current_actor_id`, and authentication evidence | Security/authorization adapters and accepted-request persistence | First-acceptance attribution plus current-action actor where audit is required | Never overwrite original attribution; reject unauthorized current actor | Original-actor replay, different authorized actor, credential rotation, ownership-transfer replay, operator action, and attribution-immutability tests |
| Scope and owner identities stay distinct | Scope mapping, immutable `accepted_owner_subject_id`, current `current_owner_subject_id`, and policy | Authorization adapter plus accepted-request/workflow persistence | Accepted/current owner, scope revisions, and authorized ownership mutation | Reject unauthorized owner choice; no inference from scope | Same-scope different-owner, service-for-owner, shared-client/user-owner, transfer-without-rekey, and unauthorized-owner tests |
| Owner-intent mismatch cannot cross ownership | Immutable accepted owner intent plus current resolved owner intent | Arbitration and authorization boundary after scoped lookup | Policy-required `OWNER_INTENT_MISMATCH` evidence using `current_actor_id` | Safe denial/conflict; no existing identifiers and no second workflow | Same fingerprint/different owner, different fingerprint/different owner, post-transfer original/new-owner intent, and duplicate-prevention tests |
| Ownership isolation controls disclosure | `current_owner_subject_id` and versioned authorization policy | Workflow API and authorization port | Accepted/current owner, acceptance/current actor, policy revision, and policy-required access disposition | Safe denial/not-found; no identifiers returned and no duplicate created | Owner, delegate, shared-domain, disabled-owner, and unauthorized tests |
| Identifier confidentiality crosses no scope | Trusted scoped lookup and safe error policy | API adapter and accepted-request repository | Policy-required cross-scope/denial security audit without protected data | Treat caller's scope independently or deny safely | Same `request_id` across scopes, guessing, hidden mapping, enumeration, and timing-shape tests |
| Replay partitions cannot collide accidentally | Adapter-resolved scope mapping plus composite uniqueness | Security adapter and database constraint | Scope creation/mapping revision and acceptance | Transaction conflict resolved only inside the same complete key | Multi-principal concurrent-acceptance and broad-scope misconfiguration tests |
| Semantic operation is stable | Reviewed application/API operation mapping | API adapter configuration and compatibility gate | Operation-mapping revision and contract review | Reject unauthorized mapping change; never rekey to avoid conflict | Two-version alias, route rename, independent operation, accidental-change, and fingerprint-only evolution tests |
| Credential rotation preserves replay | Stable principal-to-scope mapping independent of immutable acceptance evidence and ownership | Authentication/security adapter | Credential lifecycle reference and independently resolved `current_actor_id` | Deny if mapping is ambiguous; never alter acceptance attribution or create a replacement scope silently | Token/key/certificate rotation and replacement tests |
| Historical replay survives evolution | Immutable original key, fingerprint profile, deterministic aliases, and tombstones | Compatibility adapter and persistence lookup | Profile and mapping revision; policy-required replay disposition | Fail closed without duplicate creation | Old fingerprint profiles, deterministic alias, cycle/chain, stale-revision, and tombstone tests |
| Operator access is explicit | Operator `current_actor_id`, permission, target, reason, and approval policy | Administrative/recovery boundary | ADR-0009 current-actor/action/target/reason/outcome evidence | Fail closed; never overwrite `acceptance_actor_id`, impersonate scope, or mutate ownership implicitly | Authorized/unauthorized operator lookup, replay, transfer, attribution, and audit-outage tests |
| Migration preserves one canonical workflow | Immutable historical keys plus reviewed alias revision and collision preflight | Deployment migration boundary, alias resolver, and startup compatibility check | Backfill, alias, collision, activation, partial-failure, and rollback evidence | Keep prior revision or block lookup/startup; never expose two canonical workflows | One-to-one, split/merge collision, partial rollback, stale revision, ownership-unchanged, and duplicate-canonical tests |

### 18. Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| Global `request_id` uniqueness survives accidentally | Remove it only through reviewed migration; require composite constraint and cross-scope concurrency tests |
| Identifier guessing reveals another request | Scope the lookup before persistence access, authorize disclosure, and normalize safe errors |
| Ownership leaks through replay or conflict | Return identifiers/classification only when authorized; store no owner or scope in public problems |
| Replay caller overwrites original attribution | Persist immutable `acceptance_actor_id` once; resolve `current_actor_id` independently for every later action and audit them separately |
| Scope, owner, and actor are conflated | Persist separate scope, accepted/current owner, and acceptance actor references; keep current actor in request/audit context; equality is policy, not a constraint |
| Unauthorized actor selects another owner | Resolve and authorize actor-for-owner through trusted policy; no arbitrary public owner selection |
| Ownership is derived from a credential | Persist stable normalized owner and immutable actor; credential lifecycle never rewrites ownership |
| Shared scope returns another owner's workflow | Require owner-intent equivalence after key lookup and before disclosure; mismatch returns nothing and cannot create a duplicate |
| Ownership transfer silently changes replay identity | Keep accepted owner intent immutable; require separate replay-right migration for new-owner intent |
| Route or API version becomes operation identity | Resolve reviewed semantic command from configuration; aliases retain identity and fingerprint policy handles compatible shape changes |
| Operation is rekeyed to avoid conflict | Require contract/migration review and reject unauthorized mapping changes |
| Fingerprint evolution creates false replay or conflict | Store immutable semantic, canonicalization, and digest profile identity; retain historical adapters |
| Scope migration creates duplicate or unreachable mappings | Preserve original keys, use deterministic versioned aliases, preflight collisions, prohibit cycles/ambiguity, and fail closed |
| Split or merge gives two workflows one resolved identity | Require collision preflight and exactly one canonical record for every resolved replay identity |
| Stale or partial mapping revision misroutes replay | Activate complete revisions atomically; stale components refresh or fail closed; rollback preserves newer mappings |
| Scope migration silently changes ownership | Treat ownership as a separate authorized transaction and test that aliases leave it unchanged |
| Tenant evolution broadens a scope silently | Require explicit policy and migration; never infer tenant sharing from provider claims or roles |
| Operator misuse crosses ownership boundaries | Resolve operator as `current_actor_id`; require separate permission, reason/approval, durable audit, no attribution overwrite, and least-privilege recovery port |
| Historical replay meaning is ambiguous | Preserve immutable profile and original key evidence; quarantine unresolved legacy records |
| Shared scope member consumes an identifier | Make sharing deliberate, authorize disclosure independently, and use scoped client policy |
| Principal deletion permits identity reuse | Tombstone principal/scope mappings and prohibit identifier recycling |
| Rollback software assumes global uniqueness | Compatibility gate deployment and prohibit unsafe rollback after cross-scope duplicates exist |
| Optional replay telemetry outage blocks safe reads | Keep ordinary replay telemetry best effort unless policy requires durable access audit |
| Required audit outage hides disclosure or mutation | Roll back acceptance/mutation; block policy-required disclosure or privileged action; preserve workflow and never create a duplicate |
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
   acceptance, current actor, policy-required replay/conflict/owner-mismatch
   access, ownership, scope migration, and operator evidence?
6. Which data classifications, abuse thresholds, and policies require durable
   replay, conflict, or denied-access audit, and what bounded retention and
   rate controls apply?
7. What repository query names and database transaction statements implement
   scoped arbitration without exposing global lookup to the API path?
8. What physical alias representation, maximum chain bound, normalization
   method, mapping-revision protocol, and collision-preflight procedure are
   used?
9. What configuration representation and review mechanism maps routes and API
   versions to semantic operation identities?
10. Which existing safe public authorization or conflict response maps each
    policy context for internal `OWNER_INTENT_MISMATCH`?

These choices cannot weaken the complete key, internal-scope boundary,
ownership/disclosure separation, historical fingerprint behavior, required
audit durability, or migration guarantees.

### 20. Acceptance Checklist

- [ ] ADR-0004/ADR-0006 single-principal and global-`request_id` assumptions are
      explicitly identified.
- [ ] Accepted-request identity is
      `(environment, operation, idempotency_scope_id, request_id)`.
- [ ] Every key element comes from the correct trusted or client boundary.
- [ ] Operation is a trusted configured semantic command identity, never
      client supplied or derived directly from route, handler, media type,
      deployment version, or API-version string.
- [ ] Compatible API/schema evolution and route aliases retain operation
      identity; fingerprint-policy evolution does not rekey it.
- [ ] New operation identity requires an independently idempotent business
      command plus explicit contract, migration, and compatibility review.
- [ ] Operation identity cannot change merely to evade an existing conflict.
- [ ] Database uniqueness and concurrent arbitration apply to the complete
      key, not global `request_id`.
- [ ] `idempotency_scope_id` is internal, opaque, stable, adapter-resolved, and
      never client supplied.
- [ ] Idempotency scope is not a principal, role, tenant, owner, credential, or
      authorization policy.
- [ ] `idempotency_scope_id`, immutable `acceptance_actor_id`, per-call
      `current_actor_id`, immutable `accepted_owner_subject_id`, and
      `current_owner_subject_id` are separate normalized references.
- [ ] These references may be equal only as a policy result, never as a
      persistence invariant.
- [ ] Same-scope workflows may have different owners, and a service actor may
      submit for another owner only through explicit policy.
- [ ] Neither owner nor actor is inferred from `idempotency_scope_id`.
- [ ] Scope creation, credential rotation, disablement, deletion, migration,
      tombstone, and audit behavior are explicit.
- [ ] Public API fields remain limited to `request_id`, `correlation_id`, and
      `workflow_id`.
- [ ] Equivalent replay requires the same complete key and historical
      fingerprint profile plus resolved owner intent matching immutable
      `accepted_owner_subject_id`.
- [ ] Owner intent is an equivalence dimension but neither accepted nor current
      owner is part of the database uniqueness key.
- [ ] `OWNER_INTENT_MISMATCH` never returns the existing workflow, creates a
      second workflow, or exposes protected identity/existence information.
- [ ] Conflicting fingerprints never create another workflow.
- [ ] Different scopes may use the same `request_id` without discovery or
      blocking.
- [ ] Authentication resolves `current_actor_id` for every call; first
      acceptance stores `acceptance_actor_id = current_actor_id`; replay never
      changes original attribution.
- [ ] Credential rotation preserves stable principal and replay-scope mappings
      while accepted actor/owner evidence and current ownership remain
      independently stable.
- [ ] Principal disablement/deletion preserves history while denying
      unauthorized disclosure.
- [ ] Immutable accepted owner, mutable current owner, immutable acceptance
      actor, and per-call current actor remain distinct from credentials.
- [ ] Ownership transfer and tenant migration are explicit, versioned, and
      audited without silently rekeying accepted requests.
- [ ] Ownership transfer creates no alias, and scope migration changes no owner
      without a separate authorized ownership operation.
- [ ] Ownership transfer changes only `current_owner_subject_id` and current
      authority; it does not change accepted owner intent, acceptance actor,
      original fingerprint, or accepted-request key.
- [ ] Ownership transfer updates accepted-request current ownership, workflow
      ownership, history, and coupled audit atomically.
- [ ] Replay with new current-owner intent after transfer is not equivalent
      without a separate explicit replay-right migration.
- [ ] Workflow ownership controls disclosure; idempotency scope controls replay
      partitioning.
- [ ] Unauthorized equivalent and conflict cases do not reveal mapping
      existence or identifiers.
- [ ] Operator access resolves the operator as `current_actor_id`, requires
      separate permission and audit, and never overwrites acceptance
      attribution or impersonates the target scope.
- [ ] `fingerprint_policy_version` explicitly resolves semantic policy,
      canonical serialization, digest algorithm, compatibility, and
      fail-closed history.
- [ ] The accepted-request persistence record contains the complete key,
      fingerprint/profile, immutable acceptance actor and accepted owner,
      separate current/historical ownership, security evidence, workflow
      reference, and migration history; it does not store `current_actor_id` as
      accepted-request state.
- [ ] First acceptance, every state/ownership mutation, security-relevant scope
      mutation, and operator action have durable ADR-0009-aligned evidence.
- [ ] Ordinary authorized equivalent replay does not unconditionally require a
      new durable business-audit write.
- [ ] Conflict, owner-intent mismatch, and denied/hidden access use durable
      security audit with `current_actor_id` when policy, classification, abuse
      detection, or operator access requires it.
- [ ] Optional replay telemetry failure does not block correctness;
      policy-required audit failure blocks disclosure/action; acceptance or
      mutation audit failure rolls back; no replay-audit failure changes state
      or creates a duplicate.
- [ ] The migration preserves existing API fields and known historical
      semantics and does not guess ambiguous ownership or fingerprint data.
- [ ] Composite uniqueness is proven before global uniqueness is removed.
- [ ] Mixed-version startup and rollback are blocked when they could create
      duplicates or misroute replay.
- [ ] Every accepted request retains its immutable original complete key and
      exactly one canonical record exists per historical key.
- [ ] Aliases are internal, deterministic, versioned, environment scoped,
      audited, cycle-free, bounded or normalized, and fail closed on ambiguity.
- [ ] Split, merge, and tenant migration preflight collisions and cannot grant
      multiple scopes silent rights or make two workflows canonical for one
      resolved replay identity.
- [ ] Partial migration, stale mapping revisions, rollback, and tombstoned
      sources have explicit fail-closed behavior.
- [ ] Normal API lookup cannot enumerate alias or migration history.
- [ ] ADR-0004 amendments are limited to request identity and scoped
      replay/conflict/disclosure; existing fingerprint versioning is clarified,
      not replaced.
- [ ] ADR-0006 amendments are limited to accepted-request persistence,
      uniqueness, transaction lookup, guarantee wording, and migration.
- [ ] No unrelated API, contract, persistence, workflow, Event Bus,
      authentication, authorization, or audit architecture changes.
- [ ] ADR-0010's idempotency, ownership, disclosure, lifecycle, and safe-error
      requirements are satisfied.
- [ ] Required tests cover same-scope/different-authorized-owner,
      service-for-owner, shared-client/user-owner, unauthorized owner choice,
      ownership transfer without rekeying, and scope migration without
      ownership transfer.
- [ ] Required tests cover replay by original actor, replay by a different
      authorized same-scope actor, credential rotation, replay after ownership
      transfer, operator replay/retrieval, and immutable original attribution.
- [ ] Required tests cover shared-scope same-key/same-fingerprint with matching
      and mismatching owner intent, different owner plus different fingerprint,
      authorized/unauthorized actor-for-owner submission, post-transfer replay
      using original and current-owner intent, and proof that mismatch neither
      discloses nor duplicates a workflow.
- [ ] Required tests cover two API versions sharing one operation, route rename,
      independent operation identity, unauthorized identity change, and
      fingerprint-policy change without operation rekeying.
- [ ] Required tests cover deterministic alias resolution, cycle rejection,
      chain normalization, split/merge collision, stale revision, partial
      rollback, unchanged ownership, cross-scope enumeration prevention, and
      duplicate canonical-workflow prevention.
- [ ] Remaining questions are implementation choices and do not leave the
      architectural model undecided.

The acceptance review completed on 2026-07-28 found this architectural model
internally complete. All remaining questions are implementation choices.
ADR-0011 resolves the sole accepted-request scope blocker identified by
ADR-0010, which may proceed through acceptance review without another
idempotency architecture decision.

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
