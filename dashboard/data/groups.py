"""Campaign group matcher. Maps FB campaign names to logical groups."""
from __future__ import annotations

from dashboard.config import CAMPAIGN_GROUPS


def match_group(campaign_name: str) -> str | None:
    """Return the group label for a campaign name, or None if no match.

    Order in CAMPAIGN_GROUPS matters: EMX is checked before Chiro so that
    a campaign containing both tokens is classified as EMX (more specific).
    """
    if not campaign_name:
        return None
    for label, pattern in CAMPAIGN_GROUPS:
        if pattern.search(campaign_name):
            return label
    return None
