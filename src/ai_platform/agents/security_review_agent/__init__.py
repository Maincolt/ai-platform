"""Security Review Agent module (ADR-0025).

The platform's ninth capability, `security.review`: a bounded code diff,
configuration file, infrastructure-as-code snippet, or design description
in, a bounded list of advisory security findings out (never applied
automatically), via the same technology-neutral AI Router port
`summarize_agent`/`review_agent` use. Structurally identical to
`ai_platform.agents.technical_review_agent` -- the only difference is the
findings' locator key (`location` instead of `component`) and the review
prompt's adversarial security framing. No new external side effect, no
new architecture.
"""
