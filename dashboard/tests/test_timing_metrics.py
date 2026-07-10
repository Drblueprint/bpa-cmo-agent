from datetime import datetime
from zoneinfo import ZoneInfo
from dashboard.data.reconcile import business_minutes_between

CT = ZoneInfo("America/Chicago")


def _ep(y, mo, d, h, mi=0):
    return int(datetime(y, mo, d, h, mi, tzinfo=CT).timestamp())


def test_business_minutes_within_one_day():
    assert business_minutes_between(_ep(2026, 6, 1, 10), _ep(2026, 6, 1, 11)) == 60.0  # Mon 10-11


def test_business_minutes_full_workday():
    assert business_minutes_between(_ep(2026, 6, 1, 9), _ep(2026, 6, 1, 17)) == 480.0


def test_business_minutes_clamps_after_hours():
    # Mon 16:00 -> 20:00: only 16-17 counts
    assert business_minutes_between(_ep(2026, 6, 1, 16), _ep(2026, 6, 1, 20)) == 60.0


def test_business_minutes_skips_weekend():
    # Fri 16:00 -> Mon 10:00: Fri 16-17 (60) + Mon 9-10 (60) = 120; Sat/Sun excluded
    assert business_minutes_between(_ep(2026, 6, 5, 16), _ep(2026, 6, 8, 10)) == 120.0


def test_business_minutes_weekend_only_is_zero():
    assert business_minutes_between(_ep(2026, 6, 6, 10), _ep(2026, 6, 7, 12)) == 0.0


def test_business_minutes_end_before_start_is_zero():
    assert business_minutes_between(_ep(2026, 6, 1, 12), _ep(2026, 6, 1, 10)) == 0.0


def test_business_minutes_none_returns_none():
    assert business_minutes_between(None, _ep(2026, 6, 1, 10)) is None


import pandas as pd
from dashboard.data.reconcile import compute_speed_to_lead


def test_compute_speed_to_lead_all_and_prime():
    # Lead submits Fri 16:00 CT; first outbound call Mon 10:00 CT.
    # All = raw elapsed (66.0h = 3960 min); Prime = 120 business minutes.
    lead_ts = _ep(2026, 6, 5, 16)          # Fri 16:00 CT
    call_ts = _ep(2026, 6, 8, 10)          # Mon 10:00 CT
    contacts = pd.DataFrame([{
        "hs_id": "1", "typeform_submission_date":
            datetime.fromtimestamp(lead_ts, tz=CT).astimezone(ZoneInfo("UTC")).isoformat(),
        "created": None, "phone": "+15551234567", "mobilephone": None,
    }])
    calls = pd.DataFrame([{
        "direction": "outbound", "phone_normalized": "5551234567",
        "started_at_utc": call_ts,
    }])
    df = compute_speed_to_lead(contacts, calls).set_index("hs_id")
    assert abs(df.loc["1", "speed_to_lead_minutes"] - 3960.0) < 1.0
    assert df.loc["1", "speed_to_lead_minutes_prime"] == 120.0
