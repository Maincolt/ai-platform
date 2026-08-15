"""Data Analysis Agent module (ADR-0021).

The platform's sixth capability, `data.analysis`: a bounded dataset
excerpt, metrics summary, or usage/cost report text in, a bounded list of
advisory review findings out (never applied automatically), via the same
technology-neutral AI Router port `summarize_agent`/`review_agent` use.
Structurally identical to `ai_platform.agents.architecture_review_agent` --
the only difference is the findings' locator key (`metric` instead of
`section`) and the review prompt's persona/framing. No new external side
effect, no new architecture.
"""
