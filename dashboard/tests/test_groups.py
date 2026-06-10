"""Tests for campaign group regex matcher."""
import pytest

from dashboard.data.groups import match_group


@pytest.mark.parametrize("name,expected", [
    ("DS | __Chiro__ Mixed Funnel Setup | CBO | USA", "Chiro"),
    ("DS | __PT__ Recovery Program Funnel | CBO | USA", "PT Recovery"),
    ("DS | __Theraray__ Funnel Setup | CBO | USA", "TheraRay"),
    ("DS | __EMX__ Event Funnel | CBO | USA", "EMX"),
    ("DS | __Chiro__ but also __EMX__ inside", "EMX"),  # EMX wins
    ("Something with no marker", None),
    ("", None),
])
def test_match_group(name, expected):
    assert match_group(name) == expected


def test_match_group_nlap():
    assert match_group("DS | __NLAP__ Funnel Setup | CBO | USA | CA") == "NLAP"


def test_match_group_existing_unaffected():
    assert match_group("DS | __Theraray__ Funnel Setup | CBO | USA") == "TheraRay"
    assert match_group("DS | __Chiro__ Mixed Funnel Setup | CBO") == "Chiro"
    assert match_group("DS | EMX 2026 Kansas City Mixed Funnel Setup") == "EMX"
    assert match_group("DS | __NLAP__ but also __Chiro__") == "NLAP" or \
           match_group("DS | __NLAP__ but also __Chiro__") == "Chiro"


import pandas as pd
from datetime import date
from dashboard.data.groups import merge_list_group


def _fake_loaders(memberships_df, contacts_df):
    return (lambda _list_id: memberships_df,
            lambda ids: contacts_df[contacts_df["hs_id"].astype(str).isin([str(i) for i in ids])].copy())


def test_merge_list_group_tags_and_routes():
    memberships = pd.DataFrame([
        {"contact_id": "1", "membership_timestamp": "2026-06-03T00:00:00Z"},  # in window
        {"contact_id": "2", "membership_timestamp": "2026-01-01T00:00:00Z"},  # out of window
    ])
    list_contacts = pd.DataFrame([
        {"hs_id": "1", "email": "a@x.com", "name": "A"},
        {"hs_id": "2", "email": "b@x.com", "name": "B"},
    ])
    existing = pd.DataFrame([{"hs_id": "9", "email": "z@x.com", "name": "Z",
                              "typeform_asset_download": "Top 10 typeform"}])
    a2g = {}
    load_m, load_c = _fake_loaders(memberships, list_contacts)
    out = merge_list_group(
        existing, list_id="7086", asset_label="NLAP FB Lead", group="NLAP",
        start=date(2026, 6, 1), end=date(2026, 6, 30),
        load_memberships=load_m, load_contacts=load_c, asset_to_group=a2g,
    )
    # only contact 1 (in window) merged + tagged; contact 9 preserved
    assert set(out["hs_id"].astype(str)) == {"1", "9"}
    row1 = out[out["hs_id"].astype(str) == "1"].iloc[0]
    assert row1["typeform_asset_download"] == "NLAP FB Lead"
    assert a2g["NLAP FB Lead"] == "NLAP"


def test_merge_list_group_dedup_keeps_tag():
    """A member already in contacts (untagged) gets the list tag after merge."""
    memberships = pd.DataFrame([
        {"contact_id": "1", "membership_timestamp": "2026-06-03T00:00:00Z"},
    ])
    list_contacts = pd.DataFrame([{"hs_id": "1", "email": "a@x.com", "name": "A"}])
    existing = pd.DataFrame([{"hs_id": "1", "email": "a@x.com", "name": "A",
                              "typeform_asset_download": ""}])
    load_m, load_c = _fake_loaders(memberships, list_contacts)
    out = merge_list_group(
        existing, list_id="7086", asset_label="NLAP FB Lead", group="NLAP",
        start=date(2026, 6, 1), end=date(2026, 6, 30),
        load_memberships=load_m, load_contacts=load_c, asset_to_group={},
    )
    assert len(out) == 1
    assert out.iloc[0]["typeform_asset_download"] == "NLAP FB Lead"


def test_merge_list_group_no_window_members_noop():
    memberships = pd.DataFrame([
        {"contact_id": "2", "membership_timestamp": "2026-01-01T00:00:00Z"},
    ])
    existing = pd.DataFrame([{"hs_id": "9", "email": "z@x.com",
                              "typeform_asset_download": "Top 10 typeform"}])
    load_m, load_c = _fake_loaders(memberships, pd.DataFrame(columns=["hs_id", "email"]))
    out = merge_list_group(
        existing, list_id="7086", asset_label="NLAP FB Lead", group="NLAP",
        start=date(2026, 6, 1), end=date(2026, 6, 30),
        load_memberships=load_m, load_contacts=load_c, asset_to_group={},
    )
    assert out.equals(existing)
