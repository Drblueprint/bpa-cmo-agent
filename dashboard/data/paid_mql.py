"""Pure rollup logic for the PAID MEDIA tab. No I/O.

Config values arrive as parameters rather than imports, matching the
convention in reconcile.py and paid_media.py, so every function here is
testable without touching Streamlit secrets or any API.

Spec: docs/superpowers/specs/2026-08-27-paid-media-mql-dashboard-design.md
"""
from __future__ import annotations

import pandas as pd

from dashboard.data.groups import match_group

UNMATCHED = "(unmatched)"


def _safe_div(num: float, den: float) -> float | None:
    """None on a zero denominator, never 0. A zero denominator and a genuine
    zero are different facts and must render differently.

    Deliberately duplicates reconcile._safe_div to avoid coupling a small pure
    module to a 3,240-line module for a one-liner.
    """
    if not den:
        return None
    return num / den


def resolve_segment(campaign_name, *, segment_rollup: dict[str, str],
                    unmatched_label: str = UNMATCHED) -> str:
    """Map an FB campaign name to a PAID MEDIA segment.

    Applies the existing CAMPAIGN_GROUPS match, then folds groups into their
    roll-up segment (EMX and Practice Growth Workshop both become Event).
    A campaign matching nothing returns the unmatched label rather than None,
    so it surfaces as a visible row instead of vanishing.
    """
    if not campaign_name:
        return unmatched_label
    group = match_group(campaign_name)
    if not group:
        return unmatched_label
    return segment_rollup.get(group, group)
