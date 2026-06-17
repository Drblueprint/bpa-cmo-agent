from dashboard.data.reconcile import _METRIC_LABELS
from dashboard.config import METRICS_GOALS


def test_scorecard_labels_present_and_clean():
    new = [
        "theraray_submissions", "nlap_submissions",
        "dti_15min_scheduled", "dti_discovery_completed",
        "bofu_submissions_direct",
    ]
    for mid in new:
        assert mid in _METRIC_LABELS, f"missing label for {mid}"
        assert mid in METRICS_GOALS, f"missing goal for {mid}"
    # No em dashes anywhere in user-facing labels.
    for label in _METRIC_LABELS.values():
        assert "—" not in label, f"em dash in label: {label!r}"
    # Registry and goals keys stay aligned.
    assert set(_METRIC_LABELS) == set(METRICS_GOALS)
    # Specific goals from the Ninety scorecard.
    assert METRICS_GOALS["nlap_submissions"] == 15
    assert METRICS_GOALS["dti_15min_scheduled"] == 2
    assert METRICS_GOALS["dti_discovery_completed"] == 5
    # Relabel: the FB TheraRay row is disambiguated.
    assert _METRIC_LABELS["theraray_leads"] == "TheraRay - FB Leads"


from datetime import date
import pandas as pd
from dashboard.data.reconcile import weekly_metrics

# Contacts fixture MUST carry all 5 date columns weekly_metrics parses, or it
# raises on the non-empty path. None is fine where unused.
_CONTACT_DATE_COLS = [
    "typeform_submission_date", "webinar_registration_date",
    "webinar_completed_date", "pt_webinar_registration_date",
    "pt_webinar_completed_date",
]


def _contacts(rows):
    df = pd.DataFrame(rows)
    for c in (["hs_id", "typeform_asset_download", "email"] + _CONTACT_DATE_COLS):
        if c not in df.columns:
            df[c] = None
    return df


def _ms(iso):
    return int(pd.Timestamp(iso).timestamp() * 1000)


WEEK = (date(2026, 6, 8), date(2026, 6, 14))


def _run(contacts, *, meetings=None, bofu=None):
    return weekly_metrics(
        fb=pd.DataFrame(),
        contacts=contacts,
        meetings=meetings if meetings is not None else pd.DataFrame(
            columns=["meeting_id", "contact_id", "activity_type", "outcome", "start_time"]),
        contact_deals=pd.DataFrame(columns=["contact_id", "deal_id"]),
        deals=pd.DataFrame(),
        bofu_submissions=bofu if bofu is not None else pd.DataFrame(
            columns=["form_id", "submission_id", "submitted_at", "email"]),
        week_ranges=[WEEK],
        asset_to_group={"TR": "TheraRay", "NL": "NLAP", "CH": "Chiro"},
        stages_closed_won=set(),
        new_customer_stages=set(),
        goals={},
    ).set_index("metric_id")


def test_dti_calls_combine_theraray_and_nlap_only():
    contacts = _contacts([
        {"hs_id": "1", "typeform_asset_download": "TR", "email": "a@x.com"},
        {"hs_id": "2", "typeform_asset_download": "NL", "email": "b@x.com"},
        {"hs_id": "3", "typeform_asset_download": "CH", "email": "c@x.com"},
    ])
    meetings = pd.DataFrame([
        {"meeting_id": "m1", "contact_id": "1", "activity_type": "15 min call",
         "outcome": "COMPLETE - QUALIFIED", "start_time": "2026-06-09T15:00:00Z"},
        {"meeting_id": "m2", "contact_id": "2", "activity_type": "15 min call",
         "outcome": "SCHEDULED", "start_time": "2026-06-10T15:00:00Z"},
        {"meeting_id": "m3", "contact_id": "3", "activity_type": "15 min call",
         "outcome": "COMPLETED", "start_time": "2026-06-11T15:00:00Z"},
        # DTI Intro Call activity type must NOT count (Kurt: 15-min only).
        {"meeting_id": "m4", "contact_id": "1", "activity_type": "DTI Intro Call",
         "outcome": "COMPLETED", "start_time": "2026-06-09T16:00:00Z"},
    ])
    r = _run(contacts, meetings=meetings)
    assert r.loc["dti_15min_scheduled", "w0"] == 2     # TR + NL 15-min; Chiro excluded; intro excluded
    assert r.loc["dti_discovery_completed", "w0"] == 1  # only TR held (COMPLETE*)


def test_theraray_nlap_submissions_by_group_and_date():
    contacts = _contacts([
        {"hs_id": "1", "typeform_asset_download": "TR",
         "typeform_submission_date": "2026-06-09T10:00:00Z", "email": "a@x.com"},
        {"hs_id": "2", "typeform_asset_download": "NL",
         "typeform_submission_date": "2026-06-10T10:00:00Z", "email": "b@x.com"},
        # NLAP contact submitted OUTSIDE the week -> not counted.
        {"hs_id": "3", "typeform_asset_download": "NL",
         "typeform_submission_date": "2026-05-01T10:00:00Z", "email": "c@x.com"},
        # Chiro contact -> not a DTI submission.
        {"hs_id": "4", "typeform_asset_download": "CH",
         "typeform_submission_date": "2026-06-09T10:00:00Z", "email": "d@x.com"},
    ])
    r = _run(contacts)
    assert r.loc["theraray_submissions", "w0"] == 1
    assert r.loc["nlap_submissions", "w0"] == 1


def test_bofu_direct_excludes_webinar_registrants():
    contacts = _contacts([
        # Registered for a webinar -> their BOFU is NOT direct.
        {"hs_id": "1", "typeform_asset_download": "CH", "email": "webinar@x.com",
         "webinar_registration_date": "2026-06-01T10:00:00Z"},
        # Registered for PT webinar -> also NOT direct.
        {"hs_id": "2", "typeform_asset_download": "CH", "email": "ptweb@x.com",
         "pt_webinar_registration_date": "2026-06-02T10:00:00Z"},
    ])
    bofu = pd.DataFrame([
        {"form_id": "f", "submission_id": "s1", "submitted_at": _ms("2026-06-10T12:00:00Z"),
         "email": "webinar@x.com"},   # has webinar -> not direct
        {"form_id": "f", "submission_id": "s2", "submitted_at": _ms("2026-06-10T12:00:00Z"),
         "email": "ptweb@x.com"},     # has PT webinar -> not direct
        {"form_id": "f", "submission_id": "s3", "submitted_at": _ms("2026-06-11T12:00:00Z"),
         "email": "direct@x.com"},    # no webinar record -> DIRECT
    ])
    r = _run(contacts, bofu=bofu)
    assert r.loc["bofu_submissions_total", "w0"] == 3
    assert r.loc["bofu_submissions_direct", "w0"] == 1
