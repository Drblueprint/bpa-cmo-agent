"""Tests for marketing per-group aggregation."""
import pytest
import pandas as pd

from dashboard.data.reconcile import group_marketing_metrics


def test_group_marketing_metrics_basic():
    fb = pd.DataFrame([
        {"campaign_name": "DS | __Chiro__ ...", "group": "Chiro",
         "spend": 1000.0, "impressions": 50000, "clicks": 500, "fb_leads": 20},
        {"campaign_name": "DS | __PT__ ...", "group": "PT Recovery",
         "spend": 500.0, "impressions": 25000, "clicks": 250, "fb_leads": 10},
        {"campaign_name": "DS | __EMX__ ...", "group": "EMX",
         "spend": 200.0, "impressions": 8000, "clicks": 80, "fb_leads": 5},
    ])
    # 3 marketing contacts: 2 from Chiro asset, 1 PT
    # Contact 1: has call date -> booked; Contact 2: nothing; Contact 3: MQL -> booked
    contacts = pd.DataFrame([
        {"hs_id": "1", "typeform_asset_download": "Chiro Audit PDF",
         "fifteen_min_call_date": "2026-05-10T10:00:00Z", "lifecycle_stage": "subscriber"},
        {"hs_id": "2", "typeform_asset_download": "Chiro Audit PDF",
         "fifteen_min_call_date": None, "lifecycle_stage": "lead"},
        {"hs_id": "3", "typeform_asset_download": "PT Recovery Guide",
         "fifteen_min_call_date": None, "lifecycle_stage": "marketingqualifiedlead"},
    ])
    # Deal data is no longer the source of truth for calls_booked
    contact_deals = pd.DataFrame(columns=["contact_id", "deal_id"])
    deals = pd.DataFrame(columns=["deal_id", "dealstage", "amount"])
    asset_to_group = {
        "Chiro Audit PDF": "Chiro",
        "PT Recovery Guide": "PT Recovery",
    }
    hyros = pd.DataFrame([
        {"lead_id": "h1", "first_source": "FB - __Chiro__ campaign"},
        {"lead_id": "h2", "first_source": "FB - __Chiro__ campaign"},
        {"lead_id": "h3", "first_source": "FB - __PT__ campaign"},
    ])
    result = group_marketing_metrics(
        fb, contacts, contact_deals, deals,
        asset_to_group=asset_to_group,
        stages_15min_booked=set(),  # unused - calls_booked driven by contact properties
        hyros=hyros,
    )

    chiro = result[result["group"] == "Chiro"].iloc[0]
    assert chiro["spend"] == 1000.0
    assert chiro["marketing_leads"] == 2      # typeform count (source of truth)
    assert chiro["hyros_leads"] == 2          # Hyros count (diagnostic)
    assert chiro["marketing_leads_source"] == "typeform"
    assert chiro["calls_booked"] == 0         # no meetings passed → 0
    assert chiro["cpl"] == 500.0              # 1000 / 2
    assert chiro["cost_per_qualified_call"] is None


from dashboard.data.reconcile import pipeline_funnel


def test_pipeline_funnel_marketing_vs_all():
    contacts = pd.DataFrame([
        {"hs_id": "1", "typeform_asset_download": "x"},
        {"hs_id": "2", "typeform_asset_download": "y"},
    ])
    contact_deals = pd.DataFrame([
        {"contact_id": "1", "deal_id": "d1"},
        {"contact_id": "2", "deal_id": "d2"},
    ])
    deals = pd.DataFrame([
        {"deal_id": "d1", "dealstage": "15min_booked", "amount": 0},
        {"deal_id": "d2", "dealstage": "closedwon",   "amount": 5000},
        {"deal_id": "d3", "dealstage": "closedwon",   "amount": 1000},  # not marketing
    ])
    stages = {
        "15min_booked":     {"15min_booked", "15min_held"},
        "strategy_booked":  set(),
        "closedwon":        {"closedwon"},
    }

    fn = pipeline_funnel(contacts, contact_deals, deals,
                         stage_groups=stages, marketing_only=True)
    assert fn["count"].loc[fn["stage"] == "15-min Booked"].iloc[0] == 1
    assert fn["count"].loc[fn["stage"] == "Closed-Won"].iloc[0] == 1
    assert fn["revenue"].loc[fn["stage"] == "Closed-Won"].iloc[0] == 5000.0

    fn_all = pipeline_funnel(contacts, contact_deals, deals,
                              stage_groups=stages, marketing_only=False)
    assert fn_all["count"].loc[fn_all["stage"] == "Closed-Won"].iloc[0] == 2
    assert fn_all["revenue"].loc[fn_all["stage"] == "Closed-Won"].iloc[0] == 6000.0


from dashboard.data.reconcile import owner_rollup


def test_owner_rollup_by_sdr():
    contacts = pd.DataFrame([
        {"hs_id": "1", "sdr_owner": "Gage", "bds": "Scott Warren"},
        {"hs_id": "2", "sdr_owner": "Gage", "bds": "Garrett"},
        {"hs_id": "3", "sdr_owner": "Other", "bds": "Scott Warren"},
    ])
    contact_deals = pd.DataFrame([
        {"contact_id": "1", "deal_id": "d1"},
        {"contact_id": "2", "deal_id": "d2"},
        {"contact_id": "3", "deal_id": "d3"},
    ])
    deals = pd.DataFrame([
        {"deal_id": "d1", "dealstage": "15min_booked", "amount": 0},
        {"deal_id": "d2", "dealstage": "closedwon",    "amount": 5000},
        {"deal_id": "d3", "dealstage": "strategy_held", "amount": 0},
    ])
    stages = {
        "15min_booked":    {"15min_booked", "15min_held"},
        "strategy_booked": {"strategy_booked", "strategy_held"},
        "closedwon":       {"closedwon"},
    }

    by_sdr = owner_rollup(contacts, contact_deals, deals,
                          owner_field="sdr_owner", stage_groups=stages)

    gage = by_sdr[by_sdr["owner"] == "Gage"].iloc[0]
    assert gage["calls_15min"] == 1
    assert gage["closed_won"] == 1
    assert gage["closed_won_revenue"] == 5000.0


from dashboard.data.reconcile import reconciliation_panel


def test_reconciliation_panel_basic():
    fb = pd.DataFrame([
        {"campaign_name": "DS | __Chiro__ ...", "group": "Chiro",
         "spend": 1000.0, "fb_leads": 20},
        {"campaign_name": "DS | __PT__ ...", "group": "PT Recovery",
         "spend": 500.0, "fb_leads": 10},
    ])
    # HubSpot: 3 Chiro leads (from Chiro Audit PDF), 1 PT lead
    contacts = pd.DataFrame([
        {"hs_id": "1", "typeform_asset_download": "Chiro Audit PDF"},
        {"hs_id": "2", "typeform_asset_download": "Chiro Audit PDF"},
        {"hs_id": "3", "typeform_asset_download": "Chiro Audit PDF"},
        {"hs_id": "4", "typeform_asset_download": "PT Recovery Guide"},
    ])
    # Hyros: 2 leads from a Chiro campaign source, 0 PT
    hyros = pd.DataFrame([
        {"lead_id": "h1", "first_source": "FB - __Chiro__ campaign"},
        {"lead_id": "h2", "first_source": "FB - __Chiro__ campaign"},
    ])
    asset_to_group = {
        "Chiro Audit PDF": "Chiro",
        "PT Recovery Guide": "PT Recovery",
    }

    result = reconciliation_panel(fb, contacts, hyros,
                                   asset_to_group=asset_to_group)

    # Verify expected columns
    assert set(result.columns) == {"group", "fb_leads", "hyros_leads",
                                    "hubspot_leads", "match_rate"}

    # Chiro: FB=20, Hyros=2, HubSpot=3 → match_rate = min(2,3)/3 ≈ 0.667
    chiro = result[result["group"] == "Chiro"].iloc[0]
    assert chiro["fb_leads"] == 20
    assert chiro["hyros_leads"] == 2
    assert chiro["hubspot_leads"] == 3
    assert abs(chiro["match_rate"] - (2/3)) < 1e-9

    # PT Recovery: FB=10, Hyros=0, HubSpot=1 → match_rate = 0/1 = 0.0
    pt = result[result["group"] == "PT Recovery"].iloc[0]
    assert pt["fb_leads"] == 10
    assert pt["hyros_leads"] == 0
    assert pt["hubspot_leads"] == 1
    assert pt["match_rate"] == 0.0


def test_group_marketing_metrics_empty_contact_deals():
    """Empty contact_deals and no call-date properties must not crash."""
    fb = pd.DataFrame([
        {"campaign_name": "DS | __Chiro__ ...", "group": "Chiro",
         "spend": 1000.0, "impressions": 0, "clicks": 0, "fb_leads": 0},
    ])
    contacts = pd.DataFrame([
        {"hs_id": "1", "typeform_asset_download": "Chiro Audit PDF",
         "fifteen_min_call_date": None, "lifecycle_stage": "lead"},
    ])
    contact_deals = pd.DataFrame(columns=["contact_id", "deal_id"])
    deals = pd.DataFrame(columns=["deal_id", "dealstage", "amount"])

    result = group_marketing_metrics(
        fb, contacts, contact_deals, deals,
        asset_to_group={"Chiro Audit PDF": "Chiro"},
        stages_15min_booked={"15min_booked"},
        hyros=pd.DataFrame(),
    )

    chiro = result[result["group"] == "Chiro"].iloc[0]
    assert chiro["marketing_leads"] == 1      # typeform = 1, no fallback needed
    assert chiro["hyros_leads"] == 0
    assert chiro["marketing_leads_source"] == "typeform"
    assert chiro["calls_booked"] == 0
    assert chiro["cpl"] == 1000.0             # spend 1000 / 1
    assert chiro["cost_per_qualified_call"] is None


def test_reconciliation_panel_empty_hyros():
    """Hyros may return zero rows; the panel should still render the other sources."""
    fb = pd.DataFrame([
        {"campaign_name": "DS | __Chiro__ ...", "group": "Chiro",
         "spend": 1000.0, "fb_leads": 5},
    ])
    contacts = pd.DataFrame([
        {"hs_id": "1", "typeform_asset_download": "Chiro Audit PDF"},
    ])
    hyros = pd.DataFrame()  # empty

    result = reconciliation_panel(fb, contacts, hyros,
                                   asset_to_group={"Chiro Audit PDF": "Chiro"})
    chiro = result[result["group"] == "Chiro"].iloc[0]
    assert chiro["hyros_leads"] == 0
    assert chiro["hubspot_leads"] == 1


def test_owner_rollup_empty_contact_deals():
    """No matching deals → empty result with columns intact, no sort crash."""
    contacts = pd.DataFrame([
        {"hs_id": "1", "sdr_owner": "Gage", "bds": "Scott Warren"},
    ])
    contact_deals = pd.DataFrame(columns=["contact_id", "deal_id"])
    deals = pd.DataFrame(columns=["deal_id", "dealstage", "amount"])
    stages = {
        "15min_booked":    {"15min_booked"},
        "strategy_booked": {"strategy_booked"},
        "closedwon":       {"closedwon"},
    }
    result = owner_rollup(contacts, contact_deals, deals,
                          owner_field="sdr_owner", stage_groups=stages)
    # Must have the column even if zero rows
    assert "closed_won_revenue" in result.columns


def test_group_marketing_metrics_uses_meetings_for_calls_booked():
    """A contact with a '15 min call' meeting counts as booked."""
    fb = pd.DataFrame([
        {"campaign_name": "DS | __Chiro__ ...", "group": "Chiro",
         "spend": 100.0, "impressions": 1000, "clicks": 10, "fb_leads": 5},
    ])
    contacts = pd.DataFrame([
        {"hs_id": "1", "typeform_asset_download": "Chiro PDF",
         "fifteen_min_call_date": None, "lifecycle_stage": "lead"},
        {"hs_id": "2", "typeform_asset_download": "Chiro PDF",
         "fifteen_min_call_date": None, "lifecycle_stage": "lead"},
        {"hs_id": "3", "typeform_asset_download": "Chiro PDF",
         "fifteen_min_call_date": None, "lifecycle_stage": "lead"},
    ])
    meetings = pd.DataFrame([
        {"meeting_id": "m1", "contact_id": "1", "activity_type": "15 min call",
         "outcome": "COMPLETE - QUALIFIED", "start_time": ""},
        {"meeting_id": "m2", "contact_id": "2", "activity_type": "15 min call",
         "outcome": "SCHEDULED", "start_time": ""},
    ])
    contact_deals = pd.DataFrame(columns=["contact_id", "deal_id"])
    deals = pd.DataFrame(columns=["deal_id", "dealstage", "amount"])

    result = group_marketing_metrics(
        fb, contacts, contact_deals, deals,
        asset_to_group={"Chiro PDF": "Chiro"},
        stages_15min_booked=set(),
        meetings=meetings,
    )
    chiro = result[result["group"] == "Chiro"].iloc[0]
    assert chiro["marketing_leads"] == 3
    assert chiro["hyros_leads"] == 0
    assert chiro["marketing_leads_source"] == "typeform"
    # 2 contacts have 15-min meetings (m1 and m2) → calls_booked == 2
    assert chiro["calls_booked"] == 2


def test_group_marketing_metrics_fb_fallback_when_no_typeform():
    """When typeform is also zero for a group (e.g. TheraRay), FB lead count is used."""
    fb = pd.DataFrame([
        {"campaign_name": "DS | __Theraray__ ...", "group": "TheraRay",
         "spend": 500.0, "impressions": 5000, "clicks": 50, "fb_leads": 17},
    ])
    contacts = pd.DataFrame([], columns=[
        "hs_id", "typeform_asset_download", "fifteen_min_call_date", "lifecycle_stage",
    ])
    contact_deals = pd.DataFrame(columns=["contact_id", "deal_id"])
    deals = pd.DataFrame(columns=["deal_id", "dealstage", "amount"])
    hyros = pd.DataFrame(columns=["lead_id", "first_source"])  # empty Hyros

    result = group_marketing_metrics(
        fb, contacts, contact_deals, deals,
        asset_to_group={},
        stages_15min_booked=set(),
        hyros=hyros,
    )
    theraray = result[result["group"] == "TheraRay"].iloc[0]
    assert theraray["marketing_leads"] == 17           # FB fallback (typeform = 0)
    assert theraray["marketing_leads_source"] == "fb"
    assert theraray["cpl"] == 500.0 / 17               # uses fallback denominator


def test_per_contact_journey_handles_canceled_and_pt_variant():
    """Canceled meetings -> 'Canceled' status; 'PT 15 Min Call' matches as 15-min."""
    from dashboard.data.reconcile import per_contact_journey

    contacts = pd.DataFrame([
        {"hs_id": "1", "fifteen_min_call_date": None, "lifecycle_stage": "lead"},
        {"hs_id": "2", "fifteen_min_call_date": None, "lifecycle_stage": "lead"},
    ])
    meetings = pd.DataFrame([
        # Contact 1: PT variant, canceled
        {"meeting_id": "m1", "contact_id": "1", "activity_type": "PT 15 Min Call",
         "outcome": "CANCELED", "start_time": ""},
        # Contact 2: completed Strategy Call, plus a canceled 15-min - priority Completed for Strategy
        {"meeting_id": "m2", "contact_id": "2", "activity_type": "Strategy Call",
         "outcome": "COMPLETE - QUALIFIED", "start_time": ""},
        {"meeting_id": "m3", "contact_id": "2", "activity_type": "15 min call",
         "outcome": "CANCELED", "start_time": ""},
    ])
    contact_deals = pd.DataFrame(columns=["contact_id", "deal_id"])
    deals = pd.DataFrame(columns=["deal_id", "dealstage", "amount"])

    result = per_contact_journey(
        contacts, meetings, contact_deals, deals,
        stages_closed_won=set(),
    )
    by_id = {row["hs_id"]: row for _, row in result.iterrows()}
    assert by_id["1"]["fifteen_min_status"] == "Canceled"
    assert by_id["1"]["strategy_status"] == ""
    # Contact 2: a canceled 15-min still shows as Canceled (no Scheduled/Completed 15-min)
    assert by_id["2"]["fifteen_min_status"] == "Canceled"
    assert by_id["2"]["strategy_status"] == "Completed"


def test_per_contact_journey_no_show_status():
    """NO_SHOW outcome surfaces as 'No Show', distinct from Canceled."""
    from dashboard.data.reconcile import per_contact_journey
    contacts = pd.DataFrame([{"hs_id": "1", "fifteen_min_call_date": None,
                              "lifecycle_stage": "lead"}])
    meetings = pd.DataFrame([
        {"meeting_id": "m1", "contact_id": "1", "activity_type": "Strategy Call",
         "outcome": "NO_SHOW", "start_time": ""},
    ])
    result = per_contact_journey(
        contacts, meetings,
        pd.DataFrame(columns=["contact_id", "deal_id"]),
        pd.DataFrame(columns=["deal_id", "dealstage", "amount"]),
        stages_closed_won=set(),
    )
    assert result.iloc[0]["strategy_status"] == "No Show"


def test_per_contact_journey_outcome_variants():
    """Outcome suffix variants are caught via prefix matching."""
    from dashboard.data.reconcile import per_contact_journey
    contacts = pd.DataFrame([
        {"hs_id": "1", "fifteen_min_call_date": None, "lifecycle_stage": "lead"},
        {"hs_id": "2", "fifteen_min_call_date": None, "lifecycle_stage": "lead"},
    ])
    meetings = pd.DataFrame([
        {"meeting_id": "m1", "contact_id": "1", "activity_type": "Strategy Call",
         "outcome": "CANCELLED - BY BPA", "start_time": ""},
        {"meeting_id": "m2", "contact_id": "2", "activity_type": "Strategy Call",
         "outcome": "RESCHEDULED - NO BOFU", "start_time": ""},
    ])
    result = per_contact_journey(
        contacts, meetings,
        pd.DataFrame(columns=["contact_id", "deal_id"]),
        pd.DataFrame(columns=["deal_id", "dealstage", "amount"]),
        stages_closed_won=set(),
    )
    by_id = {row["hs_id"]: row for _, row in result.iterrows()}
    assert by_id["1"]["strategy_status"] == "Canceled"   # variant suffix matched
    assert by_id["2"]["strategy_status"] == "Scheduled"  # rescheduled → still scheduled


def test_per_contact_journey_priority_completed_over_canceled():
    """A contact with both Completed and Canceled Strategy meetings shows Completed."""
    from dashboard.data.reconcile import per_contact_journey
    contacts = pd.DataFrame([{"hs_id": "1", "fifteen_min_call_date": None,
                              "lifecycle_stage": "lead"}])
    meetings = pd.DataFrame([
        {"meeting_id": "m1", "contact_id": "1", "activity_type": "Strategy Call",
         "outcome": "COMPLETE - QUALIFIED", "start_time": "2026-05-01T00:00:00Z"},
        {"meeting_id": "m2", "contact_id": "1", "activity_type": "Strategy Call",
         "outcome": "CANCELED", "start_time": "2026-05-10T00:00:00Z"},
    ])
    result = per_contact_journey(
        contacts, meetings,
        pd.DataFrame(columns=["contact_id", "deal_id"]),
        pd.DataFrame(columns=["deal_id", "dealstage", "amount"]),
        stages_closed_won=set(),
    )
    assert result.iloc[0]["strategy_status"] == "Completed"


def test_executive_kpis_all_groups_basic():
    """Returns the 15 KPI values aggregated across all groups."""
    from dashboard.data.reconcile import executive_kpis

    fb = pd.DataFrame([
        {"campaign_name": "DS | __Chiro__", "group": "Chiro",
         "spend": 6750.0, "impressions": 50000, "clicks": 500, "fb_leads": 24},
        {"campaign_name": "DS | __PT__", "group": "PT Recovery",
         "spend": 1136.0, "impressions": 25000, "clicks": 250, "fb_leads": 12},
    ])
    contacts = pd.DataFrame([
        {"hs_id": "1", "typeform_asset_download": "Top 10 typeform",
         "lifecycle_stage": "marketingqualifiedlead",
         "fifteen_min_call_date": "2026-05-10T10:00:00Z",
         "sdr_owner": "89638769", "bds": "44815718",
         "typeform_submission_date": "2026-05-09T00:00:00Z",
         "createdate": "2026-05-09T00:00:00Z"},
        {"hs_id": "2", "typeform_asset_download": "Top 10 typeform",
         "lifecycle_stage": "lead",
         "fifteen_min_call_date": None,
         "sdr_owner": "89638769", "bds": "44815718",
         "typeform_submission_date": "2026-05-10T00:00:00Z",
         "createdate": "2026-05-10T00:00:00Z"},
        {"hs_id": "3", "typeform_asset_download": "Recovery Program (PT) typeform",
         "lifecycle_stage": "salesqualifiedlead",
         "fifteen_min_call_date": "2026-05-11T10:00:00Z",
         "sdr_owner": "79870794", "bds": "44815718",
         "typeform_submission_date": "2026-05-11T00:00:00Z",
         "createdate": "2026-05-11T00:00:00Z"},
    ])
    meetings = pd.DataFrame([
        {"meeting_id": "m1", "contact_id": "1", "activity_type": "15 min call",
         "outcome": "COMPLETE - QUALIFIED", "start_time": "2026-05-10T10:00:00Z"},
        {"meeting_id": "m2", "contact_id": "1", "activity_type": "Strategy Call",
         "outcome": "COMPLETE - QUALIFIED", "start_time": "2026-05-12T10:00:00Z"},
        {"meeting_id": "m3", "contact_id": "3", "activity_type": "PT 15 Min Call",
         "outcome": "SCHEDULED", "start_time": "2026-05-15T10:00:00Z"},
    ])
    contact_deals = pd.DataFrame([
        {"contact_id": "1", "deal_id": "d1"},
    ])
    deals = pd.DataFrame([
        {"deal_id": "d1", "dealstage": "closedwon", "amount": 47928.0,
         "createdate": "2026-05-09T00:00:00Z", "closedate": "2026-05-15T00:00:00Z"},
    ])

    result = executive_kpis(
        fb=fb, contacts=contacts, meetings=meetings,
        contact_deals=contact_deals, deals=deals,
        group_filter="All",
        asset_to_group={"Top 10 typeform": "Chiro",
                        "Recovery Program (PT) typeform": "PT Recovery"},
        group_default_amount={"Chiro": 47928.0, "PT Recovery": 23928.0},
        stages_closed_won={"closedwon"},
        sdr_payroll_monthly=None,
        sme_payroll_monthly=None,
    )

    # Row 1 inputs
    assert result["total_ad_spend"] == 7886.0           # 6750 + 1136
    assert result["new_leads"] == 3                      # 3 contacts with typeform
    assert result["engaged_leads"] == 2                  # MQL (1) + SQL (3)
    assert result["cpl"] == pytest.approx(7886.0 / 3)
    assert result["cost_per_engaged_lead"] == pytest.approx(7886.0 / 2)

    # Row 2 conversions
    assert result["discovery_booked"] == 2               # contacts 1, 3 have 15-min meetings
    assert result["discovery_held"] == 1                 # contact 1 (COMPLETE)
    assert result["sme_booked"] == 1                     # contact 1 has Strategy meeting
    assert result["sme_held"] == 1                       # contact 1 (COMPLETE)
    assert result["closed_won"] == 1                     # 1 closed deal

    # Row 3 money
    assert result["new_revenue"] == 47928.0
    assert result["avg_deal_size"] == 47928.0
    assert result["cac_ad_only"] == 7886.0               # 7886 / 1


def test_executive_kpis_group_filter():
    """Group filter restricts every metric to the selected group only."""
    from dashboard.data.reconcile import executive_kpis

    fb = pd.DataFrame([
        {"campaign_name": "DS | __Chiro__", "group": "Chiro",
         "spend": 1000.0, "impressions": 0, "clicks": 0, "fb_leads": 5},
        {"campaign_name": "DS | __PT__", "group": "PT Recovery",
         "spend": 2000.0, "impressions": 0, "clicks": 0, "fb_leads": 10},
    ])
    contacts = pd.DataFrame([
        {"hs_id": "1", "typeform_asset_download": "Chiro asset",
         "lifecycle_stage": "lead", "fifteen_min_call_date": None,
         "sdr_owner": "x", "bds": "y",
         "typeform_submission_date": "2026-05-10T00:00:00Z",
         "createdate": "2026-05-10T00:00:00Z"},
        {"hs_id": "2", "typeform_asset_download": "PT asset",
         "lifecycle_stage": "lead", "fifteen_min_call_date": None,
         "sdr_owner": "x", "bds": "y",
         "typeform_submission_date": "2026-05-10T00:00:00Z",
         "createdate": "2026-05-10T00:00:00Z"},
    ])

    result = executive_kpis(
        fb=fb, contacts=contacts,
        meetings=pd.DataFrame(columns=["meeting_id","contact_id","activity_type","outcome","start_time"]),
        contact_deals=pd.DataFrame(columns=["contact_id","deal_id"]),
        deals=pd.DataFrame(columns=["deal_id","dealstage","amount","createdate","closedate"]),
        group_filter="Chiro",
        asset_to_group={"Chiro asset": "Chiro", "PT asset": "PT Recovery"},
        group_default_amount={"Chiro": 47928.0, "PT Recovery": 23928.0},
        stages_closed_won=set(),
        sdr_payroll_monthly=None,
        sme_payroll_monthly=None,
    )

    assert result["total_ad_spend"] == 1000.0    # only Chiro spend
    assert result["new_leads"] == 1              # only Chiro contact


def test_executive_kpis_revenue_fallback_option_c():
    """If a closed-won deal has zero/missing amount, use the group default."""
    from dashboard.data.reconcile import executive_kpis

    fb = pd.DataFrame([
        {"campaign_name": "DS | __Chiro__", "group": "Chiro",
         "spend": 1000.0, "impressions": 0, "clicks": 0, "fb_leads": 0},
    ])
    contacts = pd.DataFrame([
        {"hs_id": "1", "typeform_asset_download": "Chiro asset",
         "lifecycle_stage": "customer", "fifteen_min_call_date": None,
         "sdr_owner": "x", "bds": "y",
         "typeform_submission_date": "2026-05-10T00:00:00Z",
         "createdate": "2026-05-10T00:00:00Z"},
    ])
    contact_deals = pd.DataFrame([{"contact_id": "1", "deal_id": "d1"}])
    deals = pd.DataFrame([
        {"deal_id": "d1", "dealstage": "closedwon", "amount": 0,  # missing
         "createdate": "2026-05-10T00:00:00Z", "closedate": "2026-05-15T00:00:00Z"},
    ])

    result = executive_kpis(
        fb=fb, contacts=contacts,
        meetings=pd.DataFrame(columns=["meeting_id","contact_id","activity_type","outcome","start_time"]),
        contact_deals=contact_deals, deals=deals,
        group_filter="All",
        asset_to_group={"Chiro asset": "Chiro"},
        group_default_amount={"Chiro": 47928.0},
        stages_closed_won={"closedwon"},
        sdr_payroll_monthly=None,
        sme_payroll_monthly=None,
    )

    assert result["new_revenue"] == 47928.0   # Option C fallback fired


def test_executive_sdr_rollup_basic():
    """Per-SDR table: leads worked, discovery booked, schedule %, held, show %."""
    from dashboard.data.reconcile import executive_sdr_rollup

    contacts = pd.DataFrame([
        {"hs_id": "1", "sdr_owner": "89638769"},   # Peyton
        {"hs_id": "2", "sdr_owner": "89638769"},   # Peyton
        {"hs_id": "3", "sdr_owner": "79870794"},   # Garrett
    ])
    meetings = pd.DataFrame([
        {"meeting_id": "m1", "contact_id": "1", "activity_type": "15 min call",
         "outcome": "COMPLETE - QUALIFIED", "start_time": ""},
        {"meeting_id": "m2", "contact_id": "3", "activity_type": "15 min call",
         "outcome": "SCHEDULED", "start_time": ""},
    ])

    result = executive_sdr_rollup(contacts, meetings)

    by_id = {row["sdr_id"]: row for _, row in result.iterrows()}
    peyton = by_id["89638769"]
    assert peyton["leads_worked"] == 2
    assert peyton["discovery_booked"] == 1
    assert peyton["discovery_held"] == 1
    # Schedule rate = 1/2 = 0.5; show rate = 1/1 = 1.0
    assert peyton["schedule_rate"] == 0.5
    assert peyton["show_rate"] == 1.0


def test_executive_sme_rollup_basic():
    """Per-SME table: calls held, deals closed, close %, revenue, revenue/call."""
    from dashboard.data.reconcile import executive_sme_rollup

    contacts = pd.DataFrame([
        {"hs_id": "1", "bds": "44815718", "typeform_asset_download": "Chiro asset"},
        {"hs_id": "2", "bds": "44815718", "typeform_asset_download": "Chiro asset"},
    ])
    meetings = pd.DataFrame([
        {"meeting_id": "m1", "contact_id": "1", "activity_type": "Strategy Call",
         "outcome": "COMPLETE - QUALIFIED", "start_time": ""},
        {"meeting_id": "m2", "contact_id": "2", "activity_type": "Strategy Call",
         "outcome": "COMPLETE - QUALIFIED", "start_time": ""},
    ])
    contact_deals = pd.DataFrame([{"contact_id": "1", "deal_id": "d1"}])
    deals = pd.DataFrame([
        {"deal_id": "d1", "dealstage": "closedwon", "amount": 47928.0,
         "createdate": "", "closedate": ""},
    ])
    result = executive_sme_rollup(
        contacts, meetings, contact_deals, deals,
        asset_to_group={"Chiro asset": "Chiro"},
        group_default_amount={"Chiro": 47928.0},
        stages_closed_won={"closedwon"},
    )

    by_id = {row["sme_id"]: row for _, row in result.iterrows()}
    scott = by_id["44815718"]
    assert scott["sme_calls_held"] == 2
    assert scott["deals_closed"] == 1
    assert scott["close_rate"] == 0.5
    assert scott["revenue"] == 47928.0
    assert scott["revenue_per_call"] == pytest.approx(47928.0 / 2)
