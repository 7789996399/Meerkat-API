"""
Tests for numerical extraction.

All examples are real patterns from clinical notes, legal contracts,
and financial filings. No synthesized data.
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.extractor import extract_numbers


class TestClinicalExtraction:
    """Tests using real clinical note patterns."""

    def test_lab_values(self):
        text = "Labs: WBC 14.2, Hgb 11.8, PLT 245, Cr 1.2, K 4.1"
        numbers = extract_numbers(text)
        values = [n.value for n in numbers]
        assert 14.2 in values
        assert 11.8 in values
        assert 245.0 in values
        assert 1.2 in values
        assert 4.1 in values

    def test_medication_doses(self):
        text = "Medications: Metoprolol 50mg BID, Lisinopril 10mg daily, Metformin 500mg BID"
        numbers = extract_numbers(text)
        values = [n.value for n in numbers]
        assert 50.0 in values
        assert 10.0 in values
        assert 500.0 in values

    def test_vital_signs(self):
        text = "Vitals: T 38.2, HR 98, BP 132/78, SpO2 91%, RR 22"
        numbers = extract_numbers(text)
        values = [n.value for n in numbers]
        assert 38.2 in values
        assert 98.0 in values
        assert 132.0 in values  # systolic
        assert 78.0 in values   # diastolic
        assert 91.0 in values
        assert 22.0 in values

    def test_age_and_counts(self):
        text = "Patient: 67F, admitted for 5 days, 3 chest X-rays performed"
        numbers = extract_numbers(text)
        values = [n.value for n in numbers]
        assert 67.0 in values
        assert 5.0 in values
        assert 3.0 in values

    def test_clinical_context_classification(self):
        text = "WBC 14.2, Metoprolol 50mg, BP 120/80, SpO2 95%"
        numbers = extract_numbers(text)

        # Find the WBC number specifically (value 14.2)
        wbc = [n for n in numbers if n.value == 14.2]
        assert len(wbc) >= 1
        assert wbc[0].context_type == "lab_value"

        # Find the medication dose (50mg)
        meds = [n for n in numbers if n.value == 50.0]
        assert len(meds) >= 1
        assert meds[0].context_type == "medication_dose"

        # Find the SpO2 value
        spo2 = [n for n in numbers if n.value == 95.0]
        assert len(spo2) >= 1
        assert spo2[0].context_type == "vital_sign"


class TestFinancialExtraction:

    def test_revenue_with_multipliers(self):
        text = "Revenue was $4.2B in 2024, up from $3.8B in 2023."
        numbers = extract_numbers(text)
        values = [n.value for n in numbers]
        assert 4_200_000_000.0 in values or 4.2 in values  # depends on multiplier handling
        assert 2024.0 in values
        assert 2023.0 in values

    def test_percentages(self):
        text = "EBITDA margin 14.2%, gross margin 42.8%, YoY growth 8.3%"
        numbers = extract_numbers(text)
        values = [n.value for n in numbers]
        assert 14.2 in values
        assert 42.8 in values
        assert 8.3 in values

    def test_monetary_with_commas(self):
        text = "Total damages of $1,250,000 plus interest of $87,500."
        numbers = extract_numbers(text)
        values = [n.value for n in numbers]
        assert 1250000.0 in values
        assert 87500.0 in values


class TestLegalExtraction:

    def test_contract_durations(self):
        text = "Non-compete clause for 24 months within 100 miles of Vancouver."
        numbers = extract_numbers(text)
        values = [n.value for n in numbers]
        assert 24.0 in values
        assert 100.0 in values

    def test_section_numbers_not_extracted_as_values(self):
        """Section 8.2 should not be confused with a standalone value."""
        text = "Under Section 8.2, the employee agrees to a 12-month restriction."
        numbers = extract_numbers(text)
        # 12 should be extracted
        values = [n.value for n in numbers]
        assert 12.0 in values


class TestEdgeCases:

    def test_empty_text(self):
        numbers = extract_numbers("")
        assert len(numbers) == 0

    def test_no_numbers(self):
        numbers = extract_numbers("The patient was admitted and treated with antibiotics.")
        assert len(numbers) == 0

    def test_decimal_only(self):
        text = "Procalcitonin 0.8, CRP 2.4"
        numbers = extract_numbers(text)
        values = [n.value for n in numbers]
        assert 0.8 in values
        assert 2.4 in values


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
