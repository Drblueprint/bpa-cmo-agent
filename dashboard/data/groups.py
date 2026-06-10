"""Campaign group matcher. Maps FB campaign names to logical groups."""
from __future__ import annotations

import pandas as pd

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


def merge_list_group(
    contacts,
    *,
    list_id,
    asset_label,
    group,
    start,
    end,
    load_memberships,
    load_contacts,
    excluded_emails=frozenset(),
    asset_to_group=None,
):
    """Merge a HubSpot list's in-window members into `contacts`.

    Mirrors the original TheraRay merge: filter `load_memberships(list_id)` to
    membership_timestamp in [start, end], load those contacts via
    `load_contacts(ids)`, drop `excluded_emails`, tag
    typeform_asset_download=asset_label + typeform_submission_date=membership ts,
    register asset_to_group[asset_label]=group (if a dict is passed), concat the
    list rows FIRST then drop_duplicates(subset="hs_id", keep="first") so the tag
    survives, and force-tag the asset on all list-member ids.

    load_memberships(list_id) -> df[contact_id, membership_timestamp].
    load_contacts(list[str])  -> contacts df with hs_id + email columns.
    Returns the merged contacts df (unchanged if no in-window members).
    """
    memberships = load_memberships(list_id)
    if memberships is None or memberships.empty:
        return contacts
    mt = pd.to_datetime(memberships["membership_timestamp"], utc=True, errors="coerce")
    start_ts = pd.Timestamp(year=start.year, month=start.month, day=start.day, tz="UTC")
    end_ts = pd.Timestamp(year=end.year, month=end.month, day=end.day, tz="UTC") + pd.Timedelta(days=1)
    in_window = memberships[(mt >= start_ts) & (mt < end_ts)]
    window_ids = in_window["contact_id"].tolist()
    if not window_ids:
        return contacts
    new_rows = load_contacts(window_ids)
    if new_rows is None or new_rows.empty:
        return contacts
    if excluded_emails:
        new_rows = new_rows[
            ~new_rows["email"].fillna("").str.lower().isin(excluded_emails)
        ].copy()
    if new_rows.empty:
        return contacts
    ts_map = dict(zip(in_window["contact_id"].astype(str),
                      in_window["membership_timestamp"]))
    new_rows = new_rows.copy()
    new_rows["typeform_asset_download"] = asset_label
    new_rows["typeform_submission_date"] = new_rows["hs_id"].astype(str).map(ts_map)
    if asset_to_group is not None:
        asset_to_group[asset_label] = group
    if contacts is None or contacts.empty:
        merged = new_rows
    else:
        merged = pd.concat([new_rows, contacts], ignore_index=True) \
            .drop_duplicates(subset="hs_id", keep="first").reset_index(drop=True)
    _ids = set(new_rows["hs_id"].astype(str))
    _mask = merged["hs_id"].astype(str).isin(_ids)
    merged.loc[_mask, "typeform_asset_download"] = asset_label
    return merged
