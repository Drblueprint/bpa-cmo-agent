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
