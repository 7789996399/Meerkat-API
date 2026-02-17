"""
Unit normalization for numerical comparison.

Converts values to canonical units so "2g" and "2000mg" are recognized
as equivalent, "$4.2B" and "$4,200,000,000" match, etc.

Returns (normalized_value, canonical_unit) tuples.
"""

import re

# ── Weight / Mass ──────────────────────────────────────────────────

MASS_TO_MG: dict[str, float] = {
    "mcg": 0.001,
    "ug": 0.001,
    "µg": 0.001,
    "microgram": 0.001,
    "micrograms": 0.001,
    "mg": 1.0,
    "milligram": 1.0,
    "milligrams": 1.0,
    "g": 1000.0,
    "gram": 1000.0,
    "grams": 1000.0,
    "kg": 1_000_000.0,
    "kilogram": 1_000_000.0,
    "kilograms": 1_000_000.0,
}

# ── Volume ─────────────────────────────────────────────────────────

VOLUME_TO_ML: dict[str, float] = {
    "ml": 1.0,
    "milliliter": 1.0,
    "milliliters": 1.0,
    "cc": 1.0,
    "l": 1000.0,
    "liter": 1000.0,
    "liters": 1000.0,
    "litre": 1000.0,
    "litres": 1000.0,
    "dl": 100.0,
    "deciliter": 100.0,
}

# ── Large number multipliers ──────────────────────────────────────

MULTIPLIERS: dict[str, float] = {
    "k": 1_000,
    "thousand": 1_000,
    "m": 1_000_000,
    "million": 1_000_000,
    "mm": 1_000_000,       # Financial: MM = million
    "b": 1_000_000_000,
    "billion": 1_000_000_000,
    "bn": 1_000_000_000,
    "t": 1_000_000_000_000,
    "trillion": 1_000_000_000_000,
    "tn": 1_000_000_000_000,
}

# ── Time ───────────────────────────────────────────────────────────

TIME_TO_DAYS: dict[str, float] = {
    "day": 1.0,
    "days": 1.0,
    "week": 7.0,
    "weeks": 7.0,
    "month": 30.0,
    "months": 30.0,
    "year": 365.0,
    "years": 365.0,
}


def normalize_value(value: float, unit: str) -> tuple[float, str]:
    """
    Normalize a value+unit to a canonical form.

    Returns (normalized_value, canonical_unit).
    If unit is not recognized, returns the value unchanged.
    """
    unit_lower = unit.lower().strip().rstrip("s.")

    # Mass -> mg
    if unit_lower in MASS_TO_MG:
        return value * MASS_TO_MG[unit_lower], "mg"

    # Volume -> ml
    if unit_lower in VOLUME_TO_ML:
        return value * VOLUME_TO_ML[unit_lower], "ml"

    # Time -> days
    if unit_lower in TIME_TO_DAYS:
        return value * TIME_TO_DAYS[unit_lower], "days"

    # Large number multipliers (e.g., "$4.2B" -> 4200000000)
    if unit_lower in MULTIPLIERS:
        return value * MULTIPLIERS[unit_lower], "units"

    # Percentage: keep as-is but standardize unit name
    if unit_lower in ("%", "percent", "pct"):
        return value, "%"

    return value, unit_lower


def strip_currency_and_commas(text: str) -> str:
    """Remove currency symbols and commas from a number string."""
    return re.sub(r"[$€£¥,]", "", text)


def parse_number_with_multiplier(num_str: str, suffix: str) -> float | None:
    """
    Parse a number string that might have a multiplier suffix.
    "4.2" + "billion" -> 4_200_000_000
    "500" + "mg" -> 500 (no multiplier, just a unit)
    """
    try:
        value = float(strip_currency_and_commas(num_str))
    except ValueError:
        return None

    suffix_lower = suffix.lower().strip().rstrip("s.")
    if suffix_lower in MULTIPLIERS:
        return value * MULTIPLIERS[suffix_lower]

    return value
