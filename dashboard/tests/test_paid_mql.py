"""Tests for the PAID MEDIA tab's pure rollup logic."""
import pytest

from dashboard.data.paid_mql import resolve_segment

ROLLUP = {"EMX": "Event", "Practice Growth Workshop": "Event"}


@pytest.mark.parametrize("campaign,expected", [
    ("DS | EMX 2026 Kansas City Mixed Funnel Setup", "Event"),
    ("DS | __Practice Growth Workshop Dallas__ Funnel Setup", "Event"),
    ("DS | __Chiro__ Mixed Funnel Setup | CBO | USA", "Chiro"),
    ("DS | __NLAP__ Funnel Setup | CBO | USA", "NLAP"),
    ("DS | __Theraray__ Funnel Setup | CBO | USA", "TheraRay"),
    ("DS | MAP Protocol Funnel Setup | CBO | USA", "MAP"),
])
def test_resolve_segment(campaign, expected):
    assert resolve_segment(campaign, segment_rollup=ROLLUP) == expected


def test_unrecognized_campaign_is_flagged_not_dropped():
    """A new campaign whose name we do not recognize must surface as a
    tripwire row. Silently dropping it is how MAP spend went unreported."""
    assert resolve_segment("Brand New Thing 2027",
                           segment_rollup=ROLLUP) == "(unmatched)"


def test_empty_campaign_name_is_unmatched():
    assert resolve_segment("", segment_rollup=ROLLUP) == "(unmatched)"
    assert resolve_segment(None, segment_rollup=ROLLUP) == "(unmatched)"


def test_nan_campaign_name_is_unmatched():
    """Ruling P7: pandas NaN in campaign_name must resolve to unmatched,
    not raise inside match_group. This happens when feeding a DataFrame column
    through .apply(resolve_segment, ...)."""
    import math
    assert resolve_segment(math.nan, segment_rollup=ROLLUP) == "(unmatched)"


import pandas as pd

from dashboard.data.paid_mql import daily_mql_summary


def _fb(rows):
    return pd.DataFrame(rows, columns=["date_start", "campaign_name", "spend"])


def _leads(rows):
    return pd.DataFrame(rows, columns=["email", "lead_date", "segment"])


def _mqls(rows):
    return pd.DataFrame(rows, columns=["email", "mql_date", "segment"])


CHIRO = "DS | __Chiro__ Mixed Funnel Setup | CBO | USA"


def test_daily_summary_is_activity_dated():
    """A lead arriving 08-20 that becomes an MQL on 08-24 counts on TWO
    different rows. This is the whole point of activity dating: each day's
    row stops moving once the day has passed."""
    out = daily_mql_summary(
        _fb([("2026-08-20", CHIRO, 100.0), ("2026-08-24", CHIRO, 50.0)]),
        _leads([("a@x.com", "2026-08-20", "Chiro")]),
        _mqls([("a@x.com", "2026-08-24", "Chiro")]),
        segment_rollup=ROLLUP,
    )
    rows = out[out["date"] != "Total"].set_index("date")
    assert rows.loc["2026-08-20", "leads"] == 1
    assert rows.loc["2026-08-20", "callable_mql"] == 0
    assert rows.loc["2026-08-24", "leads"] == 0
    assert rows.loc["2026-08-24", "callable_mql"] == 1


def test_daily_summary_costs():
    out = daily_mql_summary(
        _fb([("2026-08-20", CHIRO, 200.0)]),
        _leads([("a@x.com", "2026-08-20", "Chiro"),
                ("b@x.com", "2026-08-20", "Chiro")]),
        _mqls([("a@x.com", "2026-08-20", "Chiro")]),
        segment_rollup=ROLLUP,
    )
    row = out[out["date"] == "2026-08-20"].iloc[0]
    assert row["cost_per_lead"] == 100.0
    assert row["cost_per_callable_mql"] == 200.0
    assert row["lead_to_callable_pct"] == 0.5


def test_daily_summary_zero_denominator_is_none_not_zero():
    """Spend with no leads must render as a dash, not as $0.00, which would
    read as free leads."""
    out = daily_mql_summary(
        _fb([("2026-08-20", CHIRO, 200.0)]),
        _leads([]), _mqls([]), segment_rollup=ROLLUP,
    )
    row = out[out["date"] == "2026-08-20"].iloc[0]
    assert row["cost_per_lead"] is None
    assert row["cost_per_callable_mql"] is None
    assert row["lead_to_callable_pct"] is None


def test_daily_summary_total_row():
    out = daily_mql_summary(
        _fb([("2026-08-20", CHIRO, 100.0), ("2026-08-21", CHIRO, 300.0)]),
        _leads([("a@x.com", "2026-08-20", "Chiro"),
                ("b@x.com", "2026-08-21", "Chiro")]),
        _mqls([("a@x.com", "2026-08-20", "Chiro")]),
        segment_rollup=ROLLUP,
    )
    total = out[out["date"] == "Total"].iloc[0]
    assert total["leads"] == 2
    assert total["callable_mql"] == 1
    assert total["cost_per_lead"] == 200.0
    # Total ratios are computed from totals, NOT averaged across rows.
    assert total["cost_per_callable_mql"] == 400.0


def test_daily_summary_segment_filter():
    out = daily_mql_summary(
        _fb([("2026-08-20", CHIRO, 100.0),
             ("2026-08-20", "DS | __NLAP__ Funnel Setup", 900.0)]),
        _leads([("a@x.com", "2026-08-20", "Chiro"),
                ("n@x.com", "2026-08-20", "NLAP")]),
        _mqls([]), segment_rollup=ROLLUP, segments=("Chiro",),
    )
    row = out[out["date"] == "2026-08-20"].iloc[0]
    assert row["leads"] == 1
    assert row["cost_per_lead"] == 100.0


def test_daily_summary_row_per_calendar_day_sorted():
    out = daily_mql_summary(
        _fb([("2026-08-21", CHIRO, 10.0), ("2026-08-20", CHIRO, 10.0)]),
        _leads([]), _mqls([]), segment_rollup=ROLLUP,
    )
    dates = [d for d in out["date"] if d != "Total"]
    assert dates == ["2026-08-20", "2026-08-21"]
    assert out["date"].iloc[-1] == "Total"


def test_daily_summary_none_preserved_in_mixed_frame():
    """Ruling P8: None values must survive DataFrame construction even when
    mixed with floats. This is the normal multi-day case: day 1 has a ratio,
    day 2 has no leads so cost_per_lead is None.

    Without _frame_preserving_none, pandas coerces the column to float64
    and silently rewrites None as NaN, breaking `is None` checks in callers.
    """
    out = daily_mql_summary(
        _fb([("2026-08-20", CHIRO, 100.0), ("2026-08-21", CHIRO, 100.0)]),
        _leads([("a@x.com", "2026-08-20", "Chiro")]),
        _mqls([]), segment_rollup=ROLLUP,
    )
    day1 = out[out["date"] == "2026-08-20"].iloc[0]
    day2 = out[out["date"] == "2026-08-21"].iloc[0]

    # Day 1 has leads, so cost_per_lead is a real float.
    assert day1["cost_per_lead"] == 100.0
    assert isinstance(day1["cost_per_lead"], float)

    # Day 2 has no leads, so cost_per_lead is None, not NaN.
    assert day2["cost_per_lead"] is None

    # Ratio columns are object dtype to preserve None.
    assert out["cost_per_lead"].dtype == object
    assert out["cost_per_callable_mql"].dtype == object
    assert out["lead_to_callable_pct"].dtype == object


from dashboard.data.paid_mql import segment_results

NLAP = "DS | __NLAP__ Funnel Setup | CBO | USA"


def _seg_fb(rows):
    return pd.DataFrame(rows, columns=["campaign_name", "spend"])


def _seg_leads(rows):
    return pd.DataFrame(rows, columns=["email", "segment"])


def test_segment_results_full_funnel():
    out = segment_results(
        _seg_fb([(CHIRO, 1000.0)]),
        _seg_leads([("a@x.com", "Chiro"), ("b@x.com", "Chiro"),
                    ("c@x.com", "Chiro"), ("d@x.com", "Chiro")]),
        mql_emails={"a@x.com", "b@x.com"},
        call_emails={"a@x.com"},
        sale_emails={"a@x.com"},
        commissions_by_segment={"Chiro": 2500.0},
        segment_rollup=ROLLUP,
    )
    row = out[out["segment"] == "Chiro"].iloc[0]
    assert row["spend"] == 1000.0
    assert row["leads"] == 4
    assert row["callable_mql"] == 2
    assert row["calls"] == 1
    assert row["sales"] == 1
    assert row["lead_to_callable_pct"] == 0.5
    assert row["callable_to_call_pct"] == 0.5
    assert row["call_to_sale_pct"] == 1.0
    assert row["cost_cmql"] == 500.0
    assert row["cost_per_call"] == 1000.0
    assert row["cost_per_close"] == 1000.0
    # Segment CAC = (spend + commissions) / sales, mirroring blended_cac.
    assert row["segment_cac"] == 3500.0


def test_segment_results_event_rollup():
    """EMX and Practice Growth Workshop collapse into one Event row."""
    out = segment_results(
        _seg_fb([("DS | EMX 2026 Kansas City", 700.0),
                 ("DS | __Practice Growth Workshop Dallas__", 300.0)]),
        _seg_leads([("a@x.com", "Event")]),
        mql_emails=set(), call_emails=set(), sale_emails=set(),
        commissions_by_segment={}, segment_rollup=ROLLUP,
    )
    segs = set(out["segment"])
    assert "Event" in segs
    assert "EMX" not in segs and "Practice Growth Workshop" not in segs
    assert out[out["segment"] == "Event"].iloc[0]["spend"] == 1000.0


def test_segment_results_spend_only_segment_still_appears():
    """A segment that spent money but produced no leads must show up with a
    dash, not be dropped. Vanishing is how MAP stayed invisible."""
    out = segment_results(
        _seg_fb([(NLAP, 5000.0)]), _seg_leads([]),
        mql_emails=set(), call_emails=set(), sale_emails=set(),
        commissions_by_segment={}, segment_rollup=ROLLUP,
    )
    row = out[out["segment"] == "NLAP"].iloc[0]
    assert row["spend"] == 5000.0
    assert row["leads"] == 0
    assert row["cost_cmql"] is None
    assert row["cost_per_close"] is None


def test_segment_results_zero_spend_segment_is_omitted():
    """PT Recovery has spent $0 for 60 days. It should not clutter the table,
    but it must reappear automatically if spend resumes."""
    out = segment_results(
        _seg_fb([(CHIRO, 100.0), ("DS | __PT__ Recovery", 0.0)]),
        _seg_leads([]), mql_emails=set(), call_emails=set(),
        sale_emails=set(), commissions_by_segment={}, segment_rollup=ROLLUP,
    )
    assert "PT Recovery" not in set(out["segment"])


def test_segment_results_total_row_uses_totals_not_averages():
    out = segment_results(
        _seg_fb([(CHIRO, 1000.0), (NLAP, 3000.0)]),
        _seg_leads([("a@x.com", "Chiro"), ("n@x.com", "NLAP")]),
        mql_emails={"a@x.com"}, call_emails=set(), sale_emails=set(),
        commissions_by_segment={}, segment_rollup=ROLLUP,
    )
    total = out[out["segment"] == "Total"].iloc[0]
    assert total["spend"] == 4000.0
    assert total["leads"] == 2
    assert total["callable_mql"] == 1
    assert total["cost_cmql"] == 4000.0
    assert out["segment"].iloc[-1] == "Total"


from dashboard.data.paid_mql import creative_tracker


def _ads(rows):
    return pd.DataFrame(rows, columns=["ad_id", "ad_name", "campaign_name",
                                       "spend", "video_plays"])


def _ents(rows):
    return pd.DataFrame(rows, columns=["ad_id", "created_time",
                                       "effective_status", "story_id"])


def _tracker(ads, ad_emails, mql_emails, **kw):
    defaults = dict(segment_rollup=ROLLUP, spend_floor=500.0,
                    winner_pct=0.25, standout_pct=0.10, min_mql=3)
    defaults.update(kw)
    return creative_tracker(
        ads,
        _ents([(r[0], "2026-08-01T00:00:00-0500", "ACTIVE", "1_2")
               for r in ads.itertuples(index=False)]),
        ad_emails=ad_emails, mql_emails=mql_emails,
        call_emails=set(), sale_emails=set(), **defaults)


def test_ad_below_spend_floor_is_excluded():
    out = _tracker(_ads([("1", "Cheap ad", CHIRO, 100.0, 0.0)]), {}, set())
    assert out.empty


def test_ad_without_enough_mqls_is_not_labeled():
    """One MQL on $600 of spend must not read as a Winner. That is noise,
    and a creative tracker that promotes noise is worse than none."""
    out = _tracker(
        _ads([("1", "Thin ad", CHIRO, 600.0, 0.0)]),
        {"1": {"a@x.com"}}, {"a@x.com"})
    assert out.iloc[0]["performance"] == "Not enough data"


def test_winner_and_standout_thresholds():
    """Segment average cost per callable MQL is $100 here. An ad at $70 is
    30% below (Winner); $85 is 15% below (Stand Out); $95 is 5% below
    (neither)."""
    ads = _ads([
        ("w", "Winner ad", CHIRO, 700.0, 0.0),
        ("s", "Standout ad", CHIRO, 850.0, 0.0),
        ("n", "Normal ad", CHIRO, 950.0, 0.0),
        ("x", "Expensive ad", CHIRO, 1500.0, 0.0),
    ])
    ad_emails = {
        "w": {f"w{i}@x.com" for i in range(10)},
        "s": {f"s{i}@x.com" for i in range(10)},
        "n": {f"n{i}@x.com" for i in range(10)},
        "x": {f"x{i}@x.com" for i in range(10)},
    }
    mql = set().union(*ad_emails.values())
    out = _tracker(ads, ad_emails, mql).set_index("ad_id")
    assert out.loc["w", "performance"] == "Winner"
    assert out.loc["s", "performance"] == "Stand Out"
    assert out.loc["n", "performance"] == ""
    assert out.loc["x", "performance"] == ""


def test_scored_against_own_segment_not_account_average():
    """A cheap segment must not swallow every Winner label. Each segment
    produces its own winner."""
    ads = _ads([
        ("c1", "Chiro cheap", CHIRO, 500.0, 0.0),
        ("c2", "Chiro dear", CHIRO, 1500.0, 0.0),
        ("n1", "NLAP cheap", NLAP, 5000.0, 0.0),
        ("n2", "NLAP dear", NLAP, 15000.0, 0.0),
    ])
    ad_emails = {k: {f"{k}{i}@x.com" for i in range(10)}
                 for k in ("c1", "c2", "n1", "n2")}
    mql = set().union(*ad_emails.values())
    out = _tracker(ads, ad_emails, mql).set_index("ad_id")
    assert out.loc["c1", "performance"] == "Winner"
    assert out.loc["n1", "performance"] == "Winner"


def test_format_from_video_plays():
    ads = _ads([("v", "Video ad", CHIRO, 600.0, 42.0),
                ("s", "Static ad", CHIRO, 600.0, 0.0)])
    out = _tracker(ads, {}, set()).set_index("ad_id")
    assert out.loc["v", "format"] == "Video"
    assert out.loc["s", "format"] == "Static"


def test_ad_with_no_hyros_attribution_reports_zero_not_a_label():
    """An ad Hyros never attributed must not be scored as an infinitely
    expensive loser. It has no data, which is a different fact."""
    out = _tracker(_ads([("1", "Untracked", CHIRO, 900.0, 0.0)]), {}, set())
    row = out.iloc[0]
    assert row["callable_mql"] == 0
    assert row["cost_cmql"] is None
    assert row["performance"] == "Not enough data"


def test_creative_tracker_sort_with_missing_launched():
    """Verify that sort_values with na_position='last' correctly handles None
    in an object-dtype column (launched). Ads with None launched must sort
    last, not raise or sort first."""
    ads = _ads([
        ("1", "Ad with date", CHIRO, 600.0, 0.0),
        ("2", "Ad without date", CHIRO, 600.0, 0.0),
    ])
    ad_emails = {"1": {"a@x.com"}, "2": {"b@x.com"}}
    mql_emails = {"a@x.com", "b@x.com"}
    # Override ad_entities to give ad 1 a date but not ad 2
    out = creative_tracker(
        ads,
        _ents([
            ("1", "2026-08-15T00:00:00-0500", "ACTIVE", "1_2"),
            ("2", "", "ACTIVE", "1_2"),
        ]),
        ad_emails=ad_emails, mql_emails=mql_emails,
        call_emails=set(), sale_emails=set(),
        segment_rollup=ROLLUP, spend_floor=500.0,
        winner_pct=0.25, standout_pct=0.10, min_mql=3,
    )
    # Verify both ads are present
    assert len(out) == 2
    # Verify ad with date comes first
    assert out.iloc[0]["ad_id"] == "1"
    assert out.iloc[0]["launched"] == "2026-08-15"
    # Verify ad without date comes last (None sorts last)
    assert out.iloc[1]["ad_id"] == "2"
    assert out.iloc[1]["launched"] is None
