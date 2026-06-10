"""Tests for daily_va_summary — the morning chat post numbers."""
from datetime import date as _d

import pandas as pd

from dashboard.data.reconcile import daily_va_summary


def test_daily_va_summary_basic_chiro_split():
    """All Leads = typeform submitted in window. New Leads = subset whose
    contact createdate is ALSO in window (didn't exist before).
    """
    fb = pd.DataFrame([
        # Chiro spend on May 5: $400
        {"group": "Chiro", "spend": 400.0,
         "date_start": "2026-05-05"},
        # EMX spend on May 7: $100 (rolls up into Chiro per metrics-tab convention)
        {"group": "EMX", "spend": 100.0,
         "date_start": "2026-05-07"},
        # TheraRay spend on May 6: $50
        {"group": "TheraRay", "spend": 50.0,
         "date_start": "2026-05-06"},
        # Out of window
        {"group": "Chiro", "spend": 999.0,
         "date_start": "2026-04-30"},
    ])
    contacts = pd.DataFrame([
        # Chiro: brand-new lead in window
        {"hs_id": "c1", "typeform_asset_download": "Top 10 typeform",
         "typeform_submission_date": "2026-05-10T12:00:00Z",
         "created": "2026-05-10T12:00:00Z"},
        # Chiro: returning lead (created before window, resubmitted in window)
        {"hs_id": "c2", "typeform_asset_download": "Top 10 typeform",
         "typeform_submission_date": "2026-05-12T09:00:00Z",
         "created": "2026-02-01T00:00:00Z"},
        # EMX: brand-new lead (rolls into Chiro count)
        {"hs_id": "c3", "typeform_asset_download": "EMX Kansas City",
         "typeform_submission_date": "2026-05-08T10:00:00Z",
         "created": "2026-05-08T10:00:00Z"},
        # PT: not counted under Chiro
        {"hs_id": "c4", "typeform_asset_download": "Recovery Program (PT) typeform",
         "typeform_submission_date": "2026-05-09T10:00:00Z",
         "created": "2026-05-09T10:00:00Z"},
        # Chiro but out of window — excluded
        {"hs_id": "c5", "typeform_asset_download": "Top 10 typeform",
         "typeform_submission_date": "2026-04-29T10:00:00Z",
         "created": "2026-04-29T10:00:00Z"},
    ])
    theraray = pd.DataFrame([
        {"contact_id": "t1", "membership_timestamp": "2026-05-03T10:00:00Z"},
        {"contact_id": "t2", "membership_timestamp": "2026-05-15T10:00:00Z"},
        # Out of window
        {"contact_id": "t3", "membership_timestamp": "2026-04-15T10:00:00Z"},
    ])

    out = daily_va_summary(
        fb=fb, contacts=contacts, theraray_memberships=theraray,
        nlap_memberships=pd.DataFrame(columns=["contact_id", "membership_timestamp"]),
        start=_d(2026, 5, 1), end=_d(2026, 5, 21),
        asset_to_group={
            "Top 10 typeform": "Chiro",
            "EMX Kansas City": "EMX",
            "Recovery Program (PT) typeform": "PT Recovery",
        },
    )

    # Chiro+EMX spend: 400 + 100 = 500
    assert out["chiro_spend"] == 500.0
    # All Leads: c1 + c2 + c3 = 3 (c2 is returning but still an All Lead)
    assert out["chiro_all_leads"] == 3
    # New Leads: c1 + c3 = 2 (c2's createdate is February, excluded)
    assert out["chiro_new_leads"] == 2
    assert out["chiro_cpl_all"] == 500.0 / 3
    assert out["chiro_cpl_new"] == 500.0 / 2
    # TheraRay: 2 submissions in window, $50 spend, CPL = $25
    assert out["theraray_submissions"] == 2
    assert out["theraray_ad_spend"] == 50.0
    assert out["theraray_cpl"] == 25.0


def test_daily_va_summary_handles_empty_inputs():
    """No data → all zeros, no exceptions."""
    out = daily_va_summary(
        fb=pd.DataFrame(columns=["group", "spend", "date_start"]),
        contacts=pd.DataFrame(),
        theraray_memberships=pd.DataFrame(columns=["contact_id", "membership_timestamp"]),
        nlap_memberships=pd.DataFrame(columns=["contact_id", "membership_timestamp"]),
        start=_d(2026, 5, 1), end=_d(2026, 5, 21),
        asset_to_group={},
    )
    assert out["chiro_spend"] == 0.0
    assert out["chiro_all_leads"] == 0
    assert out["chiro_new_leads"] == 0
    assert out["chiro_cpl_all"] is None
    assert out["chiro_cpl_new"] is None
    assert out["theraray_submissions"] == 0
    assert out["theraray_ad_spend"] == 0.0
    assert out["theraray_cpl"] is None


def test_daily_va_summary_single_day_window():
    """Yesterday-only window (start == end) works correctly."""
    fb = pd.DataFrame([
        {"group": "Chiro", "spend": 421.04, "date_start": "2026-05-21"},
        {"group": "Chiro", "spend": 100.0, "date_start": "2026-05-20"},
    ])
    contacts = pd.DataFrame([
        # New Chiro lead on May 21
        {"hs_id": "c1", "typeform_asset_download": "Top 10 typeform",
         "typeform_submission_date": "2026-05-21T12:00:00Z",
         "created": "2026-05-21T12:00:00Z"},
        # May 20 (out of single-day window)
        {"hs_id": "c2", "typeform_asset_download": "Top 10 typeform",
         "typeform_submission_date": "2026-05-20T12:00:00Z",
         "created": "2026-05-20T12:00:00Z"},
    ])

    out = daily_va_summary(
        fb=fb, contacts=contacts,
        theraray_memberships=pd.DataFrame(columns=["contact_id", "membership_timestamp"]),
        nlap_memberships=pd.DataFrame(columns=["contact_id", "membership_timestamp"]),
        start=_d(2026, 5, 21), end=_d(2026, 5, 21),
        asset_to_group={"Top 10 typeform": "Chiro"},
    )
    assert out["chiro_spend"] == 421.04
    assert out["chiro_all_leads"] == 1
    assert out["chiro_new_leads"] == 1
