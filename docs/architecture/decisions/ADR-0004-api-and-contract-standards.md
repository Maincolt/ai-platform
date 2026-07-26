# ADR-0004: API and Contract Standards

- **Status:** Proposed
- **Date:** Not yet accepted
- **Supersedes:** None
- **Superseded by:** None

## Context

ADR-0001 requires open, explicit, versioned, and independently testable
contracts. ADR-0002 requires synchronous request-response contracts for direct
platform services and versioned asynchronous contracts with stable identity,
correlation, causation, idempotency, and partition-scoped ordering. ADR-0003
selects Python as the initial runtime but prohibits Python-specific
representations from becoming platform contracts.

Vertical Slice 01 needs a small synchronous Workflow API and three asynchronous
workflow messages. Those boundaries must remain understandable to future
non-Python consumers and independent of the eventual API framework, Event Bus,
persistence store, and deployment topology.

Without one contract standard, implementation models, API documentation,
message documentation, fixtures, and consumers could drift. Field naming,
identifier encoding, timestamp precision, compatibility, and error behavior
could then become accidental framework or transport behavior.

### Existing Documentation Conflicts

The following inconsistencies are explicit inputs to this proposal:

| Subject | Vertical Slice 01 | This proposal | Required alignment |
| --- | --- | --- | --- |
| Command name | `ExecuteWordCountTask` | `ExecuteTask` | Treat these as two names for the same required command, not two contracts. Before this ADR is Accepted, select one name and update the vertical slice. This ADR proposes `ExecuteTask` because capability-specific behavior belongs in the payload. |
| Outcome classification | `TaskCompleted` and `TaskFailed` are `result` messages and use `message_kind = result` | They are immutable event contracts with `message_kind = event` | Update the vertical-slice terminology if this proposal is Accepted. Their payload semantics do not change. |
| Contract-name field | `event_type` | `contract_name` | Use `contract_name` because the common envelope carries commands and events, not only events. |
| Common timestamp | `occurred_at` for commands and results | `created_at` for every message; event occurrence timestamps remain in event payloads when semantically distinct | Update the vertical-slice envelope if this proposal is Accepted. |
| Partition metadata | `partition_key` appears in the portable envelope | The logical ordering key is `workflow_id`; the derived transport partition key remains outside the domain envelope | Update the vertical-slice envelope if this proposal is Accepted. ADR-0005 will define the transport mapping. |

There is also a repository-index inconsistency unrelated to the contract
decision: ADR-0002 is marked Accepted in its own file but Proposed in the ADR
index. This ADR does not resolve that metadata issue.

## Decision Drivers

The decision is evaluated against:

- vendor neutrality and future non-Python consumers;
- interoperability across languages, processes, and transports;
- explicit, human-readable, and machine-validatable contracts;
- backward and forward compatibility;
- deterministic serialization where identity or hashes require it;
- support for synchronous and asynchronous workflows;
- independent component evolution;
- Python implementation compatibility without Python coupling;
- operational traceability through stable identifiers and timestamps;
- security, privacy, bounded inputs, and data minimization;
- reproducible generated documentation; and
- deterministic repository-owned testing.

## Decision

### 1. Contract Categories

The platform recognizes these contract categories.

#### API Contracts

API contracts define synchronous Workflow API requests, responses, and errors.
Query responses are API responses, not events. Vertical Slice 01 defines only:

- submission of a workflow;
- retrieval of a workflow; and
- the already-required liveness and readiness operations.

#### Command Contracts

Commands are imperative requests for one component to perform an action. A
command can be accepted, rejected, duplicated, delayed, or fail; its existence
does not assert that the requested action happened.

Vertical Slice 01 has one command contract. This ADR proposes the semantic name
`ExecuteTask`. It is the same command currently called
`ExecuteWordCountTask` in the vertical slice and does not add a second command.

#### Event Contracts

Events are factual, immutable statements about something that completed or
failed. They must use past-tense semantic names and must not be interpreted as
hidden commands.

Vertical Slice 01 has only:

- `TaskCompleted`; and
- `TaskFailed`.

The event payloads preserve the vertical slice's success and safe failure
semantics. No startup, heartbeat, task-started, audit, workflow-terminal, or
dead-letter domain event is introduced.

#### Configuration Contracts

The existing versioned capability manifest is a configuration contract. It is
governed by the same schema, naming, versioning, validation, example, and
security rules, but it is not an API request or asynchronous message.

Internal domain models, persistence records, Python classes, and transport
metadata are not automatically shared contracts. A model becomes a contract
only when it crosses a documented boundary.

### 2. Contract Definition Technology

#### Evaluation

| Option | Language neutrality | Validation and evolution | Documentation fit | Python and non-Python experience | Outcome |
| --- | --- | --- | --- | --- | --- |
| JSON Schema Draft 2020-12 | Language-neutral and aligned with JSON | Rich structural validation, reusable references, explicit dialect, and machine-comparable schemas; semantic compatibility still requires policy | Reusable from OpenAPI and AsyncAPI with tooling-dependent integration | Broad validators and generators; maps naturally to Python models without making them authoritative | Selected as the canonical data-schema format |
| OpenAPI schemas alone | Language-neutral for HTTP APIs | Strong for synchronous request and response shapes, but couples shared schemas to an API-description dialect | Excellent HTTP operation and documentation support | Broad client and server tooling | Selected for API documentation, not as the canonical shared schema source |
| AsyncAPI schemas alone | Protocol-agnostic message documentation | Describes messages, channels, operations, and bindings, but its native Schema Object is not the one canonical format for every boundary | Strong asynchronous documentation | Useful across languages and transports | Selected for asynchronous documentation, not as the canonical shared schema source |
| Protocol Buffers | Language-neutral schema language with strong code generation and mature binary evolution rules | Field-number discipline supports efficient binary compatibility; ProtoJSON has separate compatibility and presence rules | Does not directly describe the Workflow HTTP surface or message operations without additional formats | Strong generated clients but introduces compiler and generated-code workflows | Rejected for this JSON-first slice because no binary-performance or compactness requirement justifies a second wire model |
| Python-only Pydantic models | Excellent Python validation and model ergonomics | Evolution is tied to Python implementation behavior unless schemas are exported and governed separately | Can generate JSON Schema, but does not describe operations by itself | Couples the source of truth to Python and weakens future non-Python ownership | Rejected as the canonical contract source |

#### Selected Contract Stack

- JSON is the baseline wire representation.
- JSON Schema Draft 2020-12 is authoritative for portable data shape,
  constraints, and reusable definitions.
- OpenAPI 3.1.1 documents the synchronous HTTP operations and references the
  canonical JSON Schemas. It is selected because its Schema Object is based on
  JSON Schema Draft 2020-12. Moving to a later OpenAPI feature version requires
  a reviewed tooling-compatibility change.
- AsyncAPI 3.0.0 documents commands, events, logical channels, producers,
  consumers, correlation, and message semantics. Its Multi Format Schema
  support must reference the canonical Draft 2020-12 schemas without silently
  downgrading their meaning. A tool that cannot preserve those references is
  not suitable. AsyncAPI must not select a broker-specific binding before
  ADR-0005.
- Python runtime models are implementation artifacts. They may be generated
  from the schemas or maintained explicitly, but automated parity tests are
  mandatory either way.

If a Python model, OpenAPI document, AsyncAPI document, example, or generated
client disagrees with a canonical JSON Schema, the canonical schema and this
ADR's semantic rules are authoritative. The disagreeing artifact is defective
and must not be released.

OpenAPI and AsyncAPI remain authoritative for operation-level information that
JSON Schema does not express, such as HTTP paths, status codes, logical
channels, send or receive direction, and producer or consumer ownership. They
must reference rather than redefine shared data shapes.

### 3. JSON and Serialization Standards

#### Baseline Representation

- Wire documents use JSON encoded as UTF-8 without a byte-order mark.
- Normal API and asynchronous bodies use `application/json`.
- API problem responses use `application/problem+json`.
- JSON property names are stable and case-sensitive.
- JSON booleans are only `true` and `false`.
- Numeric values must be finite JSON numbers. `NaN`, positive or negative
  infinity, and numeric strings used in place of declared numbers are invalid.
- Integer concepts use JSON integers. Floating-point values are introduced only
  when a contract defines their precision and comparison semantics.
- Duplicate object property names are invalid.
- JSON object field order has no semantic meaning.
- Array order is semantically significant unless a contract explicitly defines
  the array as an unordered collection.

#### Omission and Null

A required field is present and non-null unless its schema explicitly includes
`null`. An optional field is omitted when it does not apply or was not
provided. Explicit `null` is allowed only when it has a documented meaning
different from omission.

The common envelope's `causation_id` is the deliberate exception: it is
required and nullable so `null` unambiguously means that the root command has
no predecessor message.

Defaults are contract semantics, not serializer conveniences. A default must
be documented and materialized before semantic comparison or fingerprinting.
Removing or changing a default follows the compatibility rules below.

#### Unknown Properties

Producers must emit only fields documented by the exact schema version they
declare. They may not silently add implementation-specific properties.

Every object schema explicitly declares `additionalProperties`; it must not
rely on JSON Schema's permissive default. Closed objects set it to `false`.
Documented extension points set it to `true` or constrain additional values
with a schema.

Objects intended for additive evolution are marked extensible in their schema.
Consumers that claim support for a contract major version must ignore unknown
properties only at those documented extension points while continuing to
validate all known fields. Security-sensitive objects are closed and reject
unknown properties. A producer must not rely on an unknown property affecting
an older consumer's behavior.

#### Canonical Serialization

Normal wire JSON need not use a canonical property order. Where deterministic
bytes are required for a request fingerprint, hash, or signature, use the JSON
Canonicalization Scheme in RFC 8785 after runtime validation and default
materialization.

For API request idempotency, compute a SHA-256 digest of the RFC 8785 canonical
UTF-8 bytes and store the lowercase hexadecimal digest with the accepted
request mapping. Raw request bytes are never compared.

### 4. Naming Conventions

| Element | Convention | Example |
| --- | --- | --- |
| JSON properties | lowercase `snake_case` | `task_attempt_id` |
| API paths | lowercase plural nouns; hyphens only for multiword path segments | `/api/v1/workflows` |
| Path and query parameters | lowercase `snake_case` | `workflow_id` |
| HTTP headers | established standard name where one exists; otherwise descriptive hyphenated words without `X-` | `Correlation-Id` |
| Semantic contract names | `PascalCase`, commands imperative and events past tense | `ExecuteTask`, `TaskCompleted` |
| Contract kinds | lowercase `snake_case` | `command`, `event` |
| Business enum values | uppercase `UPPER_SNAKE_CASE` | `DISPATCHED` |
| Stable error codes | uppercase `UPPER_SNAKE_CASE` | `REQUEST_ID_CONFLICT` |
| JSON Schema filenames | lowercase `snake_case.schema.json` | `task_completed.schema.json` |
| Version directories | `v` followed by the major integer | `v1` |
| JSON Schema identifiers | stable versioned URNs | `urn:ai-platform:contract:message:task-completed:1.0` |

Names use complete platform terms rather than unexplained abbreviations.
Capability identifiers such as `text.word-count` retain their documented
dot-separated form and are not JSON property names.

HTTP header names are case-insensitive on the wire. Documentation uses the
spelling shown above consistently. The request body, not a duplicate header,
contains `request_id`.

### 5. Common Asynchronous Message Envelope

Commands and events use one transport-neutral envelope.

| Field | Required | Creator and format | Immutable meaning |
| --- | --- | --- | --- |
| `message_id` | Yes | The producer creates a lowercase UUIDv7 | Identifies one exact logical publication and remains stable across transport redelivery |
| `message_kind` | Yes | The producer sets `command` or `event` | Distinguishes imperative requests from immutable facts |
| `contract_name` | Yes | The producer uses the registered `PascalCase` contract name | Selects the payload semantics |
| `contract_version` | Yes | The producer uses a `MAJOR.MINOR` string such as `1.0` | Selects the exact published schema and compatibility line |
| `created_at` | Yes | The producer sets an RFC 3339 UTC timestamp | Time the immutable logical message was created |
| `correlation_id` | Yes | Propagated from valid context or created by the Orchestrator as a lowercase UUIDv7 | Connects the complete end-to-end interaction |
| `causation_id` | Yes, nullable | The producer copies the direct predecessor `message_id`; `null` only for the root command | Links one message to its direct causal message without overloading identifier types |
| `workflow_id` | Yes | The Orchestrator creates a lowercase UUIDv7 | Identifies the workflow aggregate |
| `task_id` | Yes | The Orchestrator creates a lowercase UUIDv7 | Identifies the logical task across application attempts |
| `task_attempt_id` | Yes | The Orchestrator creates a lowercase UUIDv7 | Identifies one business execution attempt and is the Agent idempotency key |
| `producer` | Yes | The producer supplies an object containing stable `component` and UUIDv7 `instance_id` values | Identifies the logical producer and runtime instance without exposing a host or transport address |
| `payload` | Yes | The producer serializes a validated contract-specific object | Contains only the data defined by `contract_name` and `contract_version` |

All envelope fields are immutable after message creation. Republishing the same
logical message preserves the complete envelope and payload.

`created_at` replaces the vertical slice's proposed common `occurred_at`.
Commands are created, not facts that occurred. The generic `occurred_at` name
is therefore not part of the common envelope. An event payload uses a more
specific timestamp such as `completed_at` or `failed_at` when that time is
semantically distinct. A producer must not overwrite that domain time with
publication or broker time.

The `ExecuteTask` payload carries the command-specific `request_id`,
`attempt_number`, selected Agent, capability, input, and
`task_result_deadline`. Capability and request fields do not belong in every
message envelope.

Transport metadata remains outside the portable envelope, including:

- broker, topic, queue, subscription, and routing names;
- partition, offset, delivery count, and acknowledgement state;
- broker receipt or publication timestamps; and
- dead-letter location and transport retry metadata.

ADR-0002 requires ordering within a workflow partition. For this slice,
`workflow_id` is the logical ordering key. ADR-0005 maps it to the selected
transport without serializing a duplicate `partition_key` in the domain
envelope.

### 6. Identifier Standards

#### Evaluation

| Format | Uniqueness and ordering | Interoperability and support | Trade-offs |
| --- | --- | --- | --- |
| UUIDv4 | 122 random bits; no time order | IETF-standardized and universally supported | Excellent opaque uniqueness but random indexes have poor locality and identifiers provide no creation ordering |
| UUIDv7 | Time-ordered Unix-millisecond prefix plus random or monotonic entropy | Standardized by RFC 9562; supported by Python 3.14 and growing cross-language ecosystems | Improves index locality and rough chronological sorting, but exposes approximate creation time and requires clock-rollback-safe generation |
| ULID | Lexicographically sortable timestamp plus randomness | Widely implemented but not an IETF UUID format | Compact human handling, but canonical casing, monotonic generation, and library behavior vary more across ecosystems |

UUIDv7 is the default for all platform-generated public identifiers. It offers
standard UUID interchange, time locality, and native support in the accepted
Python 3.14 runtime without introducing a platform-specific format.

Identifiers are serialized as canonical lowercase, hyphenated UUID strings.
They remain opaque at boundaries: consumers must not derive authorization,
business state, or exact event time from their encoded timestamp. Database
sequences are not public cross-component identifiers.

#### Ownership

- `request_id` identifies one logical submission. The API client should create
  it; the Workflow API creates and returns a UUIDv7 when it is omitted. The
  first creator owns the value, and acceptance makes it immutable.
- `workflow_id`, `task_id`, and `task_attempt_id` are created and owned by the
  Orchestrator.
- `task_attempt_id` is the business idempotency key for exactly one execution
  attempt.
- `message_id` is created by each message producer and identifies one exact
  command or event publication.
- `correlation_id` is accepted from valid external context or created by the
  Orchestrator. Its format is UUIDv7.
- `causation_id` is not independently generated. It is either the direct
  predecessor `message_id` or `null` for the root command.

Generators must tolerate clock rollback and concurrent creation. UUID ordering
is useful for storage locality and diagnostics but never replaces explicit
domain timestamps or ordering guarantees.

### 7. Timestamp Standards

Contract timestamps use RFC 3339-compatible UTC strings:

- uppercase `T` date-time separator;
- exactly six fractional-second digits;
- uppercase `Z` UTC designator;
- no local timestamps;
- no offset other than `Z`; and
- no timestamp without an offset.

The standard representation is:
`YYYY-MM-DDTHH:MM:SS.ffffffZ`. Six digits provide one stable cross-component
shape; they do not claim that the source clock is accurate to a microsecond.

Each timestamp name must describe one semantic instant:

| Timestamp | Meaning |
| --- | --- |
| API request receipt time | When the platform accepted the inbound request bytes for processing |
| Workflow transition time | When the Orchestrator durably applied a named state transition |
| Message `created_at` | When the producer created the immutable logical command or event |
| Event `completed_at` or `failed_at` | When the Agent established the terminal outcome |
| Persistence time | Internal storage metadata; not a domain contract unless explicitly exposed |
| Broker receipt or publication time | Transport metadata outside the domain contract |

Only timestamps with a documented business or operational use are included.
Broker timestamps must not replace domain timestamps.

### 8. Workflow API Standards

#### Protocol and Versioning

The Workflow API uses synchronous HTTP with JSON bodies. The base path is
`/api/v1`; the URL carries the API major version.

URL path versioning is selected for the first slice because it is visible in
logs, links, routing, generated clients, and manual testing. Header versioning
is less discoverable. Vendor-specific media-type versioning complicates
content negotiation without providing a current benefit.

Only these operations are defined:

| Method and path | Purpose | Success |
| --- | --- | --- |
| `POST /api/v1/workflows` | Submit one workflow | `202 Accepted` for a new accepted workflow; `200 OK` for an equivalent previously accepted `request_id` |
| `GET /api/v1/workflows/{workflow_id}` | Retrieve durable current workflow state | `200 OK` |
| `GET /health/live` | Report process liveness | `200 OK` when live |
| `GET /health/ready` | Report platform-service readiness | `200 OK` when ready; a non-success status otherwise |

Health paths are operational and unversioned. They must not expose
configuration, credentials, dependency addresses, stack traces, or workflow
data.

Requests use `Content-Type: application/json` and UTF-8. Successful responses
use `application/json`; error responses use `application/problem+json`.
Unsupported media types use HTTP `415`, oversized bodies use `413`, and invalid
JSON or contract validation uses `400`.

The optional `Correlation-Id` request header carries a UUIDv7. Invalid supplied
correlation context is rejected rather than silently propagated. When absent,
the Orchestrator creates a correlation identifier and returns it in the
response body and `Correlation-Id` response header.

#### Submission Semantics

- A new valid submission is accepted only when the configured compatible Test
  Agent is ready.
- If no ready Agent exists, return HTTP `503` and
  `AGENT_TEMPORARILY_UNAVAILABLE` before workflow creation. Include
  `Retry-After` only when a meaningful bounded value is known.
- An equivalent accepted `request_id` returns the existing identifiers and
  current state. It does not re-evaluate Agent readiness or create another
  workflow.
- The same accepted `request_id` with a different canonical request returns
  HTTP `409` and `REQUEST_ID_CONFLICT`.
- Workflow retrieval remains available independently of Agent readiness.
- A missing workflow returns HTTP `404` and `WORKFLOW_NOT_FOUND`.

### 9. API Error Contract

API errors use RFC 9457 Problem Details with
`application/problem+json`.

| Field | Required | Rule |
| --- | --- | --- |
| `type` | Yes | Stable problem-type URI or URN |
| `title` | Yes | Short, stable, safe human summary |
| `status` | Yes | HTTP status repeated as an integer |
| `detail` | Yes | Safe occurrence-specific explanation; replaces a duplicate custom `message` field |
| `error_code` | Yes | Stable machine-readable `UPPER_SNAKE_CASE` extension |
| `correlation_id` | Yes | UUIDv7 for support and trace correlation |
| `details` | No | Bounded array of documented detail objects |

Validation detail objects contain only a stable code, a JSON Pointer path, and
a safe message. Their item count, path length, and message length are bounded.
They must not echo secrets, complete prompts, provider payloads, or excessively
large invalid values.

Stable initial errors are:

| Error code | HTTP status | Retry semantics |
| --- | --- | --- |
| `INVALID_REQUEST` | `400` | Correct the request before retrying |
| `UNSUPPORTED_CONTRACT_VERSION` | `400` | Use a supported API or message contract version |
| `REQUEST_ID_CONFLICT` | `409` | Do not retry with different content under the same `request_id` |
| `WORKFLOW_NOT_FOUND` | `404` | Do not assume retry will create the workflow |
| `AGENT_TEMPORARILY_UNAVAILABLE` | `503` | A later retry with the same request is allowed because no workflow or accepted-request mapping was created |
| `INTERNAL_PROCESSING_FAILURE` | `500` | Retry only according to documented client policy and reuse `request_id` to avoid duplicate creation |

Clients make decisions from HTTP status, `error_code`, and documented retry
semantics, never from `title` or `detail` text. Internal exception types,
transport failures, stack traces, provider details, hostnames, and secret
configuration are never returned.

### 10. Contract Versioning

API, command, event, and manifest contracts use `MAJOR.MINOR` versions:

- major changes are incompatible;
- minor changes are backward-compatible additions or clarifications permitted
  by the compatibility matrix; and
- documentation-only corrections that do not change validation or semantics do
  not change the contract version.

This is simpler than full Semantic Versioning because implementation patches do
not describe wire compatibility. It is more expressive than an integer major
alone because producers and consumers can identify an exact additive schema.

The API URL carries only the major version, such as `/api/v1`. OpenAPI metadata
records the full API contract version. Asynchronous envelopes and capability
manifests carry the full `MAJOR.MINOR` string. Canonical schema paths use the
major directory, while `$id` and schema metadata identify the full version.

A breaking change includes:

- adding a required field without a backward-compatible default protocol;
- removing or renaming a field;
- changing a field type, nullability, or semantic meaning;
- narrowing previously valid inputs;
- removing an enum value;
- changing identifier or timestamp encoding;
- moving data between envelope and payload; or
- changing command or event meaning while retaining its name.

Optional fields may be added in a minor version only when old behavior remains
valid when the field is absent and old consumers are protected by documented
unknown-field behavior or version negotiation. Required fields are not added
within a major version.

Enum additions are conditionally compatible because strict consumers may fail
on unknown values. A producer must not emit a new enum value to a consumer that
has not declared support.

Deprecated fields and versions remain documented during a migration window.
Producers and consumers may support more than one major version simultaneously.
Removing an old major requires usage evidence, an announced support window, a
migration plan, and contract-owner approval. The exact minimum support period
remains an open policy question.

### 11. Compatibility Matrix

For this matrix:

- **backward compatible** means a new consumer can process valid older data;
- **forward compatible** means an older consumer can process valid newer data;
- **conditionally compatible** means safety depends on an explicit condition;
  and
- **breaking** requires a new major version unless an exact-version negotiation
  prevents incompatible peers from exchanging data.

| Change | Backward | Forward | Classification and rule |
| --- | --- | --- | --- |
| Add optional field with no new required semantics | Yes | Conditional on documented unknown-field tolerance | Minor |
| Add required field | No | Not sufficient even if an old consumer ignores it | Breaking |
| Remove field | Conditional for already-tolerant readers | Conditional for optional old readers | Breaking by platform policy after deprecation |
| Rename field | No | No | Breaking |
| Change field type or nullability | No | No | Breaking |
| Widen accepted validation | Yes | No when an old consumer receives newly valid values | Conditional minor only with capability or version negotiation |
| Narrow accepted validation | No | Yes only for values still in the narrowed set | Breaking |
| Add enum value | Yes | Conditional; strict old consumers may reject it | Minor only when emission is negotiated |
| Remove enum value | No for old data containing it | Conditional | Breaking |
| Change semantic meaning without changing shape | No | No | Breaking |
| Change a default | No | No | Breaking unless proven observationally equivalent |
| Move field between envelope and payload | No | No | Breaking |

Unknown-field tolerance does not authorize producers to emit undocumented
fields. It is a consumer resilience rule for published compatible evolution.

### 12. Idempotency

#### API Request Idempotency

`request_id` identifies one logical workflow submission.

- The same accepted `request_id` with an equivalent request returns the
  existing workflow identifiers and current workflow state.
- The same accepted `request_id` with a different request returns
  `REQUEST_ID_CONFLICT`.
- The accepted-request mapping and workflow are created atomically and uniquely
  by `request_id`.
- The Workflow API never creates two workflows for one accepted `request_id`.
- Rejections before workflow creation do not reserve the `request_id`.

Equivalent requests are compared after validation and default materialization.
The canonical semantic object contains:

- exact workflow text as decoded, without trimming or Unicode normalization;
- capability name;
- capability version;
- API contract major version; and
- every future field documented as execution-semantic.

It excludes property order, JSON whitespace, correlation metadata, transport
headers, and other nonsemantic request data. The platform stores the SHA-256
fingerprint of the RFC 8785 canonical semantic object, not raw JSON text.

#### Agent Execution Idempotency

`task_attempt_id` identifies one business execution attempt. Repeated delivery
of the same attempt must return or republish the stored outcome and must not
duplicate execution side effects.

The same `task_attempt_id` with a different command `message_id` is a
conflicting command and fails safely. A future application retry creates a new
`task_attempt_id`; transport redelivery does not.

#### Message Deduplication

`message_id` identifies one exact logical command or event publication.
Consumers deduplicate by consumer identity and `message_id`. This is separate
from business idempotency by `task_attempt_id`.

Transport delivery counters and retry attempts are not public contract fields.

### 13. Correlation and Causation

`correlation_id` connects the complete API request, workflow, command, events,
state transitions, and logs.

- A valid client `Correlation-Id` initializes correlation context.
- If the client omits it, the Orchestrator creates a UUIDv7.
- Every command and resulting event propagates the same `correlation_id`.
- Logs restore correlation only from a validated request or message.

`causation_id` always references a prior `message_id`; it never sometimes means
`request_id`.

- The root `ExecuteTask` command has `causation_id = null` because an HTTP
  request is not a message publication.
- `TaskCompleted` or `TaskFailed` sets `causation_id` to the command's
  `message_id`.
- A future message caused by an event references that event's `message_id`.

`request_id` remains available in the workflow record and root command payload
for API idempotency and audit. It is not overloaded as message causation.

### 14. Contract Ownership

- The Workflow API owns its HTTP request, response, status, and problem
  contract surface.
- The Orchestrator owns workflow-domain semantics, domain identifiers,
  transitions, and command creation.
- The producer of a message owns conformance of the emitted envelope and
  payload.
- An Agent owns how it computes an outcome, but emits result payloads only
  within the shared accepted `TaskCompleted` or `TaskFailed` contract.
- Shared schemas, operation descriptions, examples, and compatibility records
  are versioned in this repository.
- Consumers reference shared schemas and must not maintain divergent local
  copies.
- No component may silently extend, reinterpret, or weaken a shared contract.

A breaking change requires approval from the contract owner and every known
affected producer and consumer through a pull request. It requires a new ADR
when it changes an architectural boundary or this compatibility policy.

### 15. Runtime Validation

Validation occurs at every trust boundary:

- the Workflow API validates media type, size, JSON syntax, schema, format, and
  domain constraints before workflow creation;
- consumers validate the complete envelope, declared contract version,
  producer, identifiers, relationships, and payload before processing;
- unsupported versions are rejected with stable semantics;
- configuration and capability manifests are validated separately from API and
  message contracts;
- unvalidated dictionaries do not enter domain logic; and
- producers serialize only validated contract models.

Static Python typing does not perform runtime validation and does not replace
these checks.

A Python implementation may use Pydantic or another runtime-validation library,
but this ADR does not select one. Any such library is an adapter to the
canonical JSON Schemas. Library-specific coercion must not broaden the wire
contract; for example, a numeric string must not become a valid integer unless
the schema permits a string.

### 16. OpenAPI and AsyncAPI Documentation

OpenAPI documents:

- the three required HTTP operation groups;
- request, response, parameter, header, status, media-type, and problem
  semantics; and
- reusable references to canonical JSON Schemas.

AsyncAPI documents:

- `ExecuteTask`, `TaskCompleted`, and `TaskFailed`;
- logical channels and send or receive operations;
- the common envelope and payload schemas;
- producer and consumer ownership;
- correlation and causation behavior; and
- logical ordering by `workflow_id`.

No broker binding, topic name, queue name, or server technology is included
before ADR-0005.

Canonical source schemas and source operation descriptions are committed.
Reproducibly generated, fully bundled OpenAPI and AsyncAPI JSON artifacts are
also committed because the repository is the source of truth, reviewers need
stable diffs, and self-hosted development must not require an online generator.

Generated files are never edited manually. Generation uses pinned tooling and
stable commands. When CI exists, it must regenerate into a clean workspace and
fail on drift. Until CI exists, contributors run and report the same check
locally. A generator limitation must not be resolved by changing generated
data away from the canonical schema.

### 17. Schema Repository Structure

When contract implementation begins, use this logical layout:

```text
contracts/
├── schemas/
│   ├── api/
│   │   └── v1/
│   ├── messages/
│   │   └── v1/
│   │       ├── execute_task.schema.json
│   │       ├── task_completed.schema.json
│   │       └── task_failed.schema.json
│   └── common/
│       └── v1/
├── definitions/
│   ├── openapi/
│   │   └── v1/
│   └── asyncapi/
│       └── v1/
├── examples/
│   └── v1/
└── generated/
    ├── openapi/
    │   └── v1/
    └── asyncapi/
        └── v1/

src/ai_platform/contracts/
└── Python runtime models and contract adapters

tests/contract/
├── fixtures/
└── repository-owned contract tests
```

`contracts/schemas/` is the canonical wire-schema source.
`contracts/definitions/` contains authored operation and channel descriptions
that reference the schemas. `contracts/generated/` contains committed generated
bundles. `src/ai_platform/contracts/` contains nonauthoritative Python
implementation models. Test-only invalid, boundary, and compatibility fixtures
remain under `tests/contract/`.

This is a Git-owned contract directory, not a deployed schema registry.

### 18. Contract Examples

Every public contract has at least one valid illustrative example. API errors
and failure events also have safe failure examples.

Examples:

- use realistic synthetic data;
- validate against the exact canonical schema version;
- are reused by OpenAPI, AsyncAPI, documentation, and contract tests where
  practical;
- contain no real credentials, prompts, customer data, provider responses, or
  secrets; and
- avoid identifiers or addresses copied from real environments.

Examples are illustrative, not normative. Schemas and documented semantics
remain authoritative. Golden examples are immutable test inputs for a version,
not a substitute for property and compatibility tests.

### 19. Contract Testing

The repository-owned pytest strategy from ADR-0003 remains unchanged.
Contract tests run locally unless they intentionally verify a separately
operated service.

Required coverage includes:

- canonical schema self-validation and example validation;
- producer tests proving emitted documents conform to the declared exact
  version;
- consumer tests for every supported version;
- serialization and deserialization round trips;
- compatibility tests for every schema change;
- unknown-field tests at extensible and closed object boundaries;
- unsupported-version rejection;
- lowercase UUIDv7 and timestamp-format tests;
- API request fingerprint and idempotency tests;
- Agent execution-idempotency and message-deduplication tests;
- correlation and causation propagation;
- stable API problem and validation-detail tests;
- OpenAPI and AsyncAPI reference and generation checks; and
- generated-artifact drift checks.

No third-party contract-testing service or hosted schema registry is selected.
Tests use repository schemas, examples, deterministic clocks, and controlled
identifier generators.

### 20. Security and Privacy

Contract validity does not imply authentication, authorization, or permission.
Those checks remain mandatory at the relevant trust boundary.

- Commands and events contain only data required by the receiving contract.
- Secrets, provider credentials, authorization tokens, internal connection
  details, and full exception information are prohibited.
- Fields that may contain confidential, personal, prompt, or workflow data
  must be classified and have documented logging and retention rules.
- Full workflow input is not logged by default.
- Logs use identifiers and safe outcome metadata; redaction occurs before
  serialization to logs or errors.
- String lengths, collection counts, nesting depth, and total payload size are
  bounded by schemas or boundary policy.
- Malformed, malicious, deeply nested, or excessively large payloads are
  rejected before domain processing.
- Unknown fields never grant capability or authorization.
- External AI data rules in `SECURITY.md` apply before contract data crosses a
  provider boundary.

This ADR defines contract shape and validation. It does not select an
authentication provider or authorization model.

### 21. Coherent Contract Standard

The proposed platform contract stack is:

- HTTP and UTF-8 JSON for the synchronous Workflow API;
- UTF-8 JSON for asynchronous commands and events;
- JSON Schema Draft 2020-12 as the canonical data-schema representation;
- OpenAPI 3.1.1 for synchronous operation documentation;
- AsyncAPI 3.0.0 for asynchronous operation and message documentation;
- committed, versioned source schemas and reproducibly generated bundles;
- Python runtime models validated for parity but never authoritative;
- lowercase UUIDv7 identifiers;
- RFC 3339 UTC timestamps with six fractional digits and `Z`;
- `snake_case` JSON properties and stable semantic `PascalCase` contract names;
- `MAJOR.MINOR` contract versions with explicit major compatibility;
- one transport-neutral command and event envelope;
- RFC 9457 API problem responses with stable error codes;
- RFC 8785 plus SHA-256 request fingerprints; and
- strict repository-owned contract, compatibility, idempotency, and security
  tests.

## Alternatives Considered

### Python Models as the Source of Truth

Pydantic or dataclass models could generate schemas and documentation. This
would reduce initial Python duplication, but contract meaning would depend on
Python coercion, defaults, library versions, and generator behavior. It is not
selected because future non-Python consumers and independent components need a
runtime-neutral source of truth.

### OpenAPI as the Only Contract Source

OpenAPI could define HTTP shapes and export shared components for messages. It
is not selected as the only source because message contracts and shared data
would become subordinate to the synchronous API description.

### AsyncAPI as the Only Contract Source

AsyncAPI could contain both message schemas and reusable data definitions. It
does not describe the Workflow HTTP operations as directly as OpenAPI and its
Schema Object dialect should not become the canonical source for every
boundary.

### Protocol Buffers for All Boundaries

Protocol Buffers provides efficient binary encoding, strong code generation,
and mature field evolution. It is rejected for the first slice because the
platform already requires human-readable JSON APIs and documentation, has no
measured binary requirement, and would otherwise maintain both Protobuf and
JSON semantics.

### Framework-Generated Schemas Only

The selected web framework could generate OpenAPI and JSON Schema from route
and model declarations. This is rejected because framework behavior would
become authoritative, asynchronous schemas would remain separate, and contract
review would require implementation knowledge.

### Header or Media-Type API Versioning

Header versioning keeps paths stable, while vendor media types can version
representations precisely. Both are rejected for the first slice because URL
major versioning is easier to discover, route, log, test, and use manually.

### UUIDv4 or ULID

UUIDv4 is simpler and maximally mature but lacks useful sort and index locality.
ULID is compact and sortable but has less uniform standard-library and
canonicalization support. UUIDv7 provides both IETF-standard UUID interchange
and time locality in the accepted runtime.

### Uncommitted Generated Documentation

Generating documentation only on demand avoids generated-file diffs, but makes
review, offline use, and Git-first auditability dependent on local tool
execution. Committed generated bundles with deterministic drift checks are
selected instead.

## Consequences

### Positive Consequences

- Components and future non-Python consumers share one portable contract
  vocabulary.
- Canonical schemas, examples, operation descriptions, and generated
  documentation are reviewable in Git.
- Runtime validation and compatibility tests make boundary behavior explicit.
- UUIDv7, timestamps, correlation, causation, and stable errors improve
  operational traceability.
- API request, Agent execution, and message-delivery idempotency remain
  distinct and testable.
- Transport and persistence details do not leak into domain contracts.

### Negative Consequences

- Canonical schemas and Python runtime models create parity work.
- OpenAPI, AsyncAPI, and generated bundles add files and generation tooling.
- Strict compatibility governance slows casual schema changes.
- UUIDv7 generation requires clock-rollback-safe implementations.
- Forward-compatible unknown-field handling is more complex than rejecting
  every unrecognized property.
- Committed generated artifacts create review noise when tooling changes.

### Migration Impact

There is no implementation to migrate. Before Vertical Slice 01 contract
implementation begins:

- resolve the `ExecuteTask` versus `ExecuteWordCountTask` name;
- align `result` terminology to immutable events or amend this proposal;
- align the envelope to `contract_name`, `created_at`, and transport-external
  partition metadata;
- create the contract directory only in the implementation phase that needs
  it; and
- select pinned validation and generation tools without changing the canonical
  authority rules.

### Developer Impact

- Contract changes begin with canonical schemas and semantic documentation.
- Producers and consumers use shared definitions rather than local copies.
- Python models require parity and round-trip tests.
- Developers update valid examples and compatibility tests with every contract
  change.
- Contributors regenerate and review OpenAPI and AsyncAPI bundles locally until
  CI automation exists.

### CI Impact

When CI is introduced, platform-neutral commands must verify:

- schema and example validity;
- producer, consumer, compatibility, and serialization tests;
- generated OpenAPI and AsyncAPI drift; and
- repository formatting and existing ADR-0003 quality checks.

This ADR does not claim that CI currently exists and does not select a
CI-specific action or service.

### Operational Impact

- Logs, API problems, messages, and persisted workflow records can be joined by
  stable identifiers.
- Operators can distinguish a business attempt from a transport redelivery.
- Version rejection and compatibility failures have stable diagnostic codes.
- Contract and generated-document versions must be visible in deployments.
- Payload limits, deprecation windows, and schema-release ownership require
  operational policy before production use.

### Future Review Triggers

Review or supersede this decision when:

- a measured requirement justifies a binary wire format;
- a non-Python consumer exposes an interoperability gap;
- JSON Schema, OpenAPI, or AsyncAPI evolution makes the selected combination
  incompatible;
- canonicalization or UUIDv7 behavior differs across supported languages;
- generated-artifact maintenance repeatedly creates more risk than value;
- contract volume requires schema-registry infrastructure;
- signed messages or field-level encryption are required; or
- external API compatibility commitments require a different version policy.

## Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| Schema and implementation drift | Make JSON Schema authoritative; require parity, producer, consumer, and round-trip tests |
| Generated documentation drift | Pin generation tools, commit bundles, prohibit manual edits, and verify clean regeneration |
| Strict consumers break on enum additions | Treat additions as conditionally compatible and negotiate support before emission |
| Python models become the accidental source of truth | Review schema changes first and fail parity checks when models differ |
| Excessive version proliferation | Use major changes only for incompatibility and minor changes for governed additive evolution |
| Schemas are duplicated across OpenAPI and AsyncAPI | Reference canonical files and fail generation when a tool rewrites shared meaning |
| Sensitive workflow data leaks | Minimize payloads, classify sensitive fields, prohibit secrets, and test redaction and examples |
| Consumers ignore `contract_version` | Validate supported versions before payload processing and test rejection |
| Timestamp or UUID implementations disagree | Use RFC-defined formats, fixed timestamp precision, canonical lowercase strings, and cross-language vectors |
| OpenAPI and AsyncAPI represent shared schemas differently | Treat canonical JSON Schema as authoritative and test generated representations against it |
| Unknown fields alter behavior | Permit them only at declared extension points and prohibit producers from relying on unknown semantics |
| UUIDv7 exposes approximate creation time | Treat IDs as opaque and avoid using them where timestamp disclosure is unacceptable |
| Request fingerprints differ across implementations | Validate and materialize defaults before RFC 8785 canonicalization; share test vectors |

## Assumptions

- ADR-0001, ADR-0002, and ADR-0003 remain Accepted and govern architecture,
  communication, and runtime tooling.
- Vertical Slice 01 still contains only one workflow command and two terminal
  outcome messages.
- The initial Workflow API is HTTP-accessible in a local or internal
  environment.
- JSON payload size and performance are sufficient for the first slice.
- Future non-Python consumers can support JSON, JSON Schema, UUIDv7, and RFC
  3339 timestamps.
- The Event Bus selected by ADR-0005 can carry opaque UTF-8 JSON and transport
  metadata separately.
- The persistence decision can enforce unique request mappings and store
  canonical request fingerprints.
- No concrete framework, validator, generator, broker, or schema registry is
  accepted by this ADR.

## Open Questions

1. What minimum support and deprecation period applies to an old contract major
   version?
2. What exact maximum body size, string length, collection count, and nesting
   depth applies to each first-slice contract?
3. Which maintainers own contract release coordination and version-support
   announcements?
4. Which pinned, vendor-neutral tools will validate schemas and generate or
   bundle OpenAPI and AsyncAPI artifacts?

These questions affect implementation and operating policy but do not leave
the canonical wire format, schema authority, naming, identity, timestamp,
versioning, error, or compatibility model undecided.

## Explicitly Out of Scope

This ADR does not decide:

- the concrete API framework;
- the Event Bus implementation;
- Kafka topics, queues, or broker bindings;
- persistence technology or workflow table design;
- authentication provider or authorization model;
- secrets manager;
- AI provider or AI Router design;
- LangGraph or another orchestration framework;
- deployment topology;
- monitoring backend;
- deployed schema-registry infrastructure; or
- application-level retry, cancellation, or additional workflow messages.

## Acceptance Checklist

- [ ] JSON and UTF-8 are approved as the baseline wire representation.
- [ ] JSON Schema Draft 2020-12 is approved as the canonical data-schema source.
- [ ] OpenAPI 3.1.1 and AsyncAPI 3.0.0 responsibilities and authority
      boundaries are approved.
- [ ] The `ExecuteTask` naming proposal is reconciled with Vertical Slice 01.
- [ ] Commands, events, responses, and internal models remain semantically
      distinct.
- [ ] `snake_case`, path, header, contract, enum, error, and filename
      conventions are approved.
- [ ] The common envelope, `created_at` decision, and transport-metadata
      boundary are approved.
- [ ] UUIDv7 ownership, encoding, and clock-risk rules are approved.
- [ ] RFC 3339 UTC timestamp format and semantic timestamp distinctions are
      approved.
- [ ] URL major API versioning and the limited Workflow API paths are approved.
- [ ] RFC 9457 problem details and stable initial errors are approved.
- [ ] `MAJOR.MINOR` versions, deprecation, and multiple-version support are
      approved.
- [ ] The compatibility matrix and unknown-field policy are approved.
- [ ] API, Agent, and message idempotency remain distinct and testable.
- [ ] Correlation and message-only causation semantics are approved.
- [ ] Canonical schema and breaking-change ownership are assigned.
- [ ] Runtime validation is required independently of Python static typing.
- [ ] Source and committed generated OpenAPI and AsyncAPI artifacts are
      approved.
- [ ] The proposed repository structure separates schemas, generated
      documentation, Python models, examples, and test fixtures.
- [ ] Illustrative examples and repository-owned contract tests are required.
- [ ] Security, data-minimization, redaction, and bounded-input rules align with
      `SECURITY.md`.
- [ ] Every open question has an owner or is accepted as a bounded
      implementation-policy item.
- [ ] Reviewers confirm consistency with ADR-0001 through ADR-0003, the test
      strategy, and Vertical Slice 01 after the documented conflicts are
      resolved.
- [ ] No out-of-scope infrastructure or implementation technology is selected.

## Related Decisions

- [ADR-0001: Core Design Principles](ADR-0001-core-design-principles.md)
- [ADR-0002: Platform Communication and State](ADR-0002-platform-communication-and-state.md)
- [ADR-0003: Runtime and Development Tooling](ADR-0003-runtime-and-development-tooling.md)

## References

- [Platform Architecture](../README.md)
- [Vertical Slice 01](../../implementation/vertical-slice-01.md)
- [Platform test strategy](../../testing/README.md)
- [Repository security policy](../../../SECURITY.md)
- [Repository agent guidance](../../../AGENTS.md)
- [JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12)
- [OpenAPI Specification 3.1.1](https://spec.openapis.org/oas/v3.1.1.html)
- [AsyncAPI Specification 3.0.0](https://www.asyncapi.com/docs/reference/specification/v3.0.0)
- [RFC 8259: JSON](https://www.rfc-editor.org/rfc/rfc8259.html)
- [RFC 8785: JSON Canonicalization Scheme](https://www.rfc-editor.org/rfc/rfc8785.html)
- [RFC 9457: Problem Details for HTTP APIs](https://www.rfc-editor.org/rfc/rfc9457.html)
- [RFC 9562: UUIDs](https://www.rfc-editor.org/rfc/rfc9562.html)
- [RFC 3339: Internet Timestamps](https://www.rfc-editor.org/rfc/rfc3339.html)
- [RFC 6648: Deprecating the `X-` Prefix](https://www.rfc-editor.org/rfc/rfc6648.html)
- [Python 3.14 UUID support](https://docs.python.org/3.14/library/uuid.html)
- [Protocol Buffers language guide](https://protobuf.dev/programming-guides/proto3/)
