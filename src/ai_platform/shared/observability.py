"""Backend-neutral, no-op-capable operational signal boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Protocol


@dataclass(frozen=True, slots=True)
class MetricSignal:
    """One metric update with bounded, low-cardinality labels only."""

    name: str
    value: float
    labels: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class TraceSignal:
    """One backend-neutral span outcome; trace context is transport metadata."""

    operation: str
    duration: timedelta
    outcome: str
    links: tuple[str, ...] = ()


class OperationalSignalsPort(Protocol):
    """Lossy operational signals that never control business correctness."""

    def metric(self, signal: MetricSignal) -> None: ...

    def trace(self, signal: TraceSignal) -> None: ...


@dataclass(slots=True)
class NoOpOperationalSignals:
    """Default when no local exporter or test recorder is configured."""

    def metric(self, signal: MetricSignal) -> None:
        del signal

    def trace(self, signal: TraceSignal) -> None:
        del signal


@dataclass(slots=True)
class RecordingOperationalSignals:
    """In-process model used to verify signal semantics without a backend."""

    metrics: list[MetricSignal] = field(default_factory=list[MetricSignal])
    traces: list[TraceSignal] = field(default_factory=list[TraceSignal])

    def metric(self, signal: MetricSignal) -> None:
        self.metrics.append(signal)

    def trace(self, signal: TraceSignal) -> None:
        self.traces.append(signal)


__all__ = [
    "MetricSignal",
    "NoOpOperationalSignals",
    "OperationalSignalsPort",
    "RecordingOperationalSignals",
    "TraceSignal",
]
