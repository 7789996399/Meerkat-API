"""Tests for domain-specific tolerance rules."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.domain_rules import get_tolerance_rule


class TestHealthcareRules:

    def test_medication_dose_zero_tolerance(self):
        rule = get_tolerance_rule("healthcare", "medication_dose")
        assert rule.tolerance == 0.0
        assert rule.severity == "critical"

    def test_lab_value_small_tolerance(self):
        rule = get_tolerance_rule("healthcare", "lab_value")
        assert rule.tolerance == 0.01
        assert rule.severity == "high"

    def test_vital_sign_tolerance(self):
        rule = get_tolerance_rule("healthcare", "vital_sign")
        assert rule.tolerance == 0.02

    def test_default_fallback(self):
        rule = get_tolerance_rule("healthcare", "unknown_type")
        assert rule.tolerance == 0.01  # healthcare default


class TestLegalRules:

    def test_monetary_zero_tolerance(self):
        rule = get_tolerance_rule("legal", "monetary_value")
        assert rule.tolerance == 0.0
        assert rule.severity == "critical"

    def test_duration_zero_tolerance(self):
        rule = get_tolerance_rule("legal", "duration_months")
        assert rule.tolerance == 0.0
        assert rule.severity == "critical"


class TestFinancialRules:

    def test_revenue_small_tolerance(self):
        rule = get_tolerance_rule("financial", "revenue")
        assert rule.tolerance == 0.005

    def test_share_count_zero_tolerance(self):
        rule = get_tolerance_rule("financial", "share_count")
        assert rule.tolerance == 0.0


class TestUnknownDomain:

    def test_unknown_domain_uses_general_default(self):
        rule = get_tolerance_rule("unknown_domain", "anything")
        assert rule.tolerance == 0.01
        assert rule.severity == "medium"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
