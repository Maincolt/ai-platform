"""The deterministic, read-only page-capture boundary (ADR-0019 Decision 1).

`PageCapturePort` is a narrow seam between `agent.py`'s orchestration and
whatever actually drives a browser, the same testability principle
`AIRouterPort` already gives `agent.py` for the provider call: `agent.py`
and its unit/component tests depend only on this Protocol, never on a real
browser. The real Playwright-backed implementation
(`PlaywrightPageCapture`) is a separate, later addition -- see ADR-0019's
Implementation Status -- so this module can be built, wired, and tested
end-to-end against a fake before any Chromium dependency exists.

Every method here is read-only by construction: the Protocol has no
operation that clicks, fills, or submits anything. `capture()` takes the
already-validated target URL (validation happens in `agent.py`, against
the hardcoded allowed target -- ADR-0019 Decision 4) and either returns a
`PageCapture` or raises `CaptureFailedError`, including when navigation
lands somewhere other than the requested URL (a redirect off the allowed
host is a capture failure, not a silent follow).
"""

from dataclasses import dataclass
from typing import Protocol

_MAX_CONSOLE_MESSAGES = 200
_MAX_VISIBLE_TEXT_LENGTH = 5000


@dataclass(frozen=True, slots=True)
class ConsoleMessage:
    level: str
    """Browser console severity, e.g. "error", "warning", "log"."""
    text: str


@dataclass(frozen=True, slots=True)
class PageCapture:
    """The bounded set of signals captured from one page load.

    Bounds (`_MAX_CONSOLE_MESSAGES`/`_MAX_VISIBLE_TEXT_LENGTH`) are enforced
    by whatever builds this dataclass (`PageCapturePort.capture()`
    implementations), not by the dataclass itself -- a fake test double is
    free to construct a `PageCapture` directly without re-deriving them.
    """

    url: str
    http_status: int | None
    title: str
    visible_text: str
    console_messages: tuple[ConsoleMessage, ...]
    accessibility_snapshot: str


class PageCapturePort(Protocol):
    async def capture(self, url: str) -> PageCapture:
        """Navigate to `url` and return what was observed.

        `url` has already been validated against the hardcoded allowed
        review target by the caller (`agent.py`) -- this method's own
        responsibility is only the capture itself, not target validation.
        Raises `CaptureFailedError` on navigation failure, timeout, or a
        redirect landing outside the allowed host.
        """
        ...
