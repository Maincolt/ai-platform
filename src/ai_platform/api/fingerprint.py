"""Request fingerprinting (vertical-slice-01.md Section 6, ADR-0004
"Canonical Serialization").

The fingerprint determines whether reuse of an accepted-request key is an
equivalent replay or a conflict. It includes exact decoded text, capability
name/version, and the API contract major version; it excludes property
order, JSON whitespace, headers, correlation, and trace data. Computed as
the SHA-256 digest of the RFC 8785 (JSON Canonicalization Scheme) canonical
UTF-8 bytes, using the `rfc8785` package rather than a hand-rolled
canonicalizer (see docs/sprint-5/consilium.md).
"""

import hashlib

import rfc8785

# Fixed for this slice: there is exactly one API contract major version.
# A future multi-version scheme would plug in here (see
# docs/sprint-5/consilium.md, disagreement 2).
API_CONTRACT_MAJOR = "1"

FINGERPRINT_POLICY_VERSION = "1.0"


def compute_fingerprint(
    *,
    text: str,
    capability_name: str,
    capability_version: str,
) -> str:
    """Return the lowercase hexadecimal SHA-256 fingerprint digest."""
    canonical_bytes = rfc8785.dumps(
        {
            "text": text,
            "capability": capability_name,
            "capability_version": capability_version,
            "api_contract_major": API_CONTRACT_MAJOR,
        }
    )
    return hashlib.sha256(canonical_bytes).hexdigest()
