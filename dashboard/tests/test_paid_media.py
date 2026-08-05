from dashboard.data.paid_media import (
    action_value, derive_metrics, LEAD_ACTION_TYPES,
    _f, first_lead_value,
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


def test_first_lead_value_prefers_pixel_lead_when_both_present():
    # FB often reports the same conversions under two action-type labels.
    # Priority order must win so the same leads are not double counted.
    actions = [{"action_type": "lead", "value": "9"},
               {"action_type": "offsite_conversion.fb_pixel_lead", "value": "4"}]
    assert first_lead_value(actions) == 4.0


def test_first_lead_value_falls_through_a_present_but_zero_type():
    # A zero on the higher-priority type is not a lead count, it is an absent
    # one. Falling through to the next type is deliberate: it is what makes
    # the function return the real count instead of 0.
    actions = [{"action_type": "offsite_conversion.fb_pixel_lead", "value": "0"},
               {"action_type": "lead", "value": "5"}]
    assert first_lead_value(actions) == 5.0


def test_f_coerces_bad_input_to_zero():
    assert _f(None) == 0.0
    assert _f("") == 0.0
    assert _f("N/A") == 0.0
    assert _f("12.5") == 12.5
    assert _f(3) == 3.0


def test_derive_metrics_does_not_mutate_its_input():
    row = {"spend": "100", "impressions": "1000",
           "inline_link_clicks": "10", "actions": []}
    before = dict(row)
    derive_metrics(row)
    assert row == before


def test_derive_metrics_all_ratio_keys_none_on_zero_denominators():
    m = derive_metrics({"spend": "0", "impressions": "0",
                        "inline_link_clicks": "0", "actions": []})
    for key in ("link_cpc", "link_ctr", "cpm_calc", "cpl",
                "cost_per_lp_view", "lp_view_to_lead",
                "hook_rate", "hold_rate"):
        assert m[key] is None, f"{key} should be None on a zero denominator"
