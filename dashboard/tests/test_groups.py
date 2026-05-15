"""Tests for campaign group regex matcher."""
import pytest

from dashboard.data.groups import match_group


@pytest.mark.parametrize("name,expected", [
    ("DS | __Chiro__ Mixed Funnel Setup | CBO | USA", "Chiro"),
    ("DS | __PT__ Recovery Program Funnel | CBO | USA", "PT Recovery"),
    ("DS | __Theraray__ Funnel Setup | CBO | USA", "TheraRay"),
    ("DS | __EMX__ Event Funnel | CBO | USA", "EMX"),
    ("DS | __Chiro__ but also __EMX__ inside", "EMX"),  # EMX wins
    ("Something with no marker", None),
    ("", None),
])
def test_match_group(name, expected):
    assert match_group(name) == expected
