"""Product Owner Agent module (ADR-0026, ADR-0030).

ADR-0026 Phase 3: the platform's second `PeriodicService`-driven,
non-Workflow-driven Agent (after `scrum_master_agent`, ADR-0028). Wakes up
hourly, fetches the same live GitHub Projects v2 board `scrum_status_agent`
(ADR-0027) reads and `scrum_master_agent` also writes to, and -- bounded
by a fixed six-action allowlist (create/edit/close tickets, archive a
draft ticket, reprioritize the backlog, adjust sprint scope), a daily
action/spend cap, the same
platform-wide kill switch, and a durable audit trail -- takes real,
autonomous backlog/sprint-scope write actions with no per-action human
approval, per the same narrow `SECURITY.md` exception ADR-0026
established.
"""
