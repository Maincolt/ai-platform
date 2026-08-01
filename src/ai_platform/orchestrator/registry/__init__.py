"""Capability Registry module (ADR-0008; vertical-slice-01.md Section 7).

The Orchestrator-owned logical source that determines which logical Agent
deployments are declared, compatible, permitted, and sufficiently available
candidates for a requested capability. This package is pure Python domain
code: it accepts already-parsed declarations and a technology-neutral
readiness `Protocol`, performs complete validation and conflict rejection,
and selects exactly one eligible candidate. No I/O, no persistence, no
transport, and no configuration-file parsing live here (ADR-0008 Sections
1-2, 7).
"""
