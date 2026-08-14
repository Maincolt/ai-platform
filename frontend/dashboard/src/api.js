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
