"""Agent-side domain model, shared across Agent deployments (ADR-0007).

Separate from ai_platform.orchestrator.domain: Agents and the Orchestrator
are independent deployables (ADR-0001, ADR-0007 Section 1) that
collaborate only through the Event Bus and portable contracts, never by
importing each other's internal modules.
"""
