"""Architecture Review Agent module (ADR-0020).

The platform's fifth capability, `architecture.review`: a bounded
architectural proposal/design-doc/ADR-draft text in, a bounded list of
advisory review findings out (never applied automatically), via the same
technology-neutral AI Router port `summarize_agent`/`review_agent` use.
Structurally identical to `ai_platform.agents.review_agent` -- the only
difference is the findings' locator key (`section` instead of `file`/
`line`, since a document has no file/line concept) and the review prompt's
persona/framing. No new external side effect, no new architecture, unlike
`ui_review_agent`.
"""
