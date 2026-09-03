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
    build_lead_frames, unmapped_asset_counts, unmapped_asset_warning,
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
