"""External-service crash-window recovery tests against the real containers.

Section 19's "Recovery/crash window" category requires "every row in Section
15 with deterministic fault injection and process/container restart." This
module automates the two highest-value process-level scenarios first proven
by hand in Sprint 6 (see docs/sprint-6/progress.md for the original manual
account with raw command/output evidence):

- Test Agent killed (SIGKILL) before it can commit a Kafka offset: proves
  uncommitted work is redelivered and completed on restart, with no
  duplicate receipt/outcome.
- Platform killed (SIGKILL) immediately after dispatch: the Agent keeps
  working and publishes its outcome independently. Recovery involves
  recreating the `test-agent` container (see below), which is slow enough
  that whether the platform consumes the backlogged outcome before
  `task_result_deadline` or the deadline reconciler wins first is a genuine
  race, not a fixed outcome -- this was first observed by hand in Sprint 6.
  Rather than pin down one side of that race, the test asserts the
  invariant that holds on *either* side: a deterministic terminal state,
  exactly one Agent outcome (no duplicate processing), and -- if the
  deadline wins -- the late outcome is safely recorded as
  `late_after_terminal` rather than corrupting the terminal state.

These tests drive the real `platform`/`test-agent` application containers
(image `ai-platform:sprint6`), not just the database/broker adapters. That
means they operate entirely through `podman` subprocess calls rather than
direct HTTP/DSN connections to host-published ports:

- The platform's HTTP API binds to `127.0.0.1` inside its own container
  only (an intentional, validated security property -- see
  `src/ai_platform/runtime/configuration.py`'s loopback enforcement), so it
  is reached via `podman exec ... python3 -c "..."`, exactly as Sprint 6's
  manual validation did.
- On this host, direct PostgreSQL connections from Windows-native Python to
  the published `localhost:5433` port are unreliable (TCP connects, but the
  protocol handshake can hang -- see `tests/integration/README.md`), so
  durable-state assertions use `podman exec` into the PostgreSQL container
  with `psql` rather than `psycopg` over the host-forwarded port.

Because these tests kill and restart the shared `platform`/`test-agent`
containers, they must not run concurrently with anything else exercising
that same topology. They restore both containers to a healthy, ready state
before finishing (including the network-namespace recreation `test-agent`
needs whenever `platform` itself is restarted -- see
`infrastructure/README.md`'s "Running the application against the
topology" section).
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import time
import uuid
from collections.abc import Iterator
from typing import cast

import pytest

pytestmark = pytest.mark.external_service


@pytest.fixture(scope="session", autouse=True)
def _skip_if_external_services_unavailable() -> None:  # pyright: ignore[reportUnusedFunction]
    """Override conftest.py's same-named autouse fixture for this module only.

    That fixture pre-checks direct psycopg/confluent_kafka connections to the
    host-published ports, which this module never uses (it drives everything
    through `podman exec`, for the reasons in this module's docstring). Using
    it here would make every test in this file skip on hosts where the
    direct host-port path is flaky even though podman itself works fine.
    `_ensure_app_containers_running` below is this module's own, more
    relevant readiness check.
    """


_COMPOSE_DIR = "infrastructure/compose"
_PLATFORM_CONTAINER = "ai-platform-local-platform-1"
_TEST_AGENT_CONTAINER = "ai-platform-local-test-agent-1"
_POSTGRES_CONTAINER = "ai-platform-local-postgres-1"

_READY_TIMEOUT_SECONDS = 60.0
_POLL_INTERVAL_SECONDS = 1.0


def _run(
    args: list[str], *, timeout: float = 30.0, check: bool = True, cwd: str | None = None
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args, capture_output=True, text=True, timeout=timeout, check=False, cwd=cwd
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(args)}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result


def _podman_exec_python(container: str, script: str, *, timeout: float = 15.0) -> str:
    result = _run(["podman", "exec", container, "python3", "-c", script], timeout=timeout)
    return result.stdout


def _new_uuid7() -> str:
    return str(uuid.uuid7())


def _submit_workflow(text: str) -> tuple[str, str]:
    """Submit through the real platform API (via podman exec) and return
    (workflow_id, request_id)."""
    script = f"""
import urllib.request, json
body = json.dumps({{
    'request_id': '{_new_uuid7()}',
    'text': {text!r},
    'capability': 'text.word-count',
    'capability_version': '1.0',
}}).encode()
req = urllib.request.Request(
    'http://127.0.0.1:8000/api/v1/workflows', data=body, method='POST',
    headers={{'Content-Type': 'application/json'}},
)
with urllib.request.urlopen(req, timeout=10) as resp:
    print(resp.status)
    print(resp.read().decode())
"""
    output = _podman_exec_python(_PLATFORM_CONTAINER, script)
    lines = output.strip().splitlines()
    status, body = lines[0], lines[1]
    assert status == "202", f"submission did not dispatch: {status} {body}"
    document = json.loads(body)
    return document["workflow_id"], document["request_id"]


def _get_workflow_state(workflow_id: str) -> dict[str, object]:
    script = f"""
import urllib.request, json
with urllib.request.urlopen(
    'http://127.0.0.1:8000/api/v1/workflows/{workflow_id}', timeout=10
) as resp:
    print(resp.read().decode())
"""
    output = _podman_exec_python(_PLATFORM_CONTAINER, script)
    return json.loads(output.strip())


def _wait_for_platform_ready(deadline: float) -> None:
    while time.monotonic() < deadline:
        try:
            output = _podman_exec_python(
                _PLATFORM_CONTAINER,
                "import urllib.request\n"
                "url = 'http://127.0.0.1:8000/health/ready'\n"
                "with urllib.request.urlopen(url, timeout=3) as r:\n"
                "    print(r.status)",
                timeout=8,
            )
            if output.strip() == "200":
                return
        except Exception:  # noqa: BLE001 - polling
            pass
        time.sleep(_POLL_INTERVAL_SECONDS)
    raise TimeoutError("platform did not become ready in time")


def _wait_for_workflow_state(
    workflow_id: str, expected_states: tuple[str, ...], deadline: float
) -> dict[str, object]:
    last: dict[str, object] = {}
    while time.monotonic() < deadline:
        try:
            last = _get_workflow_state(workflow_id)
            if last.get("state") in expected_states:
                return last
        except Exception:  # noqa: BLE001 - polling, platform may be mid-restart
            pass
        time.sleep(_POLL_INTERVAL_SECONDS)
    raise TimeoutError(
        f"workflow {workflow_id} did not reach {expected_states} in time; last observed: {last}"
    )


def _result_word_count(document: dict[str, object]) -> int:
    result = document.get("result")
    assert isinstance(result, dict), f"expected a result object, got: {document}"
    typed_result = cast(dict[str, object], result)
    word_count = typed_result.get("word_count")
    assert isinstance(word_count, int), f"expected an integer word_count, got: {document}"
    return word_count


def _psql_scalar(query: str) -> str:
    result = _run(
        [
            "podman",
            "exec",
            _POSTGRES_CONTAINER,
            "bash",
            "-c",
            f'PGPASSWORD="$(cat /run/secrets/postgres_admin_password)" '
            f'psql -U postgres -d ai_platform -tA -c "{query}"',
        ],
        timeout=15,
    )
    return result.stdout.strip()


def _podman_available() -> bool:
    try:
        result = subprocess.run(["podman", "version"], capture_output=True, timeout=10, check=False)
    except OSError, subprocess.TimeoutExpired:
        return False
    return result.returncode == 0


@pytest.fixture(scope="module", autouse=True)
def _ensure_app_containers_running() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Confirm the platform/test-agent application containers are present
    and ready before this module's tests run; restore them to a healthy
    state afterward regardless of what individual tests did to them."""
    if not _podman_available():
        pytest.skip(
            "podman is not available in this environment. This module drives real "
            "containers directly (kill/restart/exec) and cannot run inside the "
            "container-network sandbox used by tests/integration/run-in-network.sh -- "
            "run it directly on a host with the podman CLI instead."
        )
    inspect = _run(
        ["podman", "inspect", _PLATFORM_CONTAINER, "--format", "{{.State.Status}}"],
        check=False,
    )
    if inspect.returncode != 0 or inspect.stdout.strip() != "running":
        pytest.skip(
            f"{_PLATFORM_CONTAINER} is not running. Bring the application containers "
            "up first: 'podman compose --profile app up -d platform test-agent' from "
            f"{_COMPOSE_DIR}/ (see infrastructure/README.md)."
        )
    _wait_for_platform_ready(time.monotonic() + _READY_TIMEOUT_SECONDS)
    yield
    # Best-effort: leave both containers running and ready for whatever runs next.
    _run(["podman", "start", _PLATFORM_CONTAINER], check=False)
    inspect = _run(
        ["podman", "inspect", _TEST_AGENT_CONTAINER, "--format", "{{.State.Status}}"],
        check=False,
    )
    if inspect.returncode != 0 or inspect.stdout.strip() != "running":
        _run(["podman", "rm", "-f", _TEST_AGENT_CONTAINER], check=False)
        _run(
            ["podman", "compose", "--profile", "app", "up", "-d", "test-agent"],
            cwd=_COMPOSE_DIR,
            check=False,
        )
    with contextlib.suppress(TimeoutError):
        _wait_for_platform_ready(time.monotonic() + _READY_TIMEOUT_SECONDS)


def test_agent_killed_mid_flight_recovers_via_redelivery_with_no_duplicate() -> None:
    """SIGKILL the Test Agent before it can process a dispatched command;
    restarting it must redeliver the uncommitted message and complete the
    workflow exactly once."""
    workflow_id, _ = _submit_workflow("agent crash recovery test seven words")

    # Race the kill against the Agent's own processing -- see
    # docs/sprint-6/progress.md for why this reliably lands before commit in
    # practice (poll/idle delays give a real, if narrow, window).
    _run(["podman", "kill", _TEST_AGENT_CONTAINER], check=False)

    state = _get_workflow_state(workflow_id)
    assert state["state"] == "DISPATCHED", (
        "expected the workflow to still be DISPATCHED immediately after killing "
        f"the Agent; got {state}"
    )

    _run(["podman", "start", _TEST_AGENT_CONTAINER])

    final = _wait_for_workflow_state(workflow_id, ("COMPLETED", "FAILED"), time.monotonic() + 45.0)
    assert final["state"] == "COMPLETED", f"workflow did not recover cleanly: {final}"
    assert _result_word_count(final) == 6

    task_attempt_id = _psql_scalar(
        "SELECT task_attempt_id FROM orchestrator.task_attempts WHERE task_id = "
        f"(SELECT task_id FROM orchestrator.tasks WHERE workflow_id = '{workflow_id}')"
    )
    receipt_count = _psql_scalar(
        f"SELECT count(*) FROM agent.completed_receipts WHERE task_attempt_id = '{task_attempt_id}'"
    )
    outcome_count = _psql_scalar(
        f"SELECT count(*) FROM agent.outcomes WHERE task_attempt_id = '{task_attempt_id}'"
    )
    assert receipt_count == "1", "redelivery must not create a duplicate receipt"
    assert outcome_count == "1", "redelivery must not create a duplicate outcome"


def test_platform_killed_after_dispatch_recovers_the_backlogged_outcome() -> None:
    """SIGKILL the platform immediately after dispatch. The Agent completes
    independently while the platform is down and publishes its outcome; the
    container-recreation dance required to bring the platform back (see the
    module docstring) is slow enough that which of two *equally correct*
    outcomes actually lands is a real race, not a bug to pin down:

    - the platform recovers before `task_result_deadline` and consumes the
      backlogged outcome normally, reaching COMPLETED; or
    - the deadline reconciler wins first and fails the workflow
      (TASK_RESULT_DEADLINE_EXCEEDED) before the outcome consumer catches up,
      in which case the late-arriving outcome must be safely rejected
      (recorded as `late_after_terminal`, never overwriting the terminal
      state) -- this exact race was first proven safe by hand in Sprint 6
      (see docs/sprint-6/progress.md).

    Either way, the invariant this test actually asserts is: the workflow
    reaches a deterministic terminal state, the Agent's outcome is never
    duplicated, and a late outcome never corrupts an already-terminal
    workflow.
    """
    workflow_id, _ = _submit_workflow("platform crash recovery test with six")

    _run(["podman", "kill", _PLATFORM_CONTAINER], check=False)

    # Give the still-running Agent a moment to finish and publish its
    # outcome while the platform is down -- this is the scenario, not an
    # incidental delay.
    time.sleep(3.0)

    # Restarting the SAME platform container object breaks test-agent's
    # network_mode: "service:platform" reference (its network namespace is
    # tied to the platform container's specific instantiation, not "whichever
    # container is currently named platform" -- see infrastructure/README.md).
    # test-agent must be recreated, not just restarted, every time platform is.
    _run(["podman", "start", _PLATFORM_CONTAINER])
    _run(["podman", "rm", "-f", _TEST_AGENT_CONTAINER], check=False)
    _run(
        ["podman", "compose", "--profile", "app", "up", "-d", "test-agent"],
        cwd=_COMPOSE_DIR,
    )
    _wait_for_platform_ready(time.monotonic() + _READY_TIMEOUT_SECONDS)

    final = _wait_for_workflow_state(workflow_id, ("COMPLETED", "FAILED"), time.monotonic() + 90.0)

    if final["state"] == "COMPLETED":
        assert _result_word_count(final) == 6
    else:
        failure = final.get("failure")
        assert isinstance(failure, dict), f"FAILED workflow missing failure detail: {final}"
        typed_failure = cast(dict[str, object], failure)
        assert typed_failure.get("code") == "TASK_RESULT_DEADLINE_EXCEEDED", (
            f"unexpected failure reason: {final}"
        )

    # Regardless of which side of the race won, the Agent must eventually
    # produce exactly one outcome for this workflow's task attempt -- no
    # duplicate processing. When the deadline wins, the orchestrator's own
    # terminal transition can land before the (re-created) Agent finishes
    # working through its backlog and records its own outcome, so this polls
    # rather than checking once immediately.
    outcome_query = (
        "SELECT count(*) FROM agent.outcomes o "
        "JOIN orchestrator.task_attempts ta ON ta.task_attempt_id = o.task_attempt_id "
        "JOIN orchestrator.tasks t ON t.task_id = ta.task_id "
        f"WHERE t.workflow_id = '{workflow_id}'"
    )
    outcome_count = "0"
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        outcome_count = _psql_scalar(outcome_query)
        if outcome_count != "0":
            break
        time.sleep(_POLL_INTERVAL_SECONDS)
    assert outcome_count == "1", (
        f"expected exactly one Agent outcome for this workflow, got {outcome_count}"
    )

    if final["state"] == "FAILED":
        inbox_disposition = _psql_scalar(
            "SELECT disposition FROM orchestrator.inbox WHERE workflow_id = "
            f"'{workflow_id}' ORDER BY recorded_at DESC LIMIT 1"
        )
        assert inbox_disposition == "late_after_terminal", (
            "a terminal-then-late outcome must be recorded as late_after_terminal, "
            f"got: {inbox_disposition!r}"
        )
