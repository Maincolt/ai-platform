"""Test Agent module (Phase 4 of Vertical Slice 01).

The built-in text.word-count capability, its bounded receipt-first
idempotency lifecycle, capability/input validation, and outcome/event/
outbox persistence, per docs/implementation/vertical-slice-01.md Section
14 and ADR-0007. Composed only over the Phase 2 Agent-side persistence
ports -- no Event Bus consumer, no concrete adapter (Phase 6).
"""
