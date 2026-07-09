from datetime import date
from dashboard.data.reconcile import _period_ranges


def test_period_ranges_weekly():
    # Wed 2026-06-03 .. Tue 2026-06-16 -> 3 Mon-Sun weeks covering the span
    r = _period_ranges(date(2026, 6, 3), date(2026, 6, 16), "weekly")
    assert [(s, e) for _, s, e in r] == [
        (date(2026, 6, 1), date(2026, 6, 7)),
        (date(2026, 6, 8), date(2026, 6, 14)),
        (date(2026, 6, 15), date(2026, 6, 21)),
    ]


def test_period_ranges_monthly():
    r = _period_ranges(date(2026, 4, 15), date(2026, 6, 10), "monthly")
    assert [(s, e) for _, s, e in r] == [
        (date(2026, 4, 1), date(2026, 4, 30)),
        (date(2026, 5, 1), date(2026, 5, 31)),
        (date(2026, 6, 1), date(2026, 6, 30)),
    ]


def test_period_ranges_shorter_than_one_bucket():
    r = _period_ranges(date(2026, 6, 2), date(2026, 6, 4), "weekly")
    assert len(r) == 1
    assert (r[0][1], r[0][2]) == (date(2026, 6, 1), date(2026, 6, 7))
