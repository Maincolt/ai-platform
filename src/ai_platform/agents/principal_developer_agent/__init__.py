"""Principal Developer Agent module (ADR-0026, ADR-0031).

ADR-0026 Phase 4, the last phase ADR-0026 itself authorizes: the
platform's third `PeriodicService`-driven, non-Workflow-driven Agent
(after `scrum_master_agent` and `product_owner_agent`). Wakes up hourly,
fetches the repository's open pull requests, and -- bounded by a fixed
two-action allowlist (`request_changes`, `merge`), a daily action/spend
cap, the same platform-wide kill switch, and a durable audit trail --
takes real, autonomous PR-review and merge actions with no per-action
human approval, per the same narrow `SECURITY.md` exception ADR-0026
established. `merge` is additionally gated on GitHub's own computed
`mergeable_state == "clean"`, re-checked immediately before the merge
call itself (ADR-0031 Decision 1) to close the gap between "looked
mergeable when the cycle started" and "is it still mergeable now."

Per ADR-0031 Decision 5, this role is deployed with a placeholder
credential only -- no real PAT, no real merge -- until an explicit,
separate go-ahead from the repository owner.
"""
