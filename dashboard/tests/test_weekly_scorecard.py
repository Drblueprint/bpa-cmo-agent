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
    "typeform_submission_date", "created",
    "webinar_registration_date", "webinar_completed_date",
    "pt_webinar_registration_date", "pt_webinar_completed_date",
]


def _contacts(rows):
    df = pd.DataFrame(rows)
    for c in (["hs_id", "typeform_asset_download", "email"] + _CONTACT_DATE_COLS):
        if c not in df.columns:
            df[c] = None
    return df


WEEK = (date(2026, 6, 8), date(2026, 6, 14))


def _run(contacts, *, meetings=None, bofu=None, fb=None):
    return weekly_metrics(
        fb=fb if fb is not None else pd.DataFrame(),
        contacts=contacts,
        meetings=meetings if meetings is not None else pd.DataFrame(
            columns=["meeting_id", "contact_id", "activity_type", "outcome", "start_time"]),
        contact_deals=pd.DataFrame(columns=["contact_id", "deal_id"]),
        deals=pd.DataFrame(),
        bofu_submissions=bofu if bofu is not None else pd.DataFrame(
            columns=["form_id", "submission_id", "submitted_at", "email"]),
        week_ranges=[WEEK],
        asset_to_group={"TR": "TheraRay", "NL": "NLAP", "CH": "Chiro", "EM": "EMX",
                        "PGW": "Practice Growth Workshop", "MP": "MAP"},
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
    # submitted_at is an ISO-8601 string, matching load_form_submissions output
    # (regression guard: it used to be parsed as Unix-ms, so every BOFU was 0).
    bofu = pd.DataFrame([
        {"form_id": "f", "submission_id": "s1", "submitted_at": "2026-06-10T12:00:00Z",
         "email": "webinar@x.com"},   # has webinar -> not direct
        {"form_id": "f", "submission_id": "s2", "submitted_at": "2026-06-10T12:00:00Z",
         "email": "ptweb@x.com"},     # has PT webinar -> not direct
        {"form_id": "f", "submission_id": "s3", "submitted_at": "2026-06-11T12:00:00Z",
         "email": "direct@x.com"},    # no webinar record -> DIRECT
    ])
    r = _run(contacts, bofu=bofu)
    assert r.loc["bofu_submissions_total", "w0"] == 3
    assert r.loc["bofu_submissions_direct", "w0"] == 1


def test_chiro_ad_spend_clicks_include_all_paid_groups():
    fb = pd.DataFrame([
        {"group": "Chiro", "spend": 100.0, "inline_link_clicks": 10, "fb_leads": 5, "date_start": "2026-06-09"},
        {"group": "EMX", "spend": 50.0, "inline_link_clicks": 5, "fb_leads": 2, "date_start": "2026-06-10"},
        {"group": "TheraRay", "spend": 40.0, "inline_link_clicks": 4, "fb_leads": 1, "date_start": "2026-06-11"},
        {"group": "NLAP", "spend": 10.0, "inline_link_clicks": 1, "fb_leads": 1, "date_start": "2026-06-12"},
        {"group": "PT Recovery", "spend": 999.0, "inline_link_clicks": 99, "fb_leads": 9, "date_start": "2026-06-09"},
    ])
    r = _run(_contacts([]), fb=fb)
    assert r.loc["chiro_ad_spend", "w0"] == 200.0     # Chiro+EMX+TheraRay+NLAP; PT excluded
    assert r.loc["chiro_link_clicks", "w0"] == 20      # 10+5+4+1
    assert abs(r.loc["chiro_cpc", "w0"] - 10.0) < 1e-9  # 200/20


def test_optins_are_all_leads_new_leads_are_netnew():
    contacts = _contacts([
        # submitted in week, created earlier -> All Lead (opt-in) but NOT new
        {"hs_id": "1", "typeform_asset_download": "CH",
         "typeform_submission_date": "2026-06-09T10:00:00Z",
         "created": "2026-01-01T00:00:00Z", "email": "a@x.com"},
        # submitted + created in week -> opt-in AND new
        {"hs_id": "2", "typeform_asset_download": "CH",
         "typeform_submission_date": "2026-06-10T10:00:00Z",
         "created": "2026-06-10T09:00:00Z", "email": "b@x.com"},
        # EMX, submitted + created in week -> opt-in AND new
        {"hs_id": "3", "typeform_asset_download": "EM",
         "typeform_submission_date": "2026-06-11T10:00:00Z",
         "created": "2026-06-11T09:00:00Z", "email": "c@x.com"},
    ])
    r = _run(contacts)
    assert r.loc["chiro_lead_magnet_optins", "w0"] == 3   # all 3 submitted in week
    assert r.loc["chiro_new_leads", "w0"] == 2            # only #2 and #3 are net-new


def test_webinar_rows_filter_to_chiro_emx():
    contacts = _contacts([
        {"hs_id": "1", "typeform_asset_download": "CH",
         "webinar_registration_date": "2026-06-09T10:00:00Z",
         "webinar_completed_date": "2026-06-10T10:00:00Z", "email": "a@x.com"},
        {"hs_id": "2", "typeform_asset_download": "EM",
         "webinar_registration_date": "2026-06-10T10:00:00Z", "email": "b@x.com"},
        # TheraRay contact with a webinar date -> excluded from the generic rows
        {"hs_id": "3", "typeform_asset_download": "TR",
         "webinar_registration_date": "2026-06-11T10:00:00Z", "email": "c@x.com"},
    ])
    r = _run(contacts)
    assert r.loc["webinar_registrations", "w0"] == 2   # Chiro + EMX only; TheraRay excluded
    assert r.loc["webinar_completions", "w0"] == 1     # only #1 completed


def test_pgw_weekly_rows_and_chiro_rollin():
    fb = pd.DataFrame([
        {"group": "Practice Growth Workshop", "spend": 800.0, "inline_link_clicks": 12,
         "fb_leads": 0, "date_start": "2026-06-09"},
        {"group": "Chiro", "spend": 100.0, "inline_link_clicks": 4,
         "fb_leads": 0, "date_start": "2026-06-09"},
    ])
    contacts = _contacts([
        {"hs_id": "1", "typeform_asset_download": "PGW",
         "typeform_submission_date": "2026-06-09T10:00:00Z",
         "created": "2026-06-09T09:00:00Z", "email": "a@x.com"},
    ])
    r = _run(contacts, fb=fb)
    # standalone PGW rows
    assert r.loc["pgw_ad_spend", "w0"] == 800.0
    assert r.loc["pgw_leads", "w0"] == 1
    # rolled into the blended Chiro top-line
    assert r.loc["chiro_ad_spend", "w0"] == 900.0          # Chiro 100 + PGW 800
    assert r.loc["chiro_link_clicks", "w0"] == 16          # 4 + 12
    assert r.loc["chiro_lead_magnet_optins", "w0"] == 1    # PGW submit rolls in
    assert r.loc["chiro_new_leads", "w0"] == 1             # PGW submit+created -> net-new


def test_map_weekly_rows_and_combined_rollin():
    fb = pd.DataFrame([
        {"group": "MAP", "spend": 300.0, "inline_link_clicks": 20,
         "fb_leads": 0, "date_start": "2026-06-09"},
        {"group": "Chiro", "spend": 100.0, "inline_link_clicks": 10,
         "fb_leads": 0, "date_start": "2026-06-09"},
    ])
    contacts = _contacts([
        {"hs_id": "1", "typeform_asset_download": "MP",
         "typeform_submission_date": "2026-06-09T10:00:00Z",
         "created": "2026-06-09T09:00:00Z", "email": "a@x.com"},
    ])
    r = _run(contacts, fb=fb)
    # Standalone MAP rows
    assert r.loc["map_ad_spend", "w0"] == 300.0
    assert r.loc["map_leads", "w0"] == 1
    # MAP rolls into the combined spend/clicks/cpc
    assert r.loc["chiro_ad_spend", "w0"] == 400.0          # Chiro 100 + MAP 300
    assert r.loc["chiro_link_clicks", "w0"] == 30          # 10 + 20
    assert abs(r.loc["chiro_cpc", "w0"] - (400.0 / 30)) < 1e-9
    # MAP leads stay standalone: NOT rolled into Chiro lead rows
    assert r.loc["chiro_lead_magnet_optins", "w0"] == 0
    assert r.loc["chiro_new_leads", "w0"] == 0
