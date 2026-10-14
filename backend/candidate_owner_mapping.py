"""Candidate Owner Identity Mapping for V3 Pre-Cutover.

Rules:
- Never infer owner identity from email or username.
- Do not silently promote rehearsal placeholder UUIDs.
- Require explicit approved owner identifier via configuration.
- Support an explicit HELD/unresolved state for side-by-side candidates.
- In HELD state, owner routes fail-closed (503 / 403).
- Zero writes to economic or customer collections.
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Rehearsal placeholder UUIDs that MUST NOT be used as deployable identities.
REHEARSAL_PLACEHOLDER_UUIDS = frozenset({
    "349e6cf6-9b48-57e1-9242-08965d0fe2e3",  # rehearsal platform principal
    "ce92cb15-5491-5683-a39a-9cd739c4285f",  # rehearsal tenant owner principal
})


@dataclass(frozen=True)
class CandidateOwnerResolution:
    """Status of owner resolution for pre-cutover."""
    is_resolved: bool
    owner_id: str | None
    status: str  # "APPROVED" | "HELD" | "REJECTED"
    requires_approval: str
    detail: str


def resolve_candidate_owner() -> CandidateOwnerResolution:
    """Resolve the candidate owner identity from explicit environment/config.

    Fails closed if the configured identity is a known rehearsal placeholder
    or if no identity is configured.
    """
    configured = os.environ.get("CANDIDATE_OWNER_ID", "").strip()

    if not configured:
        return CandidateOwnerResolution(
            is_resolved=False,
            owner_id=None,
            status="HELD",
            requires_approval="OWNER_PROD_UUID_CONFIRMATION",
            detail="No candidate owner ID provided; owner operations remain HELD.",
        )

    if configured in REHEARSAL_PLACEHOLDER_UUIDS:
        return CandidateOwnerResolution(
            is_resolved=False,
            owner_id=None,
            status="REJECTED",
            requires_approval="PRODUCTION_OWNER_AUTHORIZATION",
            detail="Rehearsal placeholder UUID rejected as deployable owner.",
        )

    return CandidateOwnerResolution(
        is_resolved=True,
        owner_id=configured,
        status="APPROVED",
        requires_approval="FINAL_PRODUCTION_SIGN_OFF",
        detail="Candidate owner resolved from explicit configuration.",
    )


def require_candidate_owner_access() -> str:
    """FastAPI helper: return owner_id or raise fail-closed exception."""
    from fastapi import HTTPException
    resolution = resolve_candidate_owner()
    if not resolution.is_resolved:
        raise HTTPException(
            status_code=503,
            detail=f"Owner access held ({resolution.status}): {resolution.detail}",
        )
    return resolution.owner_id
