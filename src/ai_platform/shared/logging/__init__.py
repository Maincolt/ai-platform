"""Safe structured operational logging for local runtime processes.

Business audit remains durable persistence.  This module deliberately emits
only nonauthoritative, allowlisted operational fields through Python logging.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Final

_SAFE_EXTRA_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "component",
        "environment",
        "event",
        "operation",
        "outcome",
        "reason_code",
        "request_id",
        "correlation_id",
        "workflow_id",
        "task_id",
        "task_attempt_id",
        "message_id",
        "causation_id",
        "contract_name",
        "contract_version",
        "capability_name",
        "capability_version",
        "retry_classification",
    }
)


class JsonLogFormatter(logging.Formatter):
    """Render one bounded JSON object without serializing arbitrary extras."""

    def format(self, record: logging.LogRecord) -> str:
        document: dict[str, str] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field_name in _SAFE_EXTRA_FIELDS:
            value = getattr(record, field_name, None)
            if isinstance(value, str) and value:
                document[field_name] = value
        return json.dumps(document, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def configure_json_logging(*, level: int = logging.INFO) -> None:
    """Configure JSON-compatible standard output for a runtime process."""

    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def operational_log(
    logger: logging.Logger,
    level: int,
    message: str,
    *,
    fields: Mapping[str, str] | None = None,
) -> None:
    """Emit only explicitly allowlisted safe fields.

    Callers must pass validated/effective identifiers. Unknown keys are
    discarded, preventing accidental payload or credential expansion.
    """

    safe_fields = {
        key: value for key, value in (fields or {}).items() if key in _SAFE_EXTRA_FIELDS and value
    }
    logger.log(level, message, extra=safe_fields)


__all__ = ["JsonLogFormatter", "configure_json_logging", "operational_log"]
