"""The deterministic, read-only page-capture boundary (ADR-0019 Decision 1).

`PageCapturePort` is a narrow seam between `agent.py`'s orchestration and
whatever actually drives a browser, the same testability principle
`AIRouterPort` already gives `agent.py` for the provider call: `agent.py`
and its unit/component tests depend only on this Protocol, never on a real
browser -- `PlaywrightPageCapture` below is the only piece of this module
that actually launches Chromium.

Every method here is read-only by construction: the Protocol has no
operation that clicks, fills, or submits anything. `capture()` takes the
already-validated target URL (validation happens in `agent.py`, against
the hardcoded allowed target -- ADR-0019 Decision 4) and either returns a
`PageCapture` or raises `CaptureFailedError`, including when navigation
lands somewhere other than the requested URL (a redirect off the allowed
host is a capture failure, not a silent follow -- see
`PlaywrightPageCapture.capture`'s origin re-check).
"""

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from playwright.async_api import ConsoleMessage as PlaywrightConsoleMessage
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from ai_platform.agents.ui_review_agent.errors import CaptureFailedError

_MAX_CONSOLE_MESSAGES = 200
_MAX_VISIBLE_TEXT_LENGTH = 5000
_DEFAULT_NAVIGATION_TIMEOUT_SECONDS = 10.0


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


_DEFAULT_PORTS = {"http": 80, "https": 443}


def _origin(url: str) -> tuple[str, str, int | None]:
    """A scheme/host/port tuple with default ports normalized away, so
    `http://platform:80` and `http://platform` (the shape a browser's own
    landed `response.url` uses once it drops an explicit default port)
    compare equal -- an unnormalized comparison would treat every
    default-port navigation as if it had redirected off-origin."""
    parts = urlsplit(url)
    port = parts.port if parts.port is not None else _DEFAULT_PORTS.get(parts.scheme)
    return (parts.scheme, parts.hostname or "", port)


def _truncate(text: str, maximum_length: int) -> str:
    return text if len(text) <= maximum_length else text[:maximum_length]


class PlaywrightPageCapture:
    """The real, headless-Chromium-backed `PageCapturePort` implementation.

    Launches a fresh browser per call (no persistent browser/context reuse
    across submissions) -- this capability is not high-throughput, and a
    fresh browser per call means one submission's console/page state can
    never leak into another's. Only `page.goto()` is ever called; nothing
    here clicks, fills, or submits anything (ADR-0019 Decision 1).

    Re-validates the *landed* URL's origin against the requested URL's
    origin after navigation completes (`response.url`, which reflects the
    final address after any redirects Playwright followed) -- a redirect
    off the allowed origin is treated as a capture failure, never a silent
    follow (ADR-0019 Decision 4), even though the caller already validated
    the *requested* URL before calling this method.
    """

    def __init__(
        self, *, navigation_timeout_seconds: float = _DEFAULT_NAVIGATION_TIMEOUT_SECONDS
    ) -> None:
        if navigation_timeout_seconds <= 0:
            raise ValueError("navigation_timeout_seconds must be positive")
        self._navigation_timeout_seconds = navigation_timeout_seconds

    async def capture(self, url: str) -> PageCapture:
        requested_origin = _origin(url)
        console_messages: list[ConsoleMessage] = []

        def _on_console(message: PlaywrightConsoleMessage) -> None:
            if len(console_messages) < _MAX_CONSOLE_MESSAGES:
                console_messages.append(ConsoleMessage(level=message.type, text=message.text))

        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=True)
                try:
                    page = await browser.new_page()
                    page.on("console", _on_console)
                    response = await page.goto(
                        url,
                        timeout=self._navigation_timeout_seconds * 1000,
                        wait_until="load",
                    )
                    if response is None:
                        raise CaptureFailedError(f"navigation to {url!r} produced no response")
                    if _origin(response.url) != requested_origin:
                        raise CaptureFailedError(
                            f"navigation redirected outside the allowed origin: {response.url!r}"
                        )
                    title = await page.title()
                    visible_text = await page.evaluate(
                        "() => document.body ? document.body.innerText : ''"
                    )
                    accessibility_snapshot = await page.locator("body").aria_snapshot()
                    return PageCapture(
                        url=response.url,
                        http_status=response.status,
                        title=title,
                        visible_text=_truncate(str(visible_text or ""), _MAX_VISIBLE_TEXT_LENGTH),
                        console_messages=tuple(console_messages),
                        accessibility_snapshot=accessibility_snapshot or "",
                    )
                finally:
                    await browser.close()
        except CaptureFailedError:
            raise
        except PlaywrightTimeoutError as error:
            raise CaptureFailedError(f"navigation timed out: {error}") from error
        except PlaywrightError as error:
            raise CaptureFailedError(str(error)) from error
