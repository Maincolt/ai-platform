"""Workflow API module (Phase 5 of Vertical Slice 01).

Submit/read/health operations, trusted synthetic request context (ADR-0010
Section "Local-Development API Boundary"), ADR-0012 correlation
normalization, RFC 8785 request fingerprinting, and stable Problem Details
error responses. Composed over Sprint 3's SubmissionOrchestrator/
TerminalEventProcessor using in-memory port implementations assembled at
app startup -- no real database/Kafka adapters (Phase 6).
"""
