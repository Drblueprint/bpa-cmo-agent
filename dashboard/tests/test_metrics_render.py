"""Guards for the METRICS tab render wiring."""
from dashboard.sections.metrics import _money_metric_ids


def test_map_ad_spend_formats_as_money():
    # MAP ad spend must render as whole dollars in the weekly scorecard grid.
    assert "map_ad_spend" in _money_metric_ids()
