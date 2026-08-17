"""Domain Review Agent module (ADR-0026, ADR-0033).

A single shared implementation backing two autonomous role deployments:
`frontend-specialist-agent` and `postgres-specialist-agent`. Unlike every
prior pair of autonomous roles, these two are structurally identical --
same one action (`request_changes`), same dispatch logic -- differing
only in role name, prompt wording, and which file paths define "their"
pull requests, all supplied as constructor parameters to
`DomainReviewAgent` by each role's own `build_*_process()` composition
function.

Wakes up hourly (`PeriodicService`), fetches the configured repository's
open pull requests, filters to only those touching its own domain's file
paths, and -- bounded by a one-action allowlist, a daily action/spend
cap, the same platform-wide kill switch every role shares, and a durable
audit trail -- requests changes on qualifying pull requests with no
per-action human approval, per the narrow `SECURITY.md` exception
ADR-0033 established. Structurally incapable of merging or writing
anything else: `PullRequestReviewPort` has no such method at all.
"""
