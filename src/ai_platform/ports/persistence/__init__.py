"""Persistence ports (Phase 2 of Vertical Slice 01).

Capability-oriented `Protocol` interfaces per ADR-0006 Section 4. Domain
modules depend on these, never on SQL, connections, ORM sessions, or
database-specific exceptions. No concrete adapter exists until Phase 6.
"""
