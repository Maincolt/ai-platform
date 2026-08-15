#!/usr/bin/env python3
"""Submit a free-text assignment and let the team route it (ADR-0023).

This is the caller-side dispatch script ADR-0023 Decision 5 describes: it
performs the "agents work together as a team" fan-out entirely outside the
platform's own architecture, by making ordinary Workflow API calls a human
operator could make by hand -- nothing here is privileged or new.

Sequence:
  1. Submit the assignment text to `assignment.route` and poll it to a
     terminal state.
  2. Read the recommended `{capability, rationale}` list from its result.
  3. Submit the *same* assignment text as one independent workflow per
     recommended capability.
  4. Poll every one of those workflows to a terminal state.
  5. Print a combined report: the routing decision, then each recommended
     capability's own result side by side.

Run from inside the `platform` container, the same way every other manual
verification script in this repository is run (the Workflow API binds to
loopback only, by design -- see docs/operations/README.md Section 8):

    docker cp submit-assignment.py ai-platform-local-platform-1:/tmp/submit-assignment.py
    docker exec ai-platform-local-platform-1 python3 /tmp/submit-assignment.py "<assignment text>"

Or pipe text on stdin:

    echo "<assignment text>" | docker exec -i ai-platform-local-platform-1 \\
        python3 /tmp/submit-assignment.py
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
import uuid

_BASE_URL = "http://127.0.0.1:8000/api/v1/workflows"
_ROUTE_CAPABILITY = "assignment.route"
_CAPABILITY_VERSION = "1.0"
_POLL_INTERVAL_SECONDS = 2.0
_POLL_ATTEMPTS = 30


def _uuid7() -> str:
    b = bytearray(uuid.uuid4().bytes)
    b[6] = (b[6] & 0x0F) | 0x70
    b[8] = (b[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(b)))


def _submit(text: str, capability: str) -> str:
    body = json.dumps(
        {
            "request_id": _uuid7(),
            "text": text,
            "capability": capability,
            "capability_version": _CAPABILITY_VERSION,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        _BASE_URL, data=body, method="POST", headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        submitted = json.loads(response.read().decode("utf-8"))
    workflow_id = submitted["workflow_id"]
    assert isinstance(workflow_id, str)
    return workflow_id


def _poll_to_terminal(workflow_id: str) -> dict[str, object]:
    for _ in range(_POLL_ATTEMPTS):
        with urllib.request.urlopen(f"{_BASE_URL}/{workflow_id}", timeout=10) as response:
            workflow = json.loads(response.read().decode("utf-8"))
        if workflow["state"] in ("COMPLETED", "FAILED"):
            return workflow
        time.sleep(_POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"workflow {workflow_id} did not reach a terminal state in time")


def dispatch_assignment(text: str) -> dict[str, object]:
    """Route `text` through the team, then submit it to every recommended
    capability. Returns a combined report; never raises for an individual
    downstream capability's own failure -- that failure is just part of
    the report, same as any other workflow outcome."""
    route_workflow_id = _submit(text, _ROUTE_CAPABILITY)
    route_result = _poll_to_terminal(route_workflow_id)

    if route_result["state"] != "COMPLETED":
        return {"routing": route_result, "assignments": []}

    result = route_result.get("result")
    assert isinstance(result, dict)
    recommendations = result.get("assignments", [])
    assert isinstance(recommendations, list)

    dispatched: list[dict[str, object]] = []
    for recommendation in recommendations:
        assert isinstance(recommendation, dict)
        capability = recommendation["capability"]
        assert isinstance(capability, str)
        workflow_id = _submit(text, capability)
        dispatched.append(
            {
                "capability": capability,
                "rationale": recommendation["rationale"],
                "workflow_id": workflow_id,
            }
        )

    completed: list[dict[str, object]] = []
    for entry in dispatched:
        workflow_id = entry["workflow_id"]
        assert isinstance(workflow_id, str)
        outcome = _poll_to_terminal(workflow_id)
        completed.append({**entry, "outcome": outcome})

    return {"routing": route_result, "assignments": completed}


def _print_report(report: dict[str, object]) -> None:
    routing = report["routing"]
    assert isinstance(routing, dict)
    print(f"Routing decision: {routing['state']}")
    if routing["state"] != "COMPLETED":
        print(json.dumps(routing, indent=2))
        return

    assignments = report["assignments"]
    assert isinstance(assignments, list)
    if not assignments:
        print("No capability was recommended for this assignment.")
        return

    for entry in assignments:
        assert isinstance(entry, dict)
        print(f"\n=== {entry['capability']} ===")
        print(f"Why: {entry['rationale']}")
        outcome = entry["outcome"]
        assert isinstance(outcome, dict)
        print(f"Outcome: {outcome['state']}")
        print(json.dumps(outcome.get("result") or outcome.get("failure_code"), indent=2))


def main() -> None:
    text = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else sys.stdin.read()
    if not text.strip():
        print('usage: submit-assignment.py "<assignment text>" (or pipe text on stdin)')
        sys.exit(2)

    report = dispatch_assignment(text)
    _print_report(report)


if __name__ == "__main__":
    main()
