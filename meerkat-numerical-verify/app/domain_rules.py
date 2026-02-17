"""
Domain-specific tolerance thresholds and severity rules.

Zero tolerance means the numbers must match exactly.
A tolerance of 0.01 means up to 1% deviation is acceptable (rounding).

Severity levels:
  - critical: Immediate BLOCK. Wrong medication dose, wrong AE count.
  - high: Strong FLAG. Wrong lab value, wrong revenue figure.
  - medium: Soft FLAG. Minor rounding in non-critical context.
  - low: Informational. Acceptable rounding.
"""

from dataclasses import dataclass


@dataclass
class ToleranceRule:
    tolerance: float       # Max allowed relative deviation (0.0 = exact match)
    severity: str          # "critical" | "high" | "medium" | "low"
    description: str


# ── Healthcare ─────────────────────────────────────────────────────

HEALTHCARE_RULES: dict[str, ToleranceRule] = {
    "medication_dose": ToleranceRule(
        tolerance=0.0,
        severity="critical",
        description="Medication dosages must match exactly",
    ),
    "lab_value": ToleranceRule(
        tolerance=0.01,
        severity="high",
        description="Lab values: 1% tolerance for rounding",
    ),
    "vital_sign": ToleranceRule(
        tolerance=0.02,
        severity="high",
        description="Vital signs: 2% tolerance",
    ),
    "count": ToleranceRule(
        tolerance=0.0,
        severity="high",
        description="Event/procedure counts must match exactly",
    ),
    "age": ToleranceRule(
        tolerance=0.0,
        severity="medium",
        description="Patient age must match exactly",
    ),
    "duration_months": ToleranceRule(
        tolerance=0.0,
        severity="critical",
        description="Treatment durations must match exactly (e.g., antibiotic courses)",
    ),
    "default": ToleranceRule(
        tolerance=0.01,
        severity="medium",
        description="Default healthcare: 1% tolerance",
    ),
}


# ── Pharma ─────────────────────────────────────────────────────────

PHARMA_RULES: dict[str, ToleranceRule] = {
    "adverse_event_count": ToleranceRule(
        tolerance=0.0,
        severity="critical",
        description="Adverse event counts must match exactly",
    ),
    "dosage": ToleranceRule(
        tolerance=0.0,
        severity="critical",
        description="Drug dosages must match exactly",
    ),
    "p_value": ToleranceRule(
        tolerance=0.0,
        severity="high",
        description="P-values must match exactly",
    ),
    "efficacy_percentage": ToleranceRule(
        tolerance=0.005,
        severity="high",
        description="Efficacy: 0.5% tolerance",
    ),
    "default": ToleranceRule(
        tolerance=0.005,
        severity="medium",
        description="Default pharma: 0.5% tolerance",
    ),
}


# ── Legal ──────────────────────────────────────────────────────────

LEGAL_RULES: dict[str, ToleranceRule] = {
    "duration_months": ToleranceRule(
        tolerance=0.0,
        severity="critical",
        description="Contract durations must match exactly",
    ),
    "monetary_value": ToleranceRule(
        tolerance=0.0,
        severity="critical",
        description="Monetary values must match exactly",
    ),
    "distance": ToleranceRule(
        tolerance=0.0,
        severity="high",
        description="Geographic restrictions must match exactly",
    ),
    "percentage": ToleranceRule(
        tolerance=0.01,
        severity="medium",
        description="Percentages: 1% tolerance",
    ),
    "default": ToleranceRule(
        tolerance=0.0,
        severity="medium",
        description="Default legal: exact match",
    ),
}


# ── Financial ──────────────────────────────────────────────────────

FINANCIAL_RULES: dict[str, ToleranceRule] = {
    "revenue": ToleranceRule(
        tolerance=0.005,
        severity="high",
        description="Revenue: 0.5% tolerance for rounding",
    ),
    "percentage": ToleranceRule(
        tolerance=0.001,
        severity="high",
        description="Percentages: 0.1% tolerance",
    ),
    "share_count": ToleranceRule(
        tolerance=0.0,
        severity="high",
        description="Share counts must match exactly",
    ),
    "ratio": ToleranceRule(
        tolerance=0.01,
        severity="medium",
        description="Ratios: 1% tolerance",
    ),
    "default": ToleranceRule(
        tolerance=0.005,
        severity="medium",
        description="Default financial: 0.5% tolerance",
    ),
}


# ── Domain registry ────────────────────────────────────────────────

DOMAIN_RULES: dict[str, dict[str, ToleranceRule]] = {
    "healthcare": HEALTHCARE_RULES,
    "pharma": PHARMA_RULES,
    "legal": LEGAL_RULES,
    "financial": FINANCIAL_RULES,
}


def get_tolerance_rule(domain: str, context_type: str) -> ToleranceRule:
    """
    Get the tolerance rule for a given domain and context type.
    Falls back to domain default, then to a general default.
    """
    rules = DOMAIN_RULES.get(domain, {})
    if context_type in rules:
        return rules[context_type]
    if "default" in rules:
        return rules["default"]
    # Ultimate fallback
    return ToleranceRule(tolerance=0.01, severity="medium", description="General default: 1% tolerance")
