# ADR-0012: Correlation ID Normalization

- **Status:** Accepted
- **Date:** 2026-07-30
- **Supersedes:** Upon acceptance, only ADR-0004's requirement to reject an API
  request solely because its client-supplied `Correlation-Id` is invalid
- **Superseded by:** None

## Context

ADR-0004 and ADR-0009 are both Accepted but define conflicting behavior for an
invalid client-supplied `Correlation-Id`:

- ADR-0004 Section 8 requires invalid supplied correlation context to be
  rejected.
- ADR-0009 Sections 4, 6, 8, and 35 require malformed or disallowed correlation
  context to be discarded or replaced without failing an otherwise valid
  business request.

Neither ADR explicitly supersedes the other on this behavior. Vertical Slice
01 therefore leaves the invalid-header branch of the Workflow API contract
blocked.

The conflict concerns operational correlation metadata only. ADR-0011 remains
authoritative for accepted-request identity, idempotency, replay equivalence,
ownership, authorization, and disclosure. This ADR must not allow correlation
metadata to influence those decisions.

The platform also needs one bounded trust-boundary rule that prevents
client-controlled correlation data from reaching logs, traces, messages,
audit metadata, or responses before it is safe. The rule must preserve useful
client correlation without coupling business availability to telemetry.

## Decision

### 1. Correlation ID Role

`Correlation-Id` is optional client-supplied operational correlation metadata.
The normalized internal field is `correlation_id`.

It may group operational evidence for related activity, but it is not:

- `request_id`;
- an accepted-request identity component;
- an idempotency key;
- a workflow, task, or attempt identifier;
- a message identity or deduplication key;
- a trace identifier, although a trace may be associated with it;
- authentication, authorization, ownership, or producer evidence;
- a concurrency or ordering key;
- a secret; or
- proof that two requests represent the same business operation.

Correlation identifiers may be duplicated. Their possession grants no
authority, and their equality establishes no business relationship.
Operational tools must tolerate multiple unrelated requests and workflows
using the same value.

### 2. Effective Correlation Identifier

Every API invocation that reaches the application boundary establishes one
safe **effective correlation identifier** before the value enters structured
logs, traces, commands, events, business or security audit metadata, or an API
response.

The effective value comes from exactly one of these paths:

| Input condition | Effective correlation behavior |
| --- | --- |
| Valid client value | Preserve the validated value |
| Header missing | Generate a new platform-controlled value |
| Header malformed, unsafe, unsupported, or oversized | Discard the raw value and generate a new platform-controlled value |

Only the effective value may cross the API trust boundary. The raw rejected
value is never echoed, propagated, retained for later parsing, or used as an
observability attribute.

The current Accepted format from ADR-0004 is a canonical lowercase UUIDv7.
This ADR does not introduce a new format. The centrally defined validation
profile owns the accepted syntax, encoding, canonical form, and maximum length.
A future format change requires normal contract and compatibility review.

The generator uses a local mechanism whose availability does not depend on a
telemetry collector, exporter, network service, identity provider, Event Bus,
database, or other remote dependency. Generation must be concurrency-safe and
must satisfy the active correlation validation profile.

### 3. Valid Client-Supplied Header

When a caller supplies a `Correlation-Id` that satisfies the active syntax,
canonical-form, length, and safety constraints:

- the API preserves it as that invocation's effective external correlation
  identifier;
- the response uses it in the accepted `Correlation-Id` header;
- first acceptance may persist it as the workflow's durable correlation
  identifier and propagate it through the resulting asynchronous chain;
- supported logs, traces, and audit metadata may use it subject to redaction,
  cardinality, access, and retention policy; and
- no component interprets it as security or business identity.

A caller may intentionally reuse a valid value. Spoofing or guessing one can
affect operational grouping only.

### 4. Missing Header

When the caller omits `Correlation-Id`:

- the API generates a new platform-controlled effective correlation
  identifier;
- the current invocation uses that value consistently;
- the API returns it in the accepted `Correlation-Id` response header; and
- if the request creates a workflow, the accepted workflow and its resulting
  commands, events, audit metadata, logs, and traces use that value as their
  durable correlation identifier.

Omission is not an error and has no effect on request validation,
authorization, accepted-request arbitration, or workflow semantics.

### 5. Invalid Header

When the caller supplies a malformed, unsafe, unsupported, noncanonical, or
oversized `Correlation-Id`:

1. bounded validation rejects the supplied value as correlation metadata;
2. the API discards the raw value;
3. the API generates a new platform-controlled effective correlation
   identifier;
4. only the generated value is used for the invocation, response, and any
   resulting business or asynchronous activity; and
5. the business request continues through its ordinary validation and
   authorization path.

An invalid `Correlation-Id` does not by itself create a `4xx` response. It does
not change the business request, request fingerprint, accepted-request key,
replay classification, authorization, ownership, message deduplication, or
workflow state.

The API may emit a bounded structured operational signal that replacement
occurred. That signal may contain only a safe reason category such as
malformed, noncanonical, unsafe, or oversized. It must not contain the raw
value, an unbounded derived value, validation internals, or data that would
allow reconstruction.

### 6. Validation Boundary

Correlation validation is performed at every trust boundary before the value
is admitted to platform diagnostic or contract context.

Validation must be:

- deterministic for a given validation-profile version and input;
- bounded in processing time and memory;
- length-checked before expensive parsing;
- based on one centrally defined or explicitly versioned profile;
- consistent across API, message, and diagnostic adapters;
- safe against control characters, delimiter injection, multiline log
  injection, invalid encoding, unsupported forms, oversized values, and
  unbounded attribute cardinality; and
- independent from telemetry exporter availability.

The profile defines at minimum:

- accepted encoding;
- maximum input length;
- accepted syntax and canonical representation;
- prohibited character and control ranges;
- normalization policy, which must not silently reinterpret two distinct valid
  values as one; and
- generated-value conformance.

Validation occurs on the bounded header representation supplied by the HTTP
adapter. Infrastructure may reject an HTTP request before the application
boundary when the overall request or header block violates a lower-level,
bounded protocol limit. Such rejection is an infrastructure transport
failure, not the application correlation-invalid behavior defined here.

### 7. API-Visible Behavior

For valid, missing, and invalid input, an API response that can safely be
produced returns the invocation's effective correlation identifier in the
accepted `Correlation-Id` response header.

The behavior is:

| Request condition | Business processing | Response correlation |
| --- | --- | --- |
| Valid header | Continue normally | Preserve valid value in response header |
| Missing header | Continue normally | Return generated value in response header |
| Invalid header, otherwise valid request | Continue normally using replacement | Return generated value; never reflect raw input |
| Invalid header plus unrelated business error | Return the ordinary business Problem Details response | Use generated value in the response header and `correlation_id` problem field where safely producible |
| Request rejected before application parsing | No application processing | Infrastructure may generate a separate bounded diagnostic correlation value |

Replacement reveals neither the rejected value nor detailed validation rules.
It adds no new public error code.

#### First Acceptance and Replay

On first workflow acceptance, the invocation's effective correlation identifier
becomes the workflow's durable `correlation_id`, is persisted atomically with
the accepted workflow, and is propagated through its command and terminal
event chain.

An API retry or accepted-request replay is a new HTTP invocation and therefore
establishes its own effective correlation identifier. It may differ from the
workflow's original durable `correlation_id` without affecting replay:

- the response `Correlation-Id` header contains the current invocation's
  effective value;
- the response body continues to return the existing workflow's original
  durable `correlation_id`, as required by ADR-0009 and ADR-0011;
- replay logs, traces, and policy-required access/security audit may associate
  the current invocation value with the existing workflow;
- the existing workflow, command, events, transition history, accepted-request
  mapping, and original durable correlation are not rewritten; and
- replay creates no new asynchronous chain solely to propagate the current
  invocation value.

This distinction preserves per-invocation diagnosis while retaining immutable
accepted workflow evidence.

### 8. Propagation and Persistence

The effective correlation identifier may be:

- returned in API response headers;
- included in Problem Details where safely producible;
- stored as the durable workflow correlation on first acceptance;
- propagated through the ADR-0004 command and event envelope;
- included in business or security audit metadata where required;
- attached to structured logs and traces under ADR-0009; and
- used as an authorized operational search or grouping attribute.

It must not become:

- a workflow or accepted-request database uniqueness constraint;
- part of
  `(environment, operation, idempotency_scope_id, request_id)`;
- part of request fingerprinting or replay equivalence;
- an inbox, outbox, receipt, or transport-rejection deduplication key;
- a substitute for `message_id`, `workflow_id`, `request_id`, or trace context;
- an authorization lookup key without independent authorization; or
- an immutable domain identity for the current API invocation.

The durable workflow correlation established on first acceptance remains
immutable historical workflow evidence under ADR-0009. The per-invocation
effective value is operational request context. These values may be equal but
are not required to be equal on replay.

### 9. Asynchronous Trust Boundaries

Commands and events must contain an ADR-0004-valid `correlation_id`. Producers
validate it before constructing immutable message bytes. Consumers validate
the complete exact message contract before domain processing.

An Event Bus message with malformed, unsafe, unsupported, or oversized
correlation metadata is contract-invalid and follows ADR-0005/ADR-0006
quarantine or transport-rejection handling. A consumer must not rewrite the
field because doing so would mutate an immutable logical message. It must not
trust the value merely because the message arrived through the Event Bus or
another internal channel.

Trace headers and `correlation_id` remain separate. Invalid trace context may
be discarded or replaced under ADR-0009 without changing a valid domain
message. Invalid required message `correlation_id` makes that message invalid;
it is not repaired into a different logical publication.

### 10. Security and Disclosure

The following guarantees apply:

- invalid raw values are never reflected, logged, traced, measured, published,
  audited, persisted, or included in errors;
- replacement exposes no parser detail, rejected substring, or validation
  position;
- correlation knowledge never grants workflow access or reveals another
  caller's workflow;
- workflow retrieval and replay disclosure always use ADR-0010/ADR-0011
  authorization;
- valid-value spoofing affects operational grouping only;
- duplicate identifiers are expected and safe;
- correlation is never trusted producer identity or proof of an authenticated
  transport principal;
- high-cardinality correlation values do not become metric labels; and
- operational access to correlation data follows environment, privacy,
  retention, and diagnostic authorization policy.

Hashing, truncating, escaping, or encoding an invalid raw value does not make it
safe to propagate as correlation metadata. The platform discards it.

### 11. Failure Behavior

| Failure | Required behavior |
| --- | --- |
| Correlation generator fails | Use a local independent fallback that satisfies the same profile when available; if no safe effective value can be established, fail closed before business mutation with a generic server error and never propagate client input |
| Validation component fails or its profile is unavailable | Treat the supplied value as untrusted; generate a safe effective value through the local generator when possible; otherwise fail closed before business mutation |
| Telemetry backend/exporter unavailable | Continue business processing; bounded telemetry failure behavior follows ADR-0009 |
| Structured operational replacement signal fails | Continue business processing; the optional signal is not correctness evidence |
| Required business/security audit fails | Follow ADR-0009's coupled-audit failure rule for the affected business or privileged action; correlation normalization does not weaken it |
| Downstream message has malformed correlation metadata | Reject and quarantine or use pre-domain transport-rejection recovery; never rewrite or process it as valid |
| Duplicate correlation identifiers | Process requests independently using their accepted business identities and authorization |
| Infrastructure cannot parse enough of the request | Infrastructure may create an independent bounded diagnostic identifier; it must not reflect unsafe input or claim a durable workflow correlation |

Correlation generation needed at the synchronous application boundary cannot
depend on a telemetry service. Telemetry export failure never rolls back or
fails an otherwise committed business transaction. Conversely, failure to
establish any safe effective correlation at that boundary fails closed rather
than allowing unsafe metadata into the platform.

### 12. Concurrency and Consistency

Correlation identifiers do not arbitrate concurrency. Database constraints,
accepted-request identity, workflow revisions, inbox and receipt identities,
and message identifiers remain authoritative.

Multiple concurrent requests with the same valid correlation identifier:

- remain independent unless separate accepted business identities relate them;
- may create different workflows when their accepted-request keys differ;
- may resolve to one workflow when ADR-0011 replay rules independently say so;
- create independent API processing spans and per-invocation context; and
- must not be serialized, deduplicated, authorized, or rejected because their
  correlation values match.

Replay consistency is governed only by the complete accepted-request key,
historical fingerprint profile, resolved owner intent, and current
authorization. Correlation replacement never changes those inputs.

### 13. Amendments to Existing Decisions

Upon acceptance:

1. ADR-0012 supersedes ADR-0004 only for the behavior of an invalid
   client-supplied `Correlation-Id`. The request is no longer rejected solely
   for that reason; the value is discarded and replaced.
2. ADR-0004 remains authoritative for every other API and contract decision,
   including the current lowercase UUIDv7 correlation format, response header,
   message-envelope field, identifier ownership, and propagation of a valid
   durable workflow correlation.
3. ADR-0012 confirms and clarifies ADR-0009's correlation replacement behavior,
   including per-invocation context, telemetry nonauthority, redaction, trace
   separation, replay, and failure isolation.
4. ADR-0009 remains authoritative for the wider audit, logging, metrics,
   tracing, retention, privacy, and telemetry-failure architecture.
5. ADR-0012 does not amend ADR-0011 accepted-request identity, idempotency,
   fingerprint, replay, ownership, authorization, disclosure, persistence, or
   migration semantics.

No other clause of an Accepted ADR is superseded.

### 14. Verification Scenarios

| Scenario | Effective correlation behavior | Business-request behavior | Propagation behavior | Security/logging requirement | Prohibited outcome |
| --- | --- | --- | --- | --- | --- |
| Missing header | Generate conforming value | Continue normally | Use generated value for invocation and new workflow chain | Return generated header; log only effective value | Reject for omission |
| Valid header | Preserve validated value | Continue normally | Use value for invocation and new workflow chain | Apply ordinary access/redaction policy | Reinterpret as authority |
| Malformed header | Discard and generate | Continue normally | Propagate only generated value | Optional bounded replacement class; no raw value | `4xx` solely for correlation |
| Oversized header within infrastructure limit | Length-check, discard, generate | Continue normally | Propagate only generated value | No raw value or length-derived cardinality | Expensive unbounded parse or reflection |
| Control-character or multiline injection | Discard and generate | Continue normally | Propagate only generated value | Never log, trace, audit, or echo injected text | Log/header injection |
| Concurrent requests share one valid value | Preserve for each invocation | Process independently | Separate spans/context may share grouping value | Tooling tolerates duplicates | Correlation-based serialization/deduplication |
| Replay uses a different value | Establish current invocation value | Resolve through ADR-0011 | Header/current telemetry use invocation value; body/workflow retain original durable value | Authorize before workflow disclosure | Rekey replay or rewrite workflow correlation |
| Two workflows use the same value | Preserve for both | Create or resolve from their own accepted keys | Both may be grouped operationally | Search results still authorize each workflow | Assume one correlation equals one workflow |
| Telemetry backend unavailable | Preserve or generate locally | Continue normally | Business messages/audit use required safe value; export may drop | Observe bounded exporter failure where possible | Fail committed transaction solely for telemetry |
| Event Bus message has malformed correlation | No replacement inside immutable message | No domain processing | Quarantine/rejection recovery | No raw unsafe metadata in ordinary telemetry | Mutate and process message |
| Invalid header plus valid workflow submission | Discard and generate | Accept or replay under ordinary rules | Use generated invocation value; first acceptance persists it | Return generated response header | Correlation `4xx` or fingerprint change |
| Invalid header plus unrelated invalid business request | Discard and generate | Return ordinary safe business error | Use generated value in header/problem where safely producible | Never include rejected raw value | Hide/replace business error with correlation error |

### 15. Implementation Implications

Implementation must provide:

- one centrally owned validation profile shared by relevant adapters;
- a pre-observability API normalization boundary;
- a local, concurrency-safe generator and safe local fallback;
- distinct representation of per-invocation effective correlation and durable
  accepted workflow correlation during replay;
- response-header behavior that always uses the invocation's effective value;
- immutable-message validation and quarantine rather than downstream mutation;
- bounded structured replacement classification without raw values; and
- contract, security, replay, concurrency, injection, failure, and telemetry
  isolation tests corresponding to Section 14.

This ADR does not select an HTTP framework, validation library, logging
library, tracing SDK, telemetry backend, storage schema, or identifier
generation package.

### 16. Open Implementation Choices

The following remain implementation choices within the decision:

- the module and configuration location of the central validation profile;
- the exact maximum header length at or below infrastructure limits;
- the local UUIDv7 generator implementation and independent fallback;
- the bounded safe replacement reason vocabulary;
- how response middleware carries per-invocation context;
- how replay response models distinguish response-header correlation from the
  stored body `correlation_id`;
- exact operational event names and sampling/rate-limiting policy;
- exact quarantine diagnostics permitted for malformed internal messages; and
- test fixtures for protocol-edge failures that occur before application
  parsing.

None may weaken bounded validation, raw-value nonreflection, current
authorization, durable workflow identity, or telemetry failure isolation.

## Consequences

### Positive

- The ADR-0004/ADR-0009 conflict receives one explicit narrow resolution.
- Invalid operational metadata no longer rejects an otherwise valid business
  request.
- Client-controlled unsafe data is removed before observability and contract
  propagation.
- Per-invocation diagnosis and immutable workflow correlation both remain
  available on replay.
- Correlation remains independent from security, idempotency, concurrency, and
  workflow correctness.
- Telemetry outages cannot become API or workflow outages.
- Duplicate correlation identifiers remain safe and operationally useful.

### Negative

- A malformed client value may go unnoticed by the caller unless operational
  diagnostics are inspected.
- Replay responses may intentionally have different values in the response
  header and body, so clients and operators must understand their distinct
  meanings.
- The platform must maintain a central validation profile and local generator
  fallback.
- Correlation grouping is advisory and can be polluted by callers reusing a
  valid value.
- Contract-invalid internal messages cannot be repaired in place and require
  quarantine handling.

## Alternatives Considered

### Reject Every Invalid Client Correlation Identifier

This preserves ADR-0004's original wording but makes optional operational
metadata a business-availability dependency and conflicts with ADR-0009. It
was not selected.

### Propagate or Escape the Raw Invalid Value

Escaping, truncating, hashing, or encoding can still leak attacker-controlled
data, create cardinality pressure, or produce inconsistent identifiers across
components. It was rejected in favor of discard and replacement.

### Always Ignore Client Correlation

Generating every value would simplify trust handling but remove useful
cross-system correlation selected by ADR-0004 and ADR-0009. It was not
selected because bounded validation preserves that value safely.

### Use Correlation as Request Idempotency or Workflow Identity

This would conflate operational metadata with ADR-0011 accepted-request
identity, allow collisions to affect correctness, and create an authorization
risk. It was rejected.

### Rewrite Invalid Correlation Inside Event Bus Messages

Changing a required field would mutate the immutable logical publication and
break message identity and contract evidence. It was rejected in favor of
quarantine or transport-rejection recovery.

## Acceptance Checklist

- [ ] Valid, missing, and invalid API header behavior is unambiguous.
- [ ] Invalid input is discarded and never reflected or propagated.
- [ ] Validation is deterministic, bounded, central/versioned, and occurs
      before observability or contract propagation.
- [ ] The current ADR-0004 lowercase UUIDv7 format remains authoritative.
- [ ] The response header always carries the invocation's effective value when
      a response can safely be produced.
- [ ] First acceptance and replay distinguish invocation correlation from the
      workflow's original durable correlation.
- [ ] Correlation is not security, request, workflow, message, trace,
      deduplication, ordering, concurrency, or idempotency identity.
- [ ] Duplicate values are permitted and operational tooling tolerates them.
- [ ] Telemetry failure cannot fail a committed business transaction.
- [ ] Generator and validation failure behavior fails closed without unsafe
      propagation.
- [ ] Malformed required Event Bus correlation metadata is quarantined rather
      than rewritten.
- [ ] The verification table covers every required scenario.
- [ ] Supersession is limited exactly to ADR-0004's invalid-header rejection.
- [ ] ADR-0009's wider observability architecture remains unchanged.
- [ ] ADR-0011 semantics remain unchanged.
- [ ] No implementation technology or unrelated architecture is selected.

The decision is internally complete. The remaining questions are bounded
implementation choices. If accepted, ADR-0012 resolves the correlation-header
conflict identified in Vertical Slice 01 without changing any other
architecture.

## Related Decisions

- [ADR-0004: API and Contract Standards](ADR-0004-api-and-contract-standards.md)
- [ADR-0009: Observability, Telemetry, and Audit Correlation](ADR-0009-observability-telemetry-and-audit-correlation.md)
- [ADR-0010: Security, Identity, Authorization, and Trust Boundaries](ADR-0010-security-identity-authorization-and-trust-boundaries.md)
- [ADR-0011: Principal-Scoped API Idempotency and Accepted-Request Ownership](ADR-0011-principal-scoped-api-idempotency-and-accepted-request-ownership.md)

## References

- [Platform Architecture](../README.md)
- [Vertical Slice 01](../../implementation/vertical-slice-01.md)
- [Repository security policy](../../../SECURITY.md)
- [Repository Agent guidance](../../../AGENTS.md)
