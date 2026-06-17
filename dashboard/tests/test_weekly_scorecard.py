from dashboard.data.reconcile import _METRIC_LABELS
from dashboard.config import METRICS_GOALS


def test_scorecard_labels_present_and_clean():
    new = [
        "theraray_submissions", "nlap_submissions",
        "dti_15min_scheduled", "dti_discovery_completed",
        "bofu_submissions_direct",
    ]
    for mid in new:
        assert mid in _METRIC_LABELS, f"missing label for {mid}"
        assert mid in METRICS_GOALS, f"missing goal for {mid}"
    # No em dashes anywhere in user-facing labels.
    for label in _METRIC_LABELS.values():
        assert "—" not in label, f"em dash in label: {label!r}"
    # Registry and goals keys stay aligned.
    assert set(_METRIC_LABELS) == set(METRICS_GOALS)
    # Specific goals from the Ninety scorecard.
    assert METRICS_GOALS["nlap_submissions"] == 15
    assert METRICS_GOALS["dti_15min_scheduled"] == 2
    assert METRICS_GOALS["dti_discovery_completed"] == 5
    # Relabel: the FB TheraRay row is disambiguated.
    assert _METRIC_LABELS["theraray_leads"] == "TheraRay - FB Leads"
