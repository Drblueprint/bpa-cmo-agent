import pytest
from dashboard.data.reconcile import classify_tier


@pytest.mark.parametrize("raw,plan,group", [
    ("1:  PRIMARY", "FULL", "Chiro"),
    ("PT - Primary", "FULL", "PT"),
    ("90-DAY - C", "90DAY", "Chiro"),
    ("DIY - C", "DIY", "Chiro"),
    ("BASIC - NOT CERTIFIED", "BASIC", "Chiro"),
    ("PT - DIY", "DIY", "PT"),
    ("", "UNKNOWN", "Chiro"),
    (None, "UNKNOWN", "Chiro"),
])
def test_classify_tier(raw, plan, group):
    assert classify_tier(raw) == (plan, group)
