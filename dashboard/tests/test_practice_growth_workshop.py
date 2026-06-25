import pandas as pd
from dashboard.data.groups import match_group
from dashboard.config import ASSET_TO_GROUP
from dashboard.data.reconcile import group_marketing_metrics

CAMPAIGN = ("DS | __Practice Growth Workshop Dallas__ Funnel Setup | CBO | "
            "USA | CA | Images June 2026 | C1")


def test_match_group_practice_growth_workshop():
    assert match_group(CAMPAIGN) == "Practice Growth Workshop"


def test_asset_to_group_pgw_dallas():
    assert ASSET_TO_GROUP["Practice Growth Workshop Dallas"] == "Practice Growth Workshop"


def test_group_marketing_metrics_shows_spend_only_group():
    # Spend but no leads -> the group must still get a row (drives the
    # Executive "Breakdown by group" spend-only requirement).
    fb = pd.DataFrame([
        {"group": "Practice Growth Workshop", "spend": 500.0, "fb_leads": 0},
    ])
    contacts = pd.DataFrame(columns=["hs_id", "typeform_asset_download"])
    gm = group_marketing_metrics(
        fb, contacts,
        pd.DataFrame(columns=["contact_id", "deal_id"]),
        pd.DataFrame(columns=["deal_id", "dealstage", "amount"]),
        asset_to_group=ASSET_TO_GROUP,
        stages_15min_booked=set(),
        stages_strategy=set(),
        stages_closed_won=set(),
        meetings=None,
    ).set_index("group")
    assert gm.loc["Practice Growth Workshop", "spend"] == 500.0
    assert gm.loc["Practice Growth Workshop", "marketing_leads"] == 0
