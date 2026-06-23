from __future__ import annotations

from copy import deepcopy
from typing import Any


def apply_current_score_validation_to_payload(
    payload: dict[str, Any] | None,
    score_validation: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Return a display payload without mutating the stored prediction snapshot.

    The shared build keeps the snapshot's paper layer intact for replay and audit.
    Current score-distribution validation is attached as context, but it no longer
    rewrites historical p_adj/shrink_k/paper_EV fields or cancels PAPER_BUY.
    """
    if not isinstance(payload, dict):
        return payload

    current = deepcopy(payload)
    if score_validation:
        current["scoreDistributionValidation"] = score_validation
    return current
