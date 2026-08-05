from dashboard.data.paid_media import (
    action_value, derive_metrics, LEAD_ACTION_TYPES,
)


def test_action_value_finds_matching_type():
    actions = [{"action_type": "lead", "value": "7"},
               {"action_type": "landing_page_view", "value": "42"}]
    assert action_value(actions, "lead") == 7.0
    assert action_value(actions, "landing_page_view") == 42.0


def test_action_value_missing_type_is_zero():
    assert action_value([{"action_type": "lead", "value": "3"}], "purchase") == 0.0
    assert action_value(None, "lead") == 0.0
    assert action_value([], "lead") == 0.0


def test_derive_metrics_computes_link_cpc_and_ctr():
    row = {"spend": "100", "impressions": "10000",
           "clicks": "200", "inline_link_clicks": "50", "actions": []}
    m = derive_metrics(row)
    assert m["link_cpc"] == 2.0            # 100 / 50
    assert m["link_ctr"] == 0.005          # 50 / 10000
    assert m["cpm_calc"] == 10.0           # 100 / 10000 * 1000


def test_derive_metrics_cpl_uses_first_available_lead_action():
    row = {"spend": "200", "impressions": "1000", "inline_link_clicks": "10",
           "actions": [{"action_type": "offsite_conversion.fb_pixel_lead",
                        "value": "4"}]}
    m = derive_metrics(row)
    assert m["fb_leads"] == 4.0
    assert m["cpl"] == 50.0


def test_derive_metrics_hook_and_hold_rate():
    row = {"spend": "10", "impressions": "1000", "inline_link_clicks": "1",
           "actions": [],
           "video_3_sec_watched_actions": [{"action_type": "video_view",
                                           "value": "300"}],
           "video_thruplay_watched_actions": [{"action_type": "video_view",
                                              "value": "90"}]}
    m = derive_metrics(row)
    assert m["hook_rate"] == 0.3           # 300 / 1000
    assert m["hold_rate"] == 0.3           # 90 / 300


def test_derive_metrics_zero_denominators_are_none_not_crash():
    row = {"spend": "0", "impressions": "0", "inline_link_clicks": "0",
           "actions": []}
    m = derive_metrics(row)
    assert m["link_cpc"] is None
    assert m["link_ctr"] is None
    assert m["cpl"] is None
    assert m["hook_rate"] is None
    assert m["hold_rate"] is None


def test_lead_action_types_prefers_pixel_lead_first():
    assert LEAD_ACTION_TYPES[0] == "offsite_conversion.fb_pixel_lead"
    assert "lead" in LEAD_ACTION_TYPES
