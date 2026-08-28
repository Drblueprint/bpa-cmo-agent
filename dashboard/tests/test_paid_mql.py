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
