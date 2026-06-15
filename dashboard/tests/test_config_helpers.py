"""Tests for config-level classification helpers."""
from dashboard.config import is_existing_customer, asset_or_referral


def test_is_existing_customer_lifecycle():
    assert is_existing_customer("customer", None) is True
    assert is_existing_customer("Customer", "") is True


def test_is_existing_customer_paid_tier_backup():
    # A real paid tier with no "customer" lifecycle still counts as customer.
    assert is_existing_customer("opportunity", "1:  PRIMARY") is True
    assert is_existing_customer("salesqualifiedlead", "90-DAY - C") is True


def test_is_existing_customer_foundational_is_a_lead():
    # FOUNDATIONAL - C is the TheraRay/NLAP opt-in label — a LEAD, not a
    # customer — so it must NOT trigger the customer exclusion.
    assert is_existing_customer("salesqualifiedlead", "9 FOUNDATIONAL - C") is False
    assert is_existing_customer("marketingqualifiedlead", "FOUNDATIONAL - C") is False
    # ...unless lifecycle itself says customer.
    assert is_existing_customer("customer", "9 FOUNDATIONAL - C") is True


def test_is_existing_customer_no_signal():
    assert is_existing_customer("lead", None) is False
    assert is_existing_customer(None, "") is False


def test_asset_or_referral_fallback():
    assert asset_or_referral("Top 10 typeform", "James Haley") == "Top 10 typeform"
    assert asset_or_referral("", "James Haley") == "Referral: James Haley"
    assert asset_or_referral(None, None) == ""
