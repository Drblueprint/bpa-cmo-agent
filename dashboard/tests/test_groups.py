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
    # Chiro is listed before NLAP in CAMPAIGN_GROUPS, so first-match wins
    assert match_group("DS | __NLAP__ but also __Chiro__") == "Chiro"


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


def test_merge_list_group_excludes_emails():
    memberships = pd.DataFrame([
        {"contact_id": "1", "membership_timestamp": "2026-06-03T00:00:00Z"},
    ])
    list_contacts = pd.DataFrame([{"hs_id": "1", "email": "Drop@X.com", "name": "A"}])
    existing = pd.DataFrame([{"hs_id": "9", "email": "z@x.com",
                              "typeform_asset_download": "Top 10 typeform"}])
    load_m, load_c = _fake_loaders(memberships, list_contacts)
    out = merge_list_group(
        existing, list_id="7086", asset_label="NLAP FB Lead", group="NLAP",
        start=date(2026, 6, 1), end=date(2026, 6, 30),
        load_memberships=load_m, load_contacts=load_c,
        excluded_emails={"drop@x.com"}, asset_to_group={},
    )
    assert set(out["hs_id"].astype(str)) == {"9"}   # member 1 dropped by email


# --- MAP segment + renamed-asset attribution fix (2026-08-28) ---------------
# Live probe (120d) found three actively-used typeform asset labels mapped to
# nothing, so their leads attributed to no group at all: 54 + 16 Chiro leads
# and 13 MAP leads. Two are renamed variants of already-mapped assets. See
# docs/superpowers/specs/2026-08-27-paid-media-mql-dashboard-design.md.

from dashboard import config as cfg


def test_match_group_map_protocol():
    """MAP Protocol campaigns were matching no group, so their spend was
    invisible in every group breakdown."""
    assert match_group(
        "DS | MAP Protocol Funnel Setup | CBO | USA | Aug 2026 New Images | C1"
    ) == "MAP"
    assert match_group(
        "DS | MAP Protocol Funnel Setup | CBO | USA | Aug 2026 Images | C1-2"
    ) == "MAP"


def test_map_regex_does_not_capture_other_campaigns():
    """Verified against all 46 distinct campaign names in the trailing 120
    days: the MAP pattern hits the three MAP campaigns and nothing else."""
    assert match_group("DS | __Chiro__ Mixed Funnel Setup | CBO | USA") == "Chiro"
    assert match_group("DS | EMX 2026 Kansas City Mixed Funnel Setup") == "EMX"
    assert match_group("DS | __NLAP__ Funnel Setup | CBO | USA | CA") == "NLAP"
    assert match_group("DS | __Theraray__ Funnel Setup | CBO | USA") == "TheraRay"


@pytest.mark.parametrize("label,expected", [
    # Renamed variants of assets already mapped under their old labels.
    ("Top 10 Things Muiltimillion Dollar Practices Do", "Chiro"),
    ("BPA Revenue Pyramid", "Chiro"),
    # NOTE: trailing space is part of the value HubSpot stores. Dropping it
    # makes the lookup miss silently, which is the bug being fixed here.
    ("Movement Activation Protocol ", "MAP"),
])
def test_renamed_assets_now_attribute(label, expected):
    assert cfg.ASSET_TO_GROUP.get(label) == expected


def test_original_asset_labels_still_mapped():
    """The old labels stay in place; both variants are live in HubSpot."""
    assert cfg.ASSET_TO_GROUP["Top 10 typeform"] == "Chiro"
    assert cfg.ASSET_TO_GROUP["BPA Revenue Pyramid typeform"] == "Chiro"


def test_map_asset_requires_exact_trailing_space():
    """Guard against a future edit 'tidying' the trailing space away."""
    assert "Movement Activation Protocol " in cfg.ASSET_TO_GROUP
    assert "Movement Activation Protocol" not in cfg.ASSET_TO_GROUP


def test_list_based_assets_stay_unmapped():
    """TheraRay and NLAP attribute through HubSpot lists 6280 / 7086. Adding
    asset mappings for them would double-count those leads."""
    for label in ("TheraRay", "TheraRay Device ", "TheraRay User ",
                  "NLAP User ", "Neuro-Lymphatic Activation Protocol "):
        assert label not in cfg.ASSET_TO_GROUP
