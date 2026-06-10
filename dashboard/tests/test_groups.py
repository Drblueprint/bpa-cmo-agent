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


def test_match_group_nlap():
    assert match_group("DS | __NLAP__ Funnel Setup | CBO | USA | CA") == "NLAP"


def test_match_group_existing_unaffected():
    assert match_group("DS | __Theraray__ Funnel Setup | CBO | USA") == "TheraRay"
    assert match_group("DS | __Chiro__ Mixed Funnel Setup | CBO") == "Chiro"
    assert match_group("DS | EMX 2026 Kansas City Mixed Funnel Setup") == "EMX"
    assert match_group("DS | __NLAP__ but also __Chiro__") == "NLAP" or \
           match_group("DS | __NLAP__ but also __Chiro__") == "Chiro"
