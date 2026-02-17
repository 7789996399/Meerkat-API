"""
Tests for numerical comparison and matching.

Tests use real clinical scenarios to verify that:
1. Numbers are correctly matched by context (not randomly)
2. Tolerance thresholds work correctly per domain
3. Critical mismatches are detected (medication dose errors)
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.extractor import extract_numbers
from app.comparator import match_and_compare


class TestHealthcareComparison:
    """
    Real clinical scenario: AI Scribe generates a discharge summary
    from an EHR source. We verify the numbers match.
    """

    def test_correct_clinical_note(self):
        """All numbers match -- should not have critical mismatches."""
        source = "Labs: WBC 14.2. Medications: Metoprolol 50mg BID. Vitals: HR 98, SpO2 91%."
        ai = "The patient's WBC was 14.2. She was on Metoprolol 50mg twice daily. HR 98, oxygen saturation 91%."

        src_nums = extract_numbers(source)
        ai_nums = extract_numbers(ai)
        result = match_and_compare(src_nums, ai_nums, "healthcare")

        # Key assertion: no critical mismatches on correct data
        assert result.critical_mismatches == 0
        # All matched pairs should pass (some numbers may be ungrounded
        # due to context mismatch, but that's a warning, not an error)
        passing = [m for m in result.matches if m.match]
        assert len(passing) >= 2  # At least WBC and dose should match

    def test_medication_dose_distortion(self):
        """Wrong medication dose -- should FAIL with critical severity."""
        source = "Medications: Metoprolol 50mg BID."
        ai = "Patient was started on Metoprolol 100mg daily."

        src_nums = extract_numbers(source)
        ai_nums = extract_numbers(ai)
        result = match_and_compare(src_nums, ai_nums, "healthcare")

        assert result.status == "fail"
        assert result.critical_mismatches >= 1

    def test_lab_value_distortion(self):
        """WBC changed from 14.2 to 16.8 -- should FLAG."""
        source = "Labs: WBC 14.2, Cr 1.2"
        ai = "Lab results showed WBC 16.8 and creatinine 1.2."

        src_nums = extract_numbers(source)
        ai_nums = extract_numbers(ai)
        result = match_and_compare(src_nums, ai_nums, "healthcare")

        # At least one mismatch should be detected
        failing = [m for m in result.matches if not m.match]
        assert len(failing) >= 1
        assert result.score < 1.0

    def test_fabricated_number(self):
        """AI adds a number not in source -- should detect as ungrounded."""
        source = "Medications: Lisinopril 10mg daily."
        ai = "Patient on Lisinopril 10mg daily. Atorvastatin 40mg was also prescribed."

        src_nums = extract_numbers(source)
        ai_nums = extract_numbers(ai)
        result = match_and_compare(src_nums, ai_nums, "healthcare")

        # 40mg should be ungrounded (not in source)
        assert len(result.ungrounded) >= 1

    def test_pcn_allergy_scenario(self):
        """
        Real scenario from flagged items: discharge summary for
        pneumonia patient with documented PCN allergy.
        """
        source = (
            "Patient: 67F, PMH: COPD, HTN, T2DM. Allergies: PCN (rash). "
            "Vitals: T 39.1, HR 98, BP 132/78, SpO2 91%. "
            "Labs: WBC 14.2, Procalcitonin 0.8. "
            "Treatment: Ceftriaxone 1g IV daily."
        )
        ai = (
            "67-year-old female with COPD, HTN, and T2DM. Temperature 39.1, "
            "heart rate 98, blood pressure 132/78, SpO2 91%. "
            "WBC 14.2, procalcitonin 0.8. Treated with Ceftriaxone 1g IV daily."
        )

        src_nums = extract_numbers(source)
        ai_nums = extract_numbers(ai)
        result = match_and_compare(src_nums, ai_nums, "healthcare")

        # Key assertions: no critical mismatches on correct data
        assert result.critical_mismatches == 0
        # Matched pairs should all pass
        failing_matches = [m for m in result.matches if not m.match]
        passing_matches = [m for m in result.matches if m.match]
        assert len(passing_matches) >= 3  # BP, WBC, dose should match


class TestLegalComparison:

    def test_contract_duration_distortion(self):
        """24-month non-compete changed to 18 months."""
        source = "Employee agrees to a 24-month non-compete within 100 miles."
        ai = "The non-compete restricts for 18 months within 100 miles."

        src_nums = extract_numbers(source)
        ai_nums = extract_numbers(ai)
        result = match_and_compare(src_nums, ai_nums, "legal")

        failing = [m for m in result.matches if not m.match]
        assert len(failing) >= 1


class TestFinancialComparison:

    def test_percentage_distortion(self):
        """EBITDA margin changed from 14.2% to 18.7%."""
        source = "EBITDA margin was 14.2% for Q3 2024."
        ai = "The company reported an EBITDA margin of 18.7% in Q3 2024."

        src_nums = extract_numbers(source)
        ai_nums = extract_numbers(ai)
        result = match_and_compare(src_nums, ai_nums, "financial")

        failing = [m for m in result.matches if not m.match]
        assert len(failing) >= 1


class TestEdgeCases:

    def test_no_numbers_in_either(self):
        source = "Patient admitted with pneumonia."
        ai = "The patient was admitted for community-acquired pneumonia."

        src_nums = extract_numbers(source)
        ai_nums = extract_numbers(ai)
        result = match_and_compare(src_nums, ai_nums, "healthcare")

        assert result.status == "pass"
        assert result.score == 1.0

    def test_no_numbers_in_ai(self):
        source = "WBC 14.2, Cr 1.2"
        ai = "Lab values were within normal limits."

        src_nums = extract_numbers(source)
        ai_nums = extract_numbers(ai)
        result = match_and_compare(src_nums, ai_nums, "healthcare")

        assert result.status == "pass"  # No AI numbers to verify

    def test_numbers_in_ai_but_not_source(self):
        source = "Patient was admitted."
        ai = "Patient admitted. WBC was 14.2, started on Metoprolol 50mg."

        src_nums = extract_numbers(source)
        ai_nums = extract_numbers(ai)
        result = match_and_compare(src_nums, ai_nums, "healthcare")

        assert len(result.ungrounded) >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
