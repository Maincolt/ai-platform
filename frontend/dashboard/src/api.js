const CORRELATION_HEADER = "Correlation-Id";

/**
 * Fetch every declared Agent binding and its current readiness observation
 * from GET /api/v1/agents. Throws on a non-2xx response or network failure;
 * the caller decides how to degrade (e.g. keep showing the last good list).
 */
export async function fetchAgents() {
  const response = await fetch("/api/v1/agents", {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`GET /api/v1/agents failed: HTTP ${response.status}`);
  }
  const body = await response.json();
  return {
    agents: body.agents,
    correlationId: response.headers.get(CORRELATION_HEADER),
  };
}

/**
 * Submit one workflow (POST /api/v1/workflows). `request_id` is
 * deliberately omitted -- WorkflowSubmitRequest.request_id is optional
 * (src/ai_platform/api/models.py), so the platform generates one itself
 * rather than the browser needing its own UUIDv7 generator.
 */
export async function submitWorkflow(text, capability) {
  const response = await fetch("/api/v1/workflows", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ text, capability, capability_version: "1.0" }),
  });
  const body = await response.json();
  if (!response.ok) {
    throw new Error(body.detail ?? `POST /api/v1/workflows failed: HTTP ${response.status}`);
  }
  return body;
}

/** Read one workflow's current state (GET /api/v1/workflows/{id}). */
export async function fetchWorkflow(workflowId) {
  const response = await fetch(`/api/v1/workflows/${workflowId}`, {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`GET /api/v1/workflows/${workflowId} failed: HTTP ${response.status}`);
  }
  return response.json();
}

/**
 * Poll a workflow until it reaches COMPLETED/FAILED, or give up after
 * `maxAttempts`. Mirrors submit-assignment.py's `_poll_to_terminal`.
 */
export async function pollWorkflowToTerminal(
  workflowId,
  { intervalMs = 1500, maxAttempts = 30 } = {},
) {
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const workflow = await fetchWorkflow(workflowId);
    if (workflow.state === "COMPLETED" || workflow.state === "FAILED") {
      return workflow;
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  throw new Error(`workflow ${workflowId} did not reach a terminal state in time`);
}
