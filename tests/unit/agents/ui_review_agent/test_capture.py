"""Tests for the Playwright-backed `PageCapturePort` implementation
(ADR-0019 Implementation Status, Phase 2).

`_origin`/`_truncate` are pure helpers, tested directly without a browser.
`PlaywrightPageCapture.capture()` itself needs a real Chromium (installed
via `uv run playwright install chromium`) and is kept out of the default
fast unit suite behind the `browser` marker (`pyproject.toml`, same opt-in
spirit as `external_service`) -- it launches a real, if headless, browser
process per test and is meaningfully slower than the rest of this suite.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

import pytest

from ai_platform.agents.ui_review_agent.capture import (
    PlaywrightPageCapture,
    _origin,  # pyright: ignore[reportPrivateUsage]
    _truncate,  # pyright: ignore[reportPrivateUsage]
)
from ai_platform.agents.ui_review_agent.errors import CaptureFailedError


def _run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


def test_origin_ignores_path_and_query() -> None:
    assert _origin("http://platform:80/some/path?x=1") == _origin("http://platform:80/")


def test_origin_distinguishes_scheme_and_host() -> None:
    assert _origin("http://platform:80/") != _origin("https://platform:80/")
    assert _origin("http://platform:80/") != _origin("http://evil.example.com/")


def test_truncate_leaves_short_text_unchanged() -> None:
    assert _truncate("short", 100) == "short"


def test_truncate_bounds_long_text() -> None:
    assert _truncate("x" * 200, 100) == "x" * 100


def test_navigation_timeout_seconds_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        PlaywrightPageCapture(navigation_timeout_seconds=0)


_FIXTURE_HTML = """<!DOCTYPE html>
<html>
<head><title>Fixture Page</title></head>
<body>
<h1>Hello from the fixture</h1>
<script>console.error("a deliberate console error");</script>
</body>
</html>
"""

_REDIRECT_FIXTURE_HTML = """<!DOCTYPE html>
<html>
<head><meta http-equiv="refresh" content="0; url=https://example.invalid/"></head>
<body>redirecting...</body>
</html>
"""


@pytest.mark.browser
def test_capture_returns_bounded_signals_from_a_real_page(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture.html"
    fixture.write_text(_FIXTURE_HTML, encoding="utf-8")
    url = fixture.as_uri()

    capture = _run(PlaywrightPageCapture().capture(url))

    assert capture.title == "Fixture Page"
    assert "Hello from the fixture" in capture.visible_text
    assert any(
        message.level == "error" and "deliberate console error" in message.text
        for message in capture.console_messages
    )
    assert capture.accessibility_snapshot != ""


@pytest.mark.browser
def test_capture_rejects_navigation_that_redirects_off_origin(tmp_path: Path) -> None:
    fixture = tmp_path / "redirect.html"
    fixture.write_text(_REDIRECT_FIXTURE_HTML, encoding="utf-8")
    url = fixture.as_uri()

    with pytest.raises(CaptureFailedError):
        _run(PlaywrightPageCapture().capture(url))


@pytest.mark.browser
def test_capture_rejects_a_nonexistent_target() -> None:
    with pytest.raises(CaptureFailedError):
        _run(PlaywrightPageCapture(navigation_timeout_seconds=2).capture("http://127.0.0.1:1/"))
