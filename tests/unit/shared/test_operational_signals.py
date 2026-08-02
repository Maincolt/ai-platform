from __future__ import annotations

import json
import logging
from datetime import timedelta

from ai_platform.shared.logging import JsonLogFormatter, operational_log
from ai_platform.shared.observability import (
    MetricSignal,
    NoOpOperationalSignals,
    RecordingOperationalSignals,
    TraceSignal,
)


def test_json_logging_emits_only_allowlisted_fields() -> None:
    record = logging.LogRecord(
        "ai_platform.runtime",
        logging.INFO,
        __file__,
        1,
        "workflow accepted",
        (),
        None,
    )
    record.workflow_id = "workflow-safe"  # type: ignore[attr-defined]
    record.password = "must-not-appear"  # type: ignore[attr-defined]

    document = json.loads(JsonLogFormatter().format(record))

    assert document["workflow_id"] == "workflow-safe"
    assert "password" not in document
    assert "must-not-appear" not in json.dumps(document)


def test_operational_log_drops_unknown_extra_fields() -> None:
    logger = logging.getLogger("ai_platform.test.safe-extra")
    handler = _RecordingHandler()
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False
    try:
        operational_log(
            logger,
            logging.INFO,
            "attempt",
            fields={"reason_code": "SAFE_CODE", "database_dsn": "secret"},
        )
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)

    assert handler.record is not None
    assert handler.record.reason_code == "SAFE_CODE"  # type: ignore[attr-defined]
    assert not hasattr(handler.record, "database_dsn")


def test_noop_and_recording_signal_ports_share_semantics() -> None:
    metric = MetricSignal(name="workflow.accepted", value=1, labels=(("outcome", "new"),))
    trace = TraceSignal(
        operation="workflow.submit",
        duration=timedelta(milliseconds=2),
        outcome="accepted",
        links=("message:known",),
    )

    noop = NoOpOperationalSignals()
    noop.metric(metric)
    noop.trace(trace)

    recorder = RecordingOperationalSignals()
    recorder.metric(metric)
    recorder.trace(trace)
    assert recorder.metrics == [metric]
    assert recorder.traces == [trace]


class _RecordingHandler(logging.Handler):
    record: logging.LogRecord | None = None

    def emit(self, record: logging.LogRecord) -> None:
        self.record = record
