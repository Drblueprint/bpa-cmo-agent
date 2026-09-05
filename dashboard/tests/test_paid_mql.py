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


def test_ad_with_no_hyros_attribution_reads_no_leads():
    """An ad Hyros never attributed must not be scored as an infinitely
    expensive loser. It has no data, which is a different fact -- and now
    that leads are surfaced, it must read the specific 'No leads' label
    (investigate tracking/targeting) rather than the generic 'Not enough
    data' bucket that also covers ads that are merely too new to judge."""
    out = _tracker(_ads([("1", "Untracked", CHIRO, 900.0, 0.0)]), {}, set())
    row = out.iloc[0]
    assert row["leads"] == 0
    assert row["callable_mql"] == 0
    assert row["cost_cmql"] is None
    assert row["performance"] == "No leads"
    assert row["cost_per_lead"] is None
    assert row["lead_to_cmql_pct"] is None


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


def test_ad_entities_numeric_id_lookup_succeeds():
    """Ruling P13: ad_entities.ad_id may arrive as numeric type rather than
    string. Without defensive coercion, the join silently fails on every row,
    leaving launched, status, and story_id blank for the entire table with no
    error or warning. This is the MAP invisibility problem: silent total
    blank-out instead of loud failure.

    This test verifies the join works even when ad_entities carries numeric
    ad_id, and that launched/status/story_id come through populated."""
    ads = _ads([
        (1, "Numeric id ad", CHIRO, 600.0, 0.0),
    ])
    ad_emails = {1: {"a@x.com"}}
    mql_emails = {"a@x.com"}
    # ad_entities with NUMERIC ad_id (not string)
    ents_df = pd.DataFrame([
        (1, "2026-08-15T00:00:00-0500", "ACTIVE", "story_1"),
    ], columns=["ad_id", "created_time", "effective_status", "story_id"])
    # Force ad_id to stay numeric
    ents_df["ad_id"] = ents_df["ad_id"].astype(int)

    out = creative_tracker(
        ads,
        ents_df,
        ad_emails=ad_emails, mql_emails=mql_emails,
        call_emails=set(), sale_emails=set(),
        segment_rollup=ROLLUP, spend_floor=500.0,
        winner_pct=0.25, standout_pct=0.10, min_mql=3,
    )
    # Verify the ad came through with populated entity fields
    row = out.iloc[0]
    assert row["launched"] == "2026-08-15"
    assert row["status"] == "ACTIVE"
    assert row["story_id"] == "story_1"


# --- Task 9 follow-up: lead-level visibility on the Creative Tracker -------
#
# Kurt: "I just need to know what's running and what I need to optimize and
# look into based on the number of total leads and then the MQLs from those
# leads." Three new columns (leads, cost_per_lead, lead_to_cmql_pct) and a
# split Performance label so "no leads at all", "leads that don't qualify"
# and "too new to judge" stop collapsing into one indistinguishable bucket.


def test_leads_and_derived_columns_populate_for_a_normal_ad():
    """Baseline positive path: leads is a plain count, cost_per_lead and
    lead_to_cmql_pct compute real numbers when both sides are non-zero."""
    ads = _ads([("1", "Normal ad", CHIRO, 500.0, 0.0)])
    emails = {f"e{i}@x.com" for i in range(10)}
    mql = {f"e{i}@x.com" for i in range(4)}  # 4 of 10 qualify
    row = _tracker(ads, {"1": emails}, mql, min_mql=3).iloc[0]
    assert row["leads"] == 10
    assert row["cost_per_lead"] == 50.0
    assert row["lead_to_cmql_pct"] == pytest.approx(0.4)


def test_ad_with_zero_leads_reads_no_leads():
    """Precedence rule 1: leads == 0 -> 'No leads'. This is the bucket Kurt
    needs to investigate tracking or targeting on -- Hyros attributed nobody
    to this ad at all, which is a different problem from an ad whose leads
    simply do not qualify."""
    out = _tracker(_ads([("1", "No-lead ad", CHIRO, 600.0, 0.0)]), {}, set())
    row = out.iloc[0]
    assert row["leads"] == 0
    assert row["performance"] == "No leads"
    assert row["cost_per_lead"] is None
    assert row["lead_to_cmql_pct"] is None


def test_ad_with_leads_but_no_mqls_reads_no_mqls_with_real_zero_pct():
    """Precedence rule 2: leads > 0 and callable_mql == 0 -> 'No MQLs'. This
    is the distinction that matters most: lead_to_cmql_pct must be a REAL
    0.0 (0% conversion is signal -- the traffic does not qualify), never
    None, which would instead claim there was nothing to measure."""
    ads = _ads([("1", "Unqualified ad", CHIRO, 600.0, 0.0)])
    emails = {f"e{i}@x.com" for i in range(5)}
    out = _tracker(ads, {"1": emails}, set())
    row = out.iloc[0]
    assert row["leads"] == 5
    assert row["callable_mql"] == 0
    assert row["performance"] == "No MQLs"
    assert row["lead_to_cmql_pct"] == 0.0
    assert row["lead_to_cmql_pct"] is not None
    assert row["cost_per_lead"] == 120.0


def test_ad_below_min_mql_still_reads_not_enough_data():
    """Precedence rule 3: an ad WITH qualifying MQLs, just not enough of
    them, must still fall through to 'Not enough data', not 'No MQLs'. Only
    a genuine zero gets the new label; below-threshold noise keeps the old
    one."""
    out = _tracker(
        _ads([("1", "Thin ad", CHIRO, 600.0, 0.0)]),
        {"1": {"a@x.com"}}, {"a@x.com"}, min_mql=3)
    row = out.iloc[0]
    assert row["leads"] == 1
    assert row["callable_mql"] == 1
    assert row["performance"] == "Not enough data"


def test_cost_per_lead_is_none_when_spend_is_zero():
    """cost_per_lead is a COST column, so it goes through _cost_div: None
    unless BOTH sides are non-zero. A zero-spend ad with real leads must not
    render $0.00 per lead, which would say those leads were free."""
    ads = _ads([("1", "Free ad", CHIRO, 0.0, 0.0)])
    out = _tracker(ads, {"1": {"a@x.com", "b@x.com"}}, set(),
                   spend_floor=0.0)
    row = out.iloc[0]
    assert row["leads"] == 2
    assert row["spend"] == 0.0
    assert row["cost_per_lead"] is None


def test_segment_average_still_excludes_ads_below_volume_guard():
    """The three new columns must not disturb the existing rule that a thin
    ad's cost_cmql never enters its segment's benchmark. 'thin' plants an
    expensive cost_cmql below the volume guard; if it leaked into the
    average, 'main' -- the only ad that actually clears the guard -- would be
    scored against an inflated average and wrongly read as a Winner instead
    of blank."""
    ads = _ads([
        ("thin", "Thin ad", CHIRO, 1000.0, 0.0),    # 1 MQL, below min_mql=3
        ("main", "Guarded ad", CHIRO, 500.0, 0.0),  # 5 MQL, clears guard
    ])
    ad_emails = {
        "thin": {"t0@x.com", "t1@x.com"},           # 2 leads, 1 becomes MQL
        "main": {f"m{i}@x.com" for i in range(8)},  # 8 leads, 5 become MQL
    }
    mql_emails = {"t0@x.com"} | {f"m{i}@x.com" for i in range(5)}
    out = _tracker(ads, ad_emails, mql_emails, min_mql=3).set_index("ad_id")

    assert out.loc["thin", "cost_cmql"] == 1000.0
    assert out.loc["thin", "performance"] == "Not enough data"

    # main's cost_cmql (500/5=100.0) is the ONLY value clearing the guard, so
    # the segment average must equal it exactly, giving delta == 0 -- neither
    # Winner nor Stand Out. Were "thin" wrongly included, avg = mean(1000,
    # 100) = 550 and main's delta would jump to 0.818, misreading "Winner".
    assert out.loc["main", "cost_cmql"] == 100.0
    assert out.loc["main", "performance"] == ""


def test_winner_and_standout_thresholds_unchanged_by_lead_columns():
    """Regression guard restating test_winner_and_standout_thresholds with
    the new columns also asserted: adding leads/cost_per_lead/
    lead_to_cmql_pct must not shift the existing Winner/Stand Out math."""
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
    # And the new columns are populated (10 leads, all 10 became MQL) rather
    # than silently absent or None.
    assert out.loc["w", "leads"] == 10
    assert out.loc["w", "lead_to_cmql_pct"] == 1.0
    assert out.loc["w", "cost_per_lead"] == 70.0


# --- B2: leads whose asset maps to no segment must not vanish ---------------

from dashboard.data.paid_mql import UNMATCHED_LEADS


def test_unsegmented_leads_get_their_own_row_and_reach_the_total():
    """B2: lds.groupby("segment") dropped segment=None rows from every segment
    row AND from all_emails, so unmapped-asset leads vanished from the table
    entirely, Total included. No row, no dash, no warning. That is how Chiro
    cost per lead came to be overstated by 163% when a typeform label was
    renamed in HubSpot."""
    out = segment_results(
        _seg_fb([(CHIRO, 1000.0)]),
        _seg_leads([("a@x.com", "Chiro"), ("b@x.com", "Chiro"),
                    ("c@x.com", None), ("d@x.com", None), ("e@x.com", None)]),
        mql_emails={"a@x.com", "c@x.com", "d@x.com"},
        call_emails=set(), sale_emails=set(),
        commissions_by_segment={}, segment_rollup=ROLLUP,
    )
    rows = {r["segment"]: r for _, r in out.iterrows()}
    assert UNMATCHED_LEADS in rows, "unsegmented leads were dropped"
    assert rows[UNMATCHED_LEADS]["leads"] == 3
    assert rows[UNMATCHED_LEADS]["callable_mql"] == 2
    assert rows[UNMATCHED_LEADS]["spend"] == 0.0
    assert rows["Chiro"]["leads"] == 2
    assert rows["Total"]["leads"] == 5
    assert rows["Total"]["callable_mql"] == 3
    assert rows["Total"]["cost_cmql"] == pytest.approx(1000.0 / 3)


def test_unsegmented_leads_arriving_as_nan_are_bucketed_too():
    """In production the unresolved segment is a pandas NaN, not None:
    Series.map(dict) yields NaN for a missing key and the rollup lambda passes
    it straight through, because bool(nan) is True. A fix that only handled
    None would leave the live defect in place."""
    frame = _seg_leads([("a@x.com", "Chiro"), ("b@x.com", "Chiro")])
    frame.loc[1, "segment"] = float("nan")
    out = segment_results(
        _seg_fb([(CHIRO, 500.0)]), frame,
        mql_emails=set(), call_emails=set(), sale_emails=set(),
        commissions_by_segment={}, segment_rollup=ROLLUP,
    )
    rows = {r["segment"]: r for _, r in out.iterrows()}
    assert rows[UNMATCHED_LEADS]["leads"] == 1
    assert rows["Total"]["leads"] == 2


def test_unmatched_leads_row_is_not_merged_into_unmatched_campaign_row():
    """Two different failures, two different rows. (unmatched) means a campaign
    name matched no regex; (unmatched leads) means a typeform label maps to no
    segment. Folding them together would hide which key needs fixing."""
    out = segment_results(
        _seg_fb([("Brand New Thing 2027", 800.0)]),
        _seg_leads([("a@x.com", None)]),
        mql_emails=set(), call_emails=set(), sale_emails=set(),
        commissions_by_segment={}, segment_rollup=ROLLUP,
    )
    segs = set(out["segment"])
    assert "(unmatched)" in segs
    assert UNMATCHED_LEADS in segs
    rows = {r["segment"]: r for _, r in out.iterrows()}
    assert rows["(unmatched)"]["spend"] == 800.0
    assert rows["(unmatched)"]["leads"] == 0
    assert rows[UNMATCHED_LEADS]["leads"] == 1


def test_all_segments_mapped_produces_no_unmatched_leads_row():
    """The bucket is a tripwire, not a permanent fixture."""
    out = segment_results(
        _seg_fb([(CHIRO, 100.0)]), _seg_leads([("a@x.com", "Chiro")]),
        mql_emails=set(), call_emails=set(), sale_emails=set(),
        commissions_by_segment={}, segment_rollup=ROLLUP,
    )
    assert UNMATCHED_LEADS not in set(out["segment"])


# --- B4: zero spend must render a dash, never $0.00 ------------------------

def test_zero_spend_segment_cost_columns_are_none_not_zero():
    """B4: _safe_div guards a zero denominator but not a zero numerator, so a
    segment with real leads and no spend row reported Cost CMQL $0.00, Cost per
    Call $0.00 and Cost per Close $0.00. The table then states that the segment
    acquires customers for free, which is the most decision-distorting cell you
    can put in front of someone allocating budget."""
    leads = [(f"t{i}@x.com", "TheraRay") for i in range(12)]
    out = segment_results(
        _seg_fb([(CHIRO, 900.0)]),
        _seg_leads([("a@x.com", "Chiro")] + leads),
        mql_emails={f"t{i}@x.com" for i in range(4)},
        call_emails={f"t{i}@x.com" for i in range(7)},
        sale_emails={"t0@x.com"},
        commissions_by_segment={}, segment_rollup=ROLLUP,
    )
    row = out[out["segment"] == "TheraRay"].iloc[0]
    assert row["spend"] == 0.0
    assert row["leads"] == 12
    assert row["callable_mql"] == 4
    assert row["calls"] == 7
    assert row["sales"] == 1
    assert row["cost_cmql"] is None
    assert row["cost_per_call"] is None
    assert row["cost_per_close"] is None
    assert row["segment_cac"] is None
    # Count ratios are genuine facts and must survive.
    assert row["lead_to_callable_pct"] == pytest.approx(4 / 12)
    assert row["callable_to_call_pct"] == pytest.approx(7 / 4)


def test_zero_spend_segment_cac_still_reports_real_commissions():
    """Commissions are money actually spent acquiring the customer, so a CAC
    built only from them is a real number, not a missing one. Only a wholly
    zero numerator (no spend AND no commission) suppresses the cell."""
    out = segment_results(
        _seg_fb([(CHIRO, 900.0)]),
        _seg_leads([("a@x.com", "Chiro"), ("t@x.com", "TheraRay")]),
        mql_emails=set(), call_emails=set(), sale_emails={"t@x.com"},
        commissions_by_segment={"TheraRay": 1525.0}, segment_rollup=ROLLUP,
    )
    row = out[out["segment"] == "TheraRay"].iloc[0]
    assert row["spend"] == 0.0
    assert row["cost_per_close"] is None
    assert row["segment_cac"] == 1525.0


def test_zero_spend_total_row_cost_columns_are_none():
    out = segment_results(
        _seg_fb([]), _seg_leads([("a@x.com", "Chiro")]),
        mql_emails={"a@x.com"}, call_emails={"a@x.com"},
        sale_emails={"a@x.com"}, commissions_by_segment={},
        segment_rollup=ROLLUP,
    )
    total = out[out["segment"] == "Total"].iloc[0]
    assert total["spend"] == 0.0
    assert total["leads"] == 1
    assert total["cost_cmql"] is None
    assert total["cost_per_call"] is None
    assert total["cost_per_close"] is None
    assert total["segment_cac"] is None


def test_daily_row_with_leads_but_no_spend_has_no_cost_columns():
    """Table 1, same defect: a day where the selected segments produced leads
    but carry no spend row reported Cost Per Lead $0.00."""
    out = daily_mql_summary(
        _fb([]),
        _leads([("a@x.com", "2026-08-10", "Chiro"),
                ("b@x.com", "2026-08-10", "Chiro")]),
        _mqls([("a@x.com", "2026-08-10", "Chiro")]),
        segment_rollup=ROLLUP,
    )
    day = out[out["date"] == "2026-08-10"].iloc[0]
    assert day["leads"] == 2
    assert day["callable_mql"] == 1
    assert day["cost_per_lead"] is None
    assert day["cost_per_callable_mql"] is None
    assert day["lead_to_callable_pct"] == 0.5
    total = out[out["date"] == "Total"].iloc[0]
    assert total["cost_per_lead"] is None
    assert total["cost_per_callable_mql"] is None


# --- B2 in Table 1: the same leads must survive the segment filter ---------

def test_daily_summary_keeps_unsegmented_leads_when_their_label_is_selected():
    frame = _leads([("a@x.com", "2026-08-10", "Chiro"),
                    ("b@x.com", "2026-08-10", None)])
    out = daily_mql_summary(
        _fb([("2026-08-10", CHIRO, 200.0)]), frame,
        _mqls([("b@x.com", "2026-08-10", None)]),
        segment_rollup=ROLLUP, segments=("Chiro", UNMATCHED_LEADS),
    )
    total = out[out["date"] == "Total"].iloc[0]
    assert total["leads"] == 2
    assert total["callable_mql"] == 1


def test_daily_summary_excludes_unsegmented_leads_when_not_selected():
    frame = _leads([("a@x.com", "2026-08-10", "Chiro"),
                    ("b@x.com", "2026-08-10", None)])
    out = daily_mql_summary(
        _fb([("2026-08-10", CHIRO, 200.0)]), frame,
        _mqls([("b@x.com", "2026-08-10", None)]),
        segment_rollup=ROLLUP, segments=("Chiro",),
    )
    total = out[out["date"] == "Total"].iloc[0]
    assert total["leads"] == 1
    assert total["callable_mql"] == 0
