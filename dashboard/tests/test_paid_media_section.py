"""Tests for the PAID MEDIA section's frame construction and tripwires.

These cover dashboard/sections/paid_media.py rather than the pure rollup
module. Everything tested here is a module-level function taking config as
parameters, so no Streamlit runtime is needed.
"""
from datetime import date

import pandas as pd
import pytest

from dashboard.data.paid_mql import UNMATCHED_LEADS, daily_mql_summary
from dashboard.sections.paid_media import (
    available_segments, build_lead_frames, unmapped_asset_counts,
    unmapped_asset_warning,
)

# merge_list_group re-tags TheraRay and NLAP list members with these synthetic
# labels and registers them in ASSET_TO_GROUP at runtime, which is why they
# appear here. The RAW HubSpot labels those same contacts carry ("NLAP User ",
# "TheraRay Device ") stay deliberately and permanently unmapped, pinned by
# test_groups.test_list_based_assets_stay_unmapped.
ASSETS = {
    "Top 10 typeform": "Chiro",
    "EMX typeform": "EMX",
    "NLAP FB Lead": "NLAP",
    "TheraRay FB Lead": "TheraRay",
}
ROLLUP = {"EMX": "Event", "Practice Growth Workshop": "Event"}
START, END = date(2026, 8, 1), date(2026, 8, 31)

NLAP_CAMPAIGN = "DS | __NLAP__ Funnel Setup | CBO | USA"


def _contacts(rows):
    return pd.DataFrame(rows, columns=[
        "hs_id", "email", "typeform_submission_date",
        "typeform_asset_download"])


def _mqls(rows):
    return pd.DataFrame(rows, columns=[
        "email", "mql_entered_at", "typeform_asset_download"])


def _frames(contacts, mqls):
    return build_lead_frames(contacts, mqls, START, END,
                             asset_to_group=ASSETS, segment_rollup=ROLLUP)


# --- B1: one contact, one segment, on both sides of the page ---------------

def test_list_group_mql_segments_from_contacts_not_from_its_raw_asset():
    """B1: the two frames derived segment from different sources. leads took it
    from the POST-MERGE contacts frame, where merge_list_group re-tagged list
    members as "NLAP FB Lead"; mql_frame took it from the MQL loader's own RAW
    HubSpot asset "NLAP User ", which maps to nothing. The same contact was
    therefore segmented one way as a lead and another way as an MQL, so an NLAP
    filter kept all of NLAP's spend and dropped every one of its MQLs."""
    contacts = _contacts([
        ("1", "doc@example.com", "2026-08-10T12:00:00Z", "NLAP FB Lead"),
        ("2", "dev@example.com", "2026-08-11T12:00:00Z", "TheraRay FB Lead"),
    ])
    mqls = _mqls([
        ("doc@example.com", "2026-08-12T09:00:00Z", "NLAP User "),
        ("dev@example.com", "2026-08-13T09:00:00Z", "TheraRay Device "),
    ])
    leads, mql_frame = _frames(contacts, mqls)
    assert leads["segment"].tolist() == ["NLAP", "TheraRay"]
    assert mql_frame["segment"].tolist() == ["NLAP", "TheraRay"]


def test_nlap_contact_counts_as_lead_and_mql_under_a_segment_filter():
    """The shipped page always passes segments=tuple(picked). Under that path
    the numerator survived and the denominator disappeared, overstating Cost
    Per Callable MQL."""
    contacts = _contacts([
        ("1", "doc@example.com", "2026-08-10T12:00:00Z", "NLAP FB Lead"),
    ])
    mqls = _mqls([("doc@example.com", "2026-08-12T09:00:00Z", "NLAP User ")])
    leads, mql_frame = _frames(contacts, mqls)

    fb_daily = pd.DataFrame(
        [("2026-08-10", NLAP_CAMPAIGN, 400.0)],
        columns=["date_start", "campaign_name", "spend"])
    out = daily_mql_summary(fb_daily, leads, mql_frame,
                            segment_rollup=ROLLUP, segments=("NLAP",))
    total = out[out["date"] == "Total"].iloc[0]
    assert total["leads"] == 1
    assert total["callable_mql"] == 1
    assert total["cost_per_callable_mql"] == 400.0


def test_mql_email_absent_from_contacts_falls_back_to_its_own_asset():
    """An MQL the contacts frame never saw (its typeform_submission_date fell
    outside the window, say) keeps the asset mapping as a fallback rather than
    losing its segment."""
    contacts = _contacts([
        ("1", "known@example.com", "2026-08-10T12:00:00Z", "Top 10 typeform"),
    ])
    mqls = _mqls([
        ("ghost@example.com", "2026-08-12T09:00:00Z", "Top 10 typeform"),
    ])
    _leads, mql_frame = _frames(contacts, mqls)
    assert mql_frame["segment"].tolist() == ["Chiro"]


def test_known_contact_with_unmapped_asset_does_not_use_the_fallback():
    """Consistency is the point. If the contacts frame cannot segment this
    person as a lead, the MQL side must not invent a different answer, or the
    two halves of the page drift apart again."""
    contacts = _contacts([
        ("1", "doc@example.com", "2026-08-10T12:00:00Z", "Renamed Thing "),
    ])
    mqls = _mqls([("doc@example.com", "2026-08-12T09:00:00Z",
                   "Top 10 typeform")])
    leads, mql_frame = _frames(contacts, mqls)
    assert leads["segment"].isna().all()
    assert mql_frame["segment"].isna().all()


def test_email_lookup_is_case_and_whitespace_insensitive():
    contacts = _contacts([
        ("1", "  Doc@Example.COM ", "2026-08-10T12:00:00Z", "NLAP FB Lead"),
    ])
    mqls = _mqls([("DOC@example.com ", "2026-08-12T09:00:00Z", "NLAP User ")])
    _leads, mql_frame = _frames(contacts, mqls)
    assert mql_frame["segment"].tolist() == ["NLAP"]


def test_duplicate_contact_emails_prefer_the_resolvable_segment():
    """Two hs_ids can share an email, one of them list-merged and one not."""
    contacts = _contacts([
        ("1", "doc@example.com", "2026-08-09T12:00:00Z", "Mystery Asset "),
        ("2", "doc@example.com", "2026-08-10T12:00:00Z", "NLAP FB Lead"),
    ])
    mqls = _mqls([("doc@example.com", "2026-08-12T09:00:00Z", "NLAP User ")])
    _leads, mql_frame = _frames(contacts, mqls)
    assert mql_frame["segment"].tolist() == ["NLAP"]


def test_lead_dating_and_window_filter_survive_the_change():
    """Regression guard: leads are still dated by typeform_submission_date and
    still dropped when that date is null or outside the window."""
    contacts = _contacts([
        ("1", "in@example.com", "2026-08-10T12:00:00Z", "Top 10 typeform"),
        ("2", "early@example.com", "2026-07-30T12:00:00Z", "Top 10 typeform"),
        ("3", "null@example.com", None, "Top 10 typeform"),
    ])
    leads, _mql_frame = _frames(contacts, _mqls([]))
    assert leads["email"].tolist() == ["in@example.com"]
    assert leads["lead_date"].tolist() == ["2026-08-10"]


def test_empty_mql_frame_does_not_raise():
    contacts = _contacts([
        ("1", "a@example.com", "2026-08-10T12:00:00Z", "Top 10 typeform"),
    ])
    leads, mql_frame = _frames(contacts, _mqls([]))
    assert len(leads) == 1
    assert mql_frame.empty


# --- B2 part 2: name the unmapped asset labels -----------------------------

def test_unmapped_asset_counts_names_labels_and_lead_counts():
    """The only tripwire on the page covered CAMPAIGN names, which is the
    failure mode that already announces itself. A missing ASSET key produces no
    error at all, only a quietly wrong number, so the spec requires a check
    that surfaces unmapped asset labels carrying non-trivial volume."""
    contacts = _contacts([
        ("1", "a@example.com", "2026-08-10T12:00:00Z", "Top 10 typeform"),
        ("2", "b@example.com", "2026-08-10T12:00:00Z", "Renamed Chiro Thing "),
        ("3", "c@example.com", "2026-08-11T12:00:00Z", "Renamed Chiro Thing "),
        ("4", "d@example.com", "2026-08-11T12:00:00Z", "Brand New Asset "),
    ])
    leads, _mql_frame = _frames(contacts, _mqls([]))
    assert unmapped_asset_counts(leads) == {
        "Renamed Chiro Thing ": 2, "Brand New Asset ": 1}


def test_unmapped_asset_counts_empty_when_everything_maps():
    contacts = _contacts([
        ("1", "a@example.com", "2026-08-10T12:00:00Z", "Top 10 typeform"),
    ])
    leads, _mql_frame = _frames(contacts, _mqls([]))
    assert unmapped_asset_counts(leads) == {}


def test_single_stray_unmapped_contact_does_not_nag():
    assert unmapped_asset_warning({"Odd One Off ": 1}, minimum=3) is None
    assert unmapped_asset_warning({}, minimum=3) is None


def test_unmapped_warning_names_every_label_once_volume_is_nontrivial():
    msg = unmapped_asset_warning({"Renamed Chiro Thing ": 4, "Stray ": 1},
                                 minimum=3)
    assert msg is not None
    assert "Renamed Chiro Thing " in msg
    assert "Stray " in msg
    assert "ASSET_TO_GROUP" in msg
    assert "5" in msg  # the total carried by unmapped labels


def test_unmapped_warning_counts_the_total_not_the_largest_label():
    """Five leads spread across five labels is still five orphaned leads."""
    counts = {f"Label {i} ": 1 for i in range(5)}
    assert unmapped_asset_warning(counts, minimum=3) is not None


def test_unmapped_warning_lists_labels_worst_first():
    msg = unmapped_asset_warning({"Small ": 1, "Big ": 9}, minimum=3)
    assert msg.index("Big ") < msg.index("Small ")


# --- Residual 1: orphan MQLs are as invisible as orphan leads --------------

LIST_ATTRIBUTED = frozenset({
    "TheraRay", "TheraRay Device ", "TheraRay User ", "NLAP User ",
    "Neuro-Lymphatic Activation Protocol ",
})


def _fb_window(rows):
    return pd.DataFrame(rows, columns=["campaign_name"])


CHIRO_CAMPAIGN = "DS | __Chiro__ Mixed Funnel Setup | CBO | USA"


def test_orphan_mqls_offer_the_bucket_even_with_no_orphan_leads():
    """The picker offered (unmatched leads) only when an orphan LEAD existed,
    but daily_mql_summary buckets orphan MQLs under the same label, so a window
    with orphan MQLs and no orphan leads filtered those MQLs straight out. That
    is B1's signature on a narrower trigger: numerator lost, spend kept."""
    contacts = _contacts([
        ("1", "a@example.com", "2026-08-10T12:00:00Z", "Top 10 typeform"),
    ])
    mqls = _mqls([
        ("a@example.com", "2026-08-10T09:00:00Z", "Top 10 typeform"),
        ("ghost1@example.com", "2026-08-10T09:00:00Z", "Renamed Thing "),
        ("ghost2@example.com", "2026-08-10T09:00:00Z", "Renamed Thing "),
        ("ghost3@example.com", "2026-08-10T09:00:00Z", "Renamed Thing "),
        ("ghost4@example.com", "2026-08-10T09:00:00Z", "Renamed Thing "),
    ])
    leads, mql_frame = _frames(contacts, mqls)
    assert not leads["segment"].isna().any(), "no orphan LEADS in this shape"
    assert mql_frame["segment"].isna().sum() == 4

    available = available_segments(leads, mql_frame,
                                   _fb_window([(CHIRO_CAMPAIGN,)]),
                                   segment_rollup=ROLLUP)
    assert UNMATCHED_LEADS in available

    out = daily_mql_summary(
        pd.DataFrame([("2026-08-10", CHIRO_CAMPAIGN, 1000.0)],
                     columns=["date_start", "campaign_name", "spend"]),
        leads, mql_frame, segment_rollup=ROLLUP, segments=tuple(available))
    total = out[out["date"] == "Total"].iloc[0]
    assert total["callable_mql"] == 5
    assert total["cost_per_callable_mql"] == 200.0


def test_available_segments_offers_a_segment_only_the_mqls_carry():
    """A segment present in the MQL frame but in neither the leads frame nor a
    campaign name is still a segment the filter would otherwise delete."""
    contacts = _contacts([
        ("1", "a@example.com", "2026-08-10T12:00:00Z", "Top 10 typeform"),
        ("2", "n@example.com", "2026-07-01T12:00:00Z", "NLAP FB Lead"),
    ])
    mqls = _mqls([("n@example.com", "2026-08-12T09:00:00Z", "NLAP User ")])
    leads, mql_frame = _frames(contacts, mqls)
    assert "NLAP" not in set(leads["segment"])  # its lead date is out of window
    assert available_segments(leads, mql_frame,
                              _fb_window([(CHIRO_CAMPAIGN,)]),
                              segment_rollup=ROLLUP) == ["Chiro", "NLAP"]


def test_available_segments_stays_clean_when_everything_maps():
    contacts = _contacts([
        ("1", "a@example.com", "2026-08-10T12:00:00Z", "Top 10 typeform"),
    ])
    mqls = _mqls([("a@example.com", "2026-08-11T09:00:00Z", "Top 10 typeform")])
    leads, mql_frame = _frames(contacts, mqls)
    assert available_segments(leads, mql_frame,
                              _fb_window([(CHIRO_CAMPAIGN,)]),
                              segment_rollup=ROLLUP) == ["Chiro"]


def test_mql_frame_carries_the_asset_that_decided_its_segment():
    """The tripwire must name the label that actually decided the outcome. For
    a known contact that is the CONTACT's label, not the MQL loader's own copy,
    which can be a different and even mapped label for the same person."""
    contacts = _contacts([
        ("1", "doc@example.com", "2026-08-10T12:00:00Z", "Renamed Thing "),
    ])
    mqls = _mqls([("doc@example.com", "2026-08-12T09:00:00Z",
                   "Top 10 typeform")])
    _leads, mql_frame = _frames(contacts, mqls)
    assert mql_frame["asset"].tolist() == ["Renamed Thing "]
    assert unmapped_asset_counts(mql_frame) == {"Renamed Thing ": 1}


def test_unmapped_warning_covers_mqls_when_there_are_no_orphan_leads():
    msg = unmapped_asset_warning({}, mql_counts={"Renamed Thing ": 4},
                                 minimum=3)
    assert msg is not None
    assert "Renamed Thing " in msg
    assert "ASSET_TO_GROUP" in msg


# --- Residual 2: do not tell operators to break a pinned test --------------

def test_list_attributed_labels_are_never_told_to_be_added():
    """"TheraRay Device " and "Neuro-Lymphatic Activation Protocol " are pinned
    as permanently unmapped by test_groups.test_list_based_assets_stay_unmapped,
    because mapping them double-counts leads that already attribute through
    HubSpot lists 6280 and 7086. The warning must not instruct an operator to
    do the exact thing that test forbids."""
    msg = unmapped_asset_warning(
        {"TheraRay Device ": 4, "Neuro-Lymphatic Activation Protocol ": 7},
        list_attributed=LIST_ATTRIBUTED, minimum=3)
    assert msg is not None
    assert "TheraRay Device " in msg
    assert "BY DESIGN" in msg
    assert "Do NOT add these to ASSET_TO_GROUP" in msg
    # No instruction to add anything, because nothing here is addable.
    assert "Add these to config.ASSET_TO_GROUP" not in msg


def test_genuine_gap_and_by_design_labels_are_reported_separately():
    msg = unmapped_asset_warning(
        {"Renamed Chiro Thing ": 5, "TheraRay Device ": 2},
        list_attributed=LIST_ATTRIBUTED, minimum=3)
    assert "Add these to config.ASSET_TO_GROUP: \"Renamed Chiro Thing \"" in msg
    assert "Do NOT add these to ASSET_TO_GROUP" in msg
    # The by-design label must not appear in the addable clause.
    add_clause = msg.split("Add these to config.ASSET_TO_GROUP:")[1]
    assert add_clause.index("Do NOT add") < add_clause.find("TheraRay Device ")


def test_list_attributed_match_tolerates_a_changed_trailing_space():
    msg = unmapped_asset_warning({"theraray device": 4},
                                 list_attributed=LIST_ATTRIBUTED, minimum=3)
    assert "BY DESIGN" in msg
    assert "Add these to config.ASSET_TO_GROUP" not in msg


def test_contacts_with_no_asset_at_all_are_called_a_data_gap():
    msg = unmapped_asset_warning({}, mql_counts={"(no asset recorded)": 21},
                                 list_attributed=LIST_ATTRIBUTED, minimum=3)
    assert "no typeform asset at all" in msg
    assert "HubSpot data gap" in msg
    assert "Add these to config.ASSET_TO_GROUP" not in msg


def test_config_pins_the_list_attributed_labels_the_group_test_forbids():
    """The tripwire's by-design list and the pinning test must not drift."""
    from dashboard import config as cfg
    for label in ("TheraRay", "TheraRay Device ", "TheraRay User ",
                  "NLAP User ", "Neuro-Lymphatic Activation Protocol "):
        assert label in cfg.LIST_ATTRIBUTED_ASSETS
        assert label not in cfg.ASSET_TO_GROUP
