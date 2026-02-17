"""
Meerkat Integration Test: Numerical Verification vs Clinical Scenarios

Runs the numerical verification module against the clinical test dataset
and produces detection rates per hallucination type.

This is the offline/unit-test version. The full pipeline test (all 5 checks)
requires Docker services running.
"""

import json
import os
import sys

# Add project paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "meerkat-numerical-verify"))

from app.extractor import extract_numbers
from app.comparator import match_and_compare


def load_scenarios():
    path = os.path.join(os.path.dirname(__file__), "clinical-data", "test-scenarios.json")
    with open(path) as f:
        data = json.load(f)
    return data["scenarios"]


def run_numerical_check(scenario):
    """Run numerical verification on a single scenario."""
    source_nums = extract_numbers(scenario["source"])
    ai_nums = extract_numbers(scenario["ai_output"])
    domain = scenario.get("domain", "healthcare")
    result = match_and_compare(source_nums, ai_nums, domain)

    # Determine what flags would be produced
    flags = []
    if result.critical_mismatches > 0:
        flags.append("critical_numerical_mismatch")
    if result.status == "fail":
        flags.append("numerical_distortion")
    if result.status == "warning":
        flags.append("numerical_warning")
    if result.ungrounded:
        flags.append("ungrounded_numbers")

    return {
        "score": result.score,
        "status": result.status,
        "flags": flags,
        "matched": len(result.matches),
        "passing": sum(1 for m in result.matches if m.match),
        "failing": sum(1 for m in result.matches if not m.match),
        "critical": result.critical_mismatches,
        "ungrounded": len(result.ungrounded),
        "detail": result.detail,
    }


def main():
    scenarios = load_scenarios()

    print("=" * 80)
    print("MEERKAT NUMERICAL VERIFICATION -- CLINICAL INTEGRATION TEST")
    print("=" * 80)
    print()

    # Track results by hallucination type
    results_by_type = {}
    all_results = []

    for scenario in scenarios:
        result = run_numerical_check(scenario)
        h_type = scenario["hallucination_type"]

        if h_type not in results_by_type:
            results_by_type[h_type] = {"total": 0, "detected": 0, "scenarios": []}

        results_by_type[h_type]["total"] += 1

        # For numerical_distortion type: check if we caught it
        # For other types: numerical check may or may not flag (not its job)
        expected_flags = scenario["expected_flags"]
        detected = False

        if h_type == "numerical_distortion":
            # Numerical module SHOULD catch these
            detected = (
                "critical_numerical_mismatch" in result["flags"]
                or "numerical_distortion" in result["flags"]
            )
        elif h_type == "none":
            # Clean cases: should NOT flag
            detected = result["status"] == "pass" or (
                result["critical"] == 0 and result["failing"] == 0
            )
        else:
            # Other hallucination types: numerical module may or may not help
            # Check if any expected numerical flags match
            numerical_expected = [f for f in expected_flags
                                  if "numerical" in f or "critical" in f]
            if numerical_expected:
                detected = any(f in result["flags"] for f in numerical_expected)
            else:
                detected = None  # Not applicable for this check

        if detected is not None:
            results_by_type[h_type]["detected"] += (1 if detected else 0)

        results_by_type[h_type]["scenarios"].append({
            "id": scenario["id"],
            "name": scenario["name"],
            "detected": detected,
            "result": result,
        })

        all_results.append({
            "id": scenario["id"],
            "h_type": h_type,
            "detected": detected,
            "result": result,
        })

        # Print each scenario
        status_icon = "PASS" if detected else ("N/A" if detected is None else "MISS")
        print(f"[{status_icon:4s}] {scenario['id']:8s} | {scenario['name'][:50]:50s} | "
              f"score={result['score']:.2f} status={result['status']:7s} "
              f"critical={result['critical']} flags={result['flags']}")

    # Print summary
    print()
    print("=" * 80)
    print("DETECTION RATE BY HALLUCINATION TYPE (Numerical Verification Module)")
    print("=" * 80)
    print()
    print(f"{'Type':<30s} {'Detected':>10s} {'Total':>8s} {'Rate':>8s}")
    print("-" * 60)

    for h_type in ["source_misattribution", "confident_confabulation",
                    "fabrication", "numerical_distortion", "none"]:
        if h_type not in results_by_type:
            continue
        data = results_by_type[h_type]
        rate = data["detected"] / data["total"] if data["total"] > 0 else 0
        label = h_type if h_type != "none" else "clean (no hallucination)"
        print(f"{label:<30s} {data['detected']:>10d} {data['total']:>8d} {rate:>7.0%}")

    print()
    print("=" * 80)
    print("NOTES:")
    print("- Numerical verification is designed to catch NUMERICAL DISTORTION")
    print("- Other hallucination types (source misattrib, fabrication, confab)")
    print("  are primarily caught by entailment, claim extraction, and semantic entropy")
    print("- Clean cases should produce no critical flags or failing matches")
    print("=" * 80)

    # Return exit code based on numerical distortion detection rate
    nd_data = results_by_type.get("numerical_distortion", {"detected": 0, "total": 0})
    nd_rate = nd_data["detected"] / nd_data["total"] if nd_data["total"] > 0 else 0
    clean_data = results_by_type.get("none", {"detected": 0, "total": 0})
    clean_rate = clean_data["detected"] / clean_data["total"] if clean_data["total"] > 0 else 0

    print()
    if nd_rate >= 0.75 and clean_rate >= 0.5:
        print("RESULT: PASS -- Numerical distortion detection rate >= 75%")
        return 0
    else:
        print(f"RESULT: NEEDS WORK -- ND rate: {nd_rate:.0%}, Clean rate: {clean_rate:.0%}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
