"""Technical Review Agent module (ADR-0022).

The platform's seventh capability, `technical.review`: a bounded proposed
data model/schema, API/contract definition, service-boundary design, or
deployment-topology text in, a bounded list of advisory review findings
out (never applied automatically), via the same technology-neutral AI
Router port `summarize_agent`/`review_agent` use. Structurally identical
to `ai_platform.agents.data_analysis_agent` -- the only difference is the
findings' locator key (`component` instead of `metric`) and the review
prompt's persona/framing. No new external side effect, no new
architecture.
"""
