#!/usr/bin/env python3
"""
Gateway Validation Pipeline — 40 notes × 4 variants through /v1/verify

Tests the full production pipeline (numerical_verify + claim_extraction +
implicit_preference) via the meerkat-node gateway at api.meerkatplatform.com.

Reuses the same 40 MIMIC-style notes from run_validation.py (same seed).
"""

import json
import os
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# Import note generation + corruption from the sibling module
sys.path.insert(0, str(Path(__file__).parent))
from run_validation import (
    generate_note,
    corrupt_medication,
    corrupt_lab,
    corrupt_diagnosis,
    NUM_NOTES,
    SEED,
)
import random

# ── Config ────────────────────────────────────────────────────────────────
GATEWAY_URL = os.getenv(
    "GATEWAY_URL",
    "https://api.meerkatplatform.com/v1/verify",
)
API_KEY = os.getenv(
    "MEERKAT_API_KEY",
    "mk_live_94378e48-cfc8-472d-8286-8b0c4ff0de33",
)
DELAY_BETWEEN_CALLS = 1.0  # 1 req/s rate limit
OUTPUT_DIR = Path(__file__).parent / "data"
OUTPUT_FILE = OUTPUT_DIR / "gateway_results_v1.json"

# ── Regenerate identical notes (same seed) ────────────────────────────────

def build_variants() -> list[dict]:
    """Regenerate the exact same 40 notes + 4 variants using the fixed seed."""
    random.seed(SEED)
    notes = [generate_note(i) for i in range(NUM_NOTES)]

    variants = []
    for note in notes:
        variants.append({
            "note_id": note["note_id"],
            "variant": "original",
            "ai_output": note["text"],
            "source": note["text"],
            "corruption_detail": "none",
        })
        corrupted_text, detail = corrupt_medication(note)
        variants.append({
            "note_id": note["note_id"],
            "variant": "medication_error",
            "ai_output": corrupted_text,
            "source": note["text"],
            "corruption_detail": detail,
        })
        corrupted_text, detail = corrupt_lab(note)
        variants.append({
            "note_id": note["note_id"],
            "variant": "lab_fabrication",
            "ai_output": corrupted_text,
            "source": note["text"],
            "corruption_detail": detail,
        })
        corrupted_text, detail = corrupt_diagnosis(note)
        variants.append({
            "note_id": note["note_id"],
            "variant": "diagnosis_fabrication",
            "ai_output": corrupted_text,
            "source": note["text"],
            "corruption_detail": detail,
        })
    return variants


# ── API caller ────────────────────────────────────────────────────────────

def call_verify(ai_output: str, source: str) -> dict:
    """POST to the gateway /v1/verify endpoint."""
    payload = json.dumps({
        "input": "Summarize the clinical note",
        "output": ai_output,
        "context": source,
        "domain": "healthcare",
    }).encode("utf-8")

    req = Request(
        GATEWAY_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
        method="POST",
    )

    try:
        with urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"error": f"HTTP {e.code}: {body[:300]}"}
    except URLError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}


# ── Main pipeline ─────────────────────────────────────────────────────────

def main():
    print("=" * 72)
    print("  Gateway Validation Pipeline — 40 notes × 4 variants = 160 calls")
    print(f"  Endpoint: {GATEWAY_URL}")
    print("=" * 72)
    print()

    # Step 1: Build variants (deterministic, same seed)
    print("[1/4] Regenerating 40 notes + corruption variants (seed=42)...")
    variants = build_variants()
    print(f"       {len(variants)} variants ready.\n")

    # Step 2: Call gateway
    print(f"[2/4] Calling /v1/verify ({len(variants)} requests, ~1 req/s)...")
    results = []
    errors = 0
    for i, v in enumerate(variants):
        resp = call_verify(v["ai_output"], v["source"])

        result = {
            "note_id": v["note_id"],
            "variant": v["variant"],
            "corruption_detail": v["corruption_detail"],
            "trust_score": resp.get("trust_score", 0),
            "status": resp.get("status", "ERROR"),
            "checks": resp.get("checks", {}),
            "audit_id": resp.get("audit_id", ""),
            "verification_mode": resp.get("verification_mode", ""),
            "recommendations": resp.get("recommendations", []),
        }
        results.append(result)

        if "error" in resp:
            errors += 1

        done = i + 1
        if done % 10 == 0 or done == len(variants):
            print(f"       {done}/{len(variants)} complete "
                  f"({errors} errors so far)")

        if i < len(variants) - 1:
            time.sleep(DELAY_BETWEEN_CALLS)

    print()

    # Step 3: Save results
    print("[3/4] Saving results...")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=2)
    print(f"       Saved to {OUTPUT_FILE}\n")

    # Step 4: Summary
    print("[4/4] Computing summary...\n")
    print_summary(results)


def print_summary(results: list[dict]):
    """Print summary statistics."""
    by_variant: dict[str, list[dict]] = {}
    for r in results:
        by_variant.setdefault(r["variant"], []).append(r)

    variant_order = ["original", "medication_error", "lab_fabrication", "diagnosis_fabrication"]

    # ── 1. Average trust score per variant ────────────────────────────
    print("=" * 72)
    print("  SUMMARY")
    print("=" * 72)
    print()
    print("1. Average trust score per variant")
    print("-" * 72)
    print(f"  {'Variant':<25} {'Avg Trust':>10} {'Avg Numer':>10} "
          f"{'Avg Claims':>11} {'Avg Pref':>9}")
    print(f"  {'-'*25} {'-'*10} {'-'*10} {'-'*11} {'-'*9}")

    orig_trust = 0.0
    for v in variant_order:
        group = by_variant.get(v, [])
        if not group:
            continue
        avg_ts = sum(r["trust_score"] for r in group) / len(group)
        avg_num = sum(
            r["checks"].get("numerical_verify", {}).get("score", 0)
            for r in group
        ) / len(group)
        avg_claims = sum(
            r["checks"].get("claim_extraction", {}).get("score", 0)
            for r in group
        ) / len(group)
        avg_pref = sum(
            r["checks"].get("implicit_preference", {}).get("score", 0)
            for r in group
        ) / len(group)

        if v == "original":
            orig_trust = avg_ts

        print(f"  {v:<25} {avg_ts:>10.1f} {avg_num:>10.4f} "
              f"{avg_claims:>11.4f} {avg_pref:>9.4f}")

    # ── 2. Status distribution per variant ────────────────────────────
    print()
    print("2. Status distribution per variant")
    print("-" * 72)
    print(f"  {'Variant':<25} {'PASS':>6} {'FLAG':>6} {'BLOCK':>7} {'ERROR':>7}")
    print(f"  {'-'*25} {'-'*6} {'-'*6} {'-'*7} {'-'*7}")

    for v in variant_order:
        group = by_variant.get(v, [])
        if not group:
            continue
        counts = {"PASS": 0, "FLAG": 0, "BLOCK": 0, "ERROR": 0}
        for r in group:
            s = r["status"]
            if s in counts:
                counts[s] += 1
            else:
                counts["ERROR"] += 1
        print(f"  {v:<25} {counts['PASS']:>6} {counts['FLAG']:>6} "
              f"{counts['BLOCK']:>7} {counts['ERROR']:>7}")

    # ── 3. Detection rate ─────────────────────────────────────────────
    print()
    print("3. Detection rate (% of corrupted scoring lower than their original)")
    print("-" * 72)

    for v in variant_order:
        if v == "original":
            continue
        group = by_variant.get(v, [])
        if not group:
            continue
        detected = 0
        for r in group:
            orig = next(
                (o for o in by_variant["original"] if o["note_id"] == r["note_id"]),
                None,
            )
            if orig and r["trust_score"] < orig["trust_score"]:
                detected += 1
        det_rate = detected / len(group) * 100
        avg_delta = (
            sum(r["trust_score"] for r in group) / len(group) - orig_trust
        )
        print(f"  {v:<25} {det_rate:>5.1f}%  (delta {avg_delta:>+.1f} pts)")

    # ── 4. False positive rate ────────────────────────────────────────
    print()
    print("4. False positive rate (originals that got BLOCK)")
    print("-" * 72)
    orig_group = by_variant.get("original", [])
    if orig_group:
        fp = sum(1 for r in orig_group if r["status"] == "BLOCK")
        fp_rate = fp / len(orig_group) * 100
        print(f"  {fp}/{len(orig_group)} = {fp_rate:.1f}%")

    # ── 5. Which check caught each corruption ─────────────────────────
    print()
    print("5. Which check caught each corruption type")
    print("-" * 72)
    print(f"  {'Variant':<25} {'Numer Only':>11} {'Claims Only':>12} "
          f"{'Both':>6} {'Neither':>8}")
    print(f"  {'-'*25} {'-'*11} {'-'*12} {'-'*6} {'-'*8}")

    for v in variant_order:
        if v == "original":
            continue
        group = by_variant.get(v, [])
        if not group:
            continue

        numer_only = 0
        claims_only = 0
        both = 0
        neither = 0

        for r in group:
            orig = next(
                (o for o in by_variant["original"] if o["note_id"] == r["note_id"]),
                None,
            )
            if not orig:
                continue

            # Check if numerical score dropped
            orig_num = orig["checks"].get("numerical_verify", {}).get("score", 0)
            curr_num = r["checks"].get("numerical_verify", {}).get("score", 0)
            num_caught = curr_num < orig_num

            # Check if claims score dropped
            orig_cl = orig["checks"].get("claim_extraction", {}).get("score", 0)
            curr_cl = r["checks"].get("claim_extraction", {}).get("score", 0)
            cl_caught = curr_cl < orig_cl

            if num_caught and cl_caught:
                both += 1
            elif num_caught:
                numer_only += 1
            elif cl_caught:
                claims_only += 1
            else:
                neither += 1

        print(f"  {v:<25} {numer_only:>11} {claims_only:>12} "
              f"{both:>6} {neither:>8}")

    # ── Errors ────────────────────────────────────────────────────────
    error_count = sum(1 for r in results if r["status"] == "ERROR")
    if error_count:
        print(f"\nAPI errors: {error_count}/{len(results)}")

    print()
    print("=" * 72)


if __name__ == "__main__":
    main()
