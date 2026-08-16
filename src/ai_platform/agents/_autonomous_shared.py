"""Pure, role-agnostic helpers shared by every ADR-0026 autonomous role's
`agent.py` (`scrum_master_agent`, `product_owner_agent`, and eventually
`principal_developer_agent`).

Deliberately narrow: only logic with genuinely zero role-specific
variation lives here (the estimated-spend calculation and the markdown-
fence-stripping preprocessing step for the AI Router's raw text
response). Each role's proposal-parsing/dispatch logic stays in its own
`agent.py` -- the action verbs, required-key sets, and validation differ
enough per role that forcing them into a shared base would be a leaky
abstraction, not a useful one (see ADR-0030's Context).
"""

from ai_platform.ports.ai_router import AICompletionUsage as ProviderCallUsage

# Rough, hardcoded USD-cents-per-1000-tokens estimates (input_rate,
# output_rate) for the ADR-0017 Decision 3-approved models -- NOT exact
# provider billing (ADR-0028 Decision 2). Update to match real current
# pricing before relying on the daily spend cap for anything beyond a
# rough circuit breaker; the action-count cap is the primary practical
# limiter.
_MODEL_RATE_CENTS_PER_1K_TOKENS: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (0.1, 0.5),
    "gpt-5-mini": (0.025, 0.2),
}
_DEFAULT_RATE_CENTS_PER_1K_TOKENS = (0.5, 1.5)


def estimate_spend_cents(usage: ProviderCallUsage) -> int:
    input_rate, output_rate = _MODEL_RATE_CENTS_PER_1K_TOKENS.get(
        usage.model, _DEFAULT_RATE_CENTS_PER_1K_TOKENS
    )
    estimated = (usage.input_tokens / 1000) * input_rate + (
        usage.output_tokens / 1000
    ) * output_rate
    return max(0, round(estimated))


def strip_markdown_json_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) < 2 or lines[-1].strip() != "```":
        return stripped
    return "\n".join(lines[1:-1]).strip()
