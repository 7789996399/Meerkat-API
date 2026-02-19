#!/usr/bin/env python3
"""
40-Note MIMIC Validation Pipeline (v3)

Generates 40 synthetic MIMIC-style discharge summaries, creates 3 corruption
variants per note (medication_error, lab_fabrication, diagnosis_fabrication),
and validates all 160 texts against the live claim extractor.

Endpoint: POST https://meerkat-claim-extractor.azurewebsites.net/extract
"""

import copy
import json
import os
import random
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# ── Config ────────────────────────────────────────────────────────────────
EXTRACT_URL = os.getenv(
    "EXTRACT_URL",
    "https://meerkat-claims.delightfulwave-a819ec78.canadacentral.azurecontainerapps.io/extract",
)
SEED = 42
NUM_NOTES = 40
DELAY_BETWEEN_CALLS = 0.5  # seconds
OUTPUT_DIR = Path(__file__).parent / "data"
OUTPUT_FILE = OUTPUT_DIR / "meerkat_results_v3.json"

random.seed(SEED)

# ── Clinical data pools ───────────────────────────────────────────────────

FIRST_NAMES = [
    "James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael",
    "Linda", "David", "Elizabeth", "William", "Barbara", "Richard", "Susan",
    "Joseph", "Jessica", "Thomas", "Sarah", "Charles", "Karen", "Daniel",
    "Lisa", "Matthew", "Nancy", "Anthony", "Betty", "Mark", "Margaret",
    "Donald", "Sandra", "Steven", "Ashley", "Paul", "Dorothy", "Andrew",
    "Kimberly", "Joshua", "Emily", "Kenneth", "Donna",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
    "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King",
    "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores",
]

CONDITIONS = [
    "Hypertension", "Type 2 Diabetes Mellitus", "Hyperlipidemia",
    "Coronary Artery Disease", "Atrial Fibrillation", "Heart Failure (HFrEF)",
    "Chronic Kidney Disease Stage 3", "COPD", "Asthma",
    "Gastroesophageal Reflux Disease", "Hypothyroidism",
    "Osteoarthritis", "Major Depressive Disorder", "Generalized Anxiety Disorder",
    "Obstructive Sleep Apnea", "Deep Vein Thrombosis",
    "Peripheral Artery Disease", "Iron Deficiency Anemia",
    "Chronic Low Back Pain", "Migraine",
    "Benign Prostatic Hyperplasia", "Gout",
    "Rheumatoid Arthritis", "Systemic Lupus Erythematosus",
]

# (drug_name, dose, route, frequency)
MEDICATIONS = [
    ("Metoprolol Succinate", "50mg", "PO", "daily"),
    ("Metoprolol Succinate", "100mg", "PO", "daily"),
    ("Lisinopril", "10mg", "PO", "daily"),
    ("Lisinopril", "20mg", "PO", "daily"),
    ("Amlodipine", "5mg", "PO", "daily"),
    ("Amlodipine", "10mg", "PO", "daily"),
    ("Atorvastatin", "40mg", "PO", "at bedtime"),
    ("Atorvastatin", "80mg", "PO", "at bedtime"),
    ("Metformin", "500mg", "PO", "twice daily"),
    ("Metformin", "1000mg", "PO", "twice daily"),
    ("Omeprazole", "20mg", "PO", "daily"),
    ("Omeprazole", "40mg", "PO", "daily"),
    ("Losartan", "50mg", "PO", "daily"),
    ("Losartan", "100mg", "PO", "daily"),
    ("Apixaban", "5mg", "PO", "twice daily"),
    ("Warfarin", "5mg", "PO", "daily"),
    ("Aspirin", "81mg", "PO", "daily"),
    ("Clopidogrel", "75mg", "PO", "daily"),
    ("Furosemide", "40mg", "PO", "daily"),
    ("Furosemide", "20mg", "PO", "twice daily"),
    ("Levothyroxine", "75mcg", "PO", "daily"),
    ("Levothyroxine", "100mcg", "PO", "daily"),
    ("Gabapentin", "300mg", "PO", "three times daily"),
    ("Sertraline", "50mg", "PO", "daily"),
    ("Sertraline", "100mg", "PO", "daily"),
    ("Albuterol", "2 puffs", "INH", "every 4-6 hours PRN"),
    ("Prednisone", "20mg", "PO", "daily"),
    ("Hydrochlorothiazide", "25mg", "PO", "daily"),
    ("Insulin Glargine", "20 units", "SubQ", "at bedtime"),
    ("Insulin Glargine", "30 units", "SubQ", "at bedtime"),
    ("Carvedilol", "12.5mg", "PO", "twice daily"),
    ("Carvedilol", "25mg", "PO", "twice daily"),
    ("Spironolactone", "25mg", "PO", "daily"),
    ("Tamsulosin", "0.4mg", "PO", "daily"),
    ("Allopurinol", "300mg", "PO", "daily"),
]

# (lab_name, value, unit, reference_range)
LABS = [
    ("Sodium", 138, "mEq/L", "136-145"),
    ("Sodium", 141, "mEq/L", "136-145"),
    ("Potassium", 4.2, "mEq/L", "3.5-5.0"),
    ("Potassium", 3.8, "mEq/L", "3.5-5.0"),
    ("Potassium", 4.6, "mEq/L", "3.5-5.0"),
    ("Chloride", 102, "mEq/L", "98-106"),
    ("Bicarbonate", 24, "mEq/L", "22-29"),
    ("BUN", 18, "mg/dL", "7-20"),
    ("BUN", 32, "mg/dL", "7-20"),
    ("Creatinine", 1.1, "mg/dL", "0.7-1.3"),
    ("Creatinine", 0.9, "mg/dL", "0.7-1.3"),
    ("Creatinine", 1.8, "mg/dL", "0.7-1.3"),
    ("Glucose", 110, "mg/dL", "70-100"),
    ("Glucose", 145, "mg/dL", "70-100"),
    ("Glucose", 95, "mg/dL", "70-100"),
    ("Hemoglobin", 13.5, "g/dL", "12.0-17.5"),
    ("Hemoglobin", 10.2, "g/dL", "12.0-17.5"),
    ("Hemoglobin", 14.8, "g/dL", "12.0-17.5"),
    ("WBC", 7.2, "x10^3/uL", "4.5-11.0"),
    ("WBC", 12.4, "x10^3/uL", "4.5-11.0"),
    ("Platelets", 220, "x10^3/uL", "150-400"),
    ("Platelets", 145, "x10^3/uL", "150-400"),
    ("INR", 1.0, "", "0.8-1.1"),
    ("INR", 2.3, "", "0.8-1.1"),
    ("TSH", 2.1, "mIU/L", "0.4-4.0"),
    ("TSH", 6.8, "mIU/L", "0.4-4.0"),
    ("HbA1c", 7.2, "%", "<5.7 normal"),
    ("HbA1c", 6.1, "%", "<5.7 normal"),
    ("Albumin", 3.8, "g/dL", "3.5-5.5"),
    ("Albumin", 2.9, "g/dL", "3.5-5.5"),
    ("ALT", 25, "U/L", "7-56"),
    ("AST", 30, "U/L", "10-40"),
    ("Total Bilirubin", 0.8, "mg/dL", "0.1-1.2"),
    ("Troponin I", 0.02, "ng/mL", "<0.04"),
    ("BNP", 150, "pg/mL", "<100"),
    ("BNP", 450, "pg/mL", "<100"),
    ("Magnesium", 2.0, "mg/dL", "1.7-2.2"),
    ("Calcium", 9.2, "mg/dL", "8.5-10.5"),
    ("Phosphorus", 3.5, "mg/dL", "2.5-4.5"),
    ("eGFR", 65, "mL/min/1.73m2", ">60"),
    ("eGFR", 42, "mL/min/1.73m2", ">60"),
    ("Lactate", 1.2, "mmol/L", "0.5-2.0"),
]

DIAGNOSES = [
    "Acute on chronic systolic heart failure",
    "Non-ST elevation myocardial infarction",
    "Community-acquired pneumonia",
    "Acute kidney injury",
    "Diabetic ketoacidosis",
    "Pulmonary embolism",
    "Acute exacerbation of COPD",
    "Urinary tract infection",
    "Cellulitis of the right lower extremity",
    "Hypertensive urgency",
    "Atrial fibrillation with rapid ventricular response",
    "Acute pancreatitis",
    "Upper gastrointestinal bleeding",
    "Sepsis secondary to pneumonia",
    "Syncope",
    "Transient ischemic attack",
    "Deep vein thrombosis, left lower extremity",
    "Hyperkalemia",
    "Hypoglycemia",
    "Decompensated cirrhosis",
]

ASSESSMENT_TEMPLATES = [
    "{age} y/o {gender} admitted for {dx1}. Hospital course was uncomplicated. "
    "{dx1} was managed with {med1} and {med2}. Discharge labs showed {lab1_name} "
    "of {lab1_val} {lab1_unit}. Patient is hemodynamically stable and ready for discharge.",

    "Patient is a {age} year old {gender} who presented with {dx1} in the setting of "
    "{pmh1}. Treated with {med1} with good clinical response. "
    "{lab1_name} improved from admission to {lab1_val} {lab1_unit} at discharge. "
    "Follow-up with PCP in 1-2 weeks.",

    "{age} y/o {gender} with history of {pmh1} and {pmh2} admitted for {dx1}. "
    "Medications were optimized during this admission. Discharging on {med1}, "
    "{med2}, and {med3}. {lab1_name} at discharge: {lab1_val} {lab1_unit}. "
    "Patient educated on medication adherence and warning signs.",

    "This {age} year old {gender} was admitted with {dx1}. Workup revealed {lab1_name} "
    "{lab1_val} {lab1_unit} and {lab2_name} {lab2_val} {lab2_unit}. Managed conservatively "
    "with {med1}. Condition stabilized. Discharge to home with outpatient follow-up.",
]

# Drugs that are never in the MEDICATIONS pool -- used for corruption swaps
SWAP_DRUGS = [
    ("Diltiazem", "120mg", "PO", "daily"),
    ("Verapamil", "80mg", "PO", "three times daily"),
    ("Doxazosin", "4mg", "PO", "at bedtime"),
    ("Clonidine", "0.1mg", "PO", "twice daily"),
    ("Nifedipine", "30mg", "PO", "daily"),
    ("Phenytoin", "100mg", "PO", "three times daily"),
    ("Lithium", "300mg", "PO", "twice daily"),
    ("Valproic Acid", "500mg", "PO", "twice daily"),
    ("Chlorthalidone", "25mg", "PO", "daily"),
    ("Dapagliflozin", "10mg", "PO", "daily"),
]


# ── Note generation ───────────────────────────────────────────────────────

def generate_note(note_id: int) -> dict:
    """Generate a single MIMIC-style discharge summary. Returns metadata + text."""
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    age = random.randint(35, 88)
    gender = random.choice(["male", "female"])
    mrn = f"{random.randint(100000, 999999)}"

    # Pick 2-4 PMH conditions (no duplicates)
    pmh = random.sample(CONDITIONS, random.randint(2, 4))

    # Pick 3-5 medications (unique drug names)
    seen_drugs = set()
    meds = []
    pool = list(MEDICATIONS)
    random.shuffle(pool)
    for m in pool:
        if m[0] not in seen_drugs and len(meds) < random.randint(3, 5):
            meds.append(m)
            seen_drugs.add(m[0])

    # Pick 5-8 lab values (unique lab names)
    seen_labs = set()
    labs = []
    pool = list(LABS)
    random.shuffle(pool)
    for lb in pool:
        if lb[0] not in seen_labs and len(labs) < random.randint(5, 8):
            labs.append(lb)
            seen_labs.add(lb[0])

    # Vitals
    sys_bp = random.randint(110, 155)
    dia_bp = random.randint(60, 90)
    hr = random.randint(62, 100)
    rr = random.randint(14, 22)
    temp = round(random.uniform(97.6, 99.2), 1)
    spo2 = random.randint(94, 100)

    # Discharge diagnoses (1-2)
    dxs = random.sample(DIAGNOSES, random.randint(1, 2))

    # Assessment
    tmpl = random.choice(ASSESSMENT_TEMPLATES)
    assessment = tmpl.format(
        age=age,
        gender=gender,
        dx1=dxs[0],
        pmh1=pmh[0],
        pmh2=pmh[1] if len(pmh) > 1 else pmh[0],
        med1=f"{meds[0][0]} {meds[0][1]}",
        med2=f"{meds[1][0]} {meds[1][1]}" if len(meds) > 1 else f"{meds[0][0]} {meds[0][1]}",
        med3=f"{meds[2][0]} {meds[2][1]}" if len(meds) > 2 else f"{meds[0][0]} {meds[0][1]}",
        lab1_name=labs[0][0],
        lab1_val=labs[0][1],
        lab1_unit=labs[0][2],
        lab2_name=labs[1][0] if len(labs) > 1 else labs[0][0],
        lab2_val=labs[1][1] if len(labs) > 1 else labs[0][1],
        lab2_unit=labs[1][2] if len(labs) > 1 else labs[0][2],
    )

    # Build note text
    lines = [
        "DISCHARGE SUMMARY",
        f"Patient: {first} {last}, {age} y/o {gender}",
        f"MRN: {mrn}",
        "",
        "PAST MEDICAL HISTORY:",
    ]
    for c in pmh:
        lines.append(f"- {c}")
    lines.append("")
    lines.append("MEDICATIONS ON ADMISSION:")
    for drug, dose, route, freq in meds:
        lines.append(f"- {drug} {dose} {route} {freq}")
    lines.append("")
    lines.append("LABORATORY VALUES:")
    for name, val, unit, ref in labs:
        lines.append(f"- {name}: {val} {unit} (ref: {ref})")
    lines.append("")
    lines.append("VITAL SIGNS ON DISCHARGE:")
    lines.append(f"- BP: {sys_bp}/{dia_bp} mmHg")
    lines.append(f"- HR: {hr} bpm")
    lines.append(f"- RR: {rr} breaths/min")
    lines.append(f"- Temp: {temp} F")
    lines.append(f"- SpO2: {spo2}%")
    lines.append("")
    lines.append("DISCHARGE DIAGNOSES:")
    for i, dx in enumerate(dxs, 1):
        lines.append(f"{i}. {dx}")
    lines.append("")
    lines.append("ASSESSMENT AND PLAN:")
    lines.append(assessment)

    text = "\n".join(lines)

    return {
        "note_id": note_id,
        "text": text,
        "meds": meds,
        "labs": labs,
        "diagnoses": dxs,
        "pmh": pmh,
    }


# ── Corruption functions ──────────────────────────────────────────────────

def corrupt_medication(note: dict) -> tuple[str, str]:
    """Swap one drug name for a different drug not in the source."""
    text = note["text"]
    meds = note["meds"]
    if not meds:
        return text, "no_meds_to_corrupt"

    target = random.choice(meds)
    target_name = target[0]

    # Pick a swap drug whose name isn't already in the note
    note_drug_names = {m[0] for m in meds}
    candidates = [s for s in SWAP_DRUGS if s[0] not in note_drug_names]
    if not candidates:
        candidates = SWAP_DRUGS

    if random.random() < 0.5:
        # Strategy A: swap drug name entirely
        swap = random.choice(candidates)
        corrupted = text.replace(target_name, swap[0])
        detail = f"swapped {target_name} -> {swap[0]}"
    else:
        # Strategy B: change dose by 2-10x
        old_dose = target[1]
        # Extract numeric part
        num_str = ""
        unit_str = ""
        for ch in old_dose:
            if ch.isdigit() or ch == ".":
                num_str += ch
            else:
                unit_str = old_dose[len(num_str):]
                break
        if num_str:
            old_num = float(num_str)
            multiplier = random.choice([2, 3, 5, 10])
            new_num = old_num * multiplier
            if new_num == int(new_num):
                new_num = int(new_num)
            new_dose = f"{new_num}{unit_str}"
            corrupted = text.replace(
                f"{target_name} {old_dose}",
                f"{target_name} {new_dose}",
            )
            detail = f"dose {target_name} {old_dose} -> {new_dose}"
        else:
            swap = random.choice(candidates)
            corrupted = text.replace(target_name, swap[0])
            detail = f"swapped {target_name} -> {swap[0]}"

    return corrupted, detail


def corrupt_lab(note: dict) -> tuple[str, str]:
    """Replace 1-2 lab values with clinically different numbers."""
    text = note["text"]
    labs = note["labs"]
    if not labs:
        return text, "no_labs_to_corrupt"

    num_to_corrupt = random.randint(1, min(2, len(labs)))
    targets = random.sample(labs, num_to_corrupt)
    details = []

    for name, val, unit, ref in targets:
        # Generate a clinically different value
        if isinstance(val, float):
            if val < 1:
                new_val = round(val * random.uniform(3.0, 10.0), 2)
            else:
                new_val = round(val * random.uniform(1.5, 2.5), 1)
        else:
            new_val = int(val * random.uniform(1.5, 3.0))

        old_str = f"{name}: {val} {unit}".strip()
        new_str = f"{name}: {new_val} {unit}".strip()
        text = text.replace(old_str, new_str)

        # Also replace any mention in the assessment section
        old_val_str = f"{name} {val} {unit}".strip()
        new_val_str = f"{name} {new_val} {unit}".strip()
        text = text.replace(old_val_str, new_val_str)

        # Plain value references like "of 4.2 mEq/L"
        old_ref = f"{val} {unit}".strip()
        new_ref = f"{new_val} {unit}".strip()
        # Only replace in assessment area (after ASSESSMENT AND PLAN:)
        parts = text.split("ASSESSMENT AND PLAN:")
        if len(parts) == 2:
            parts[1] = parts[1].replace(old_ref, new_ref, 1)
            text = "ASSESSMENT AND PLAN:".join(parts)

        details.append(f"{name} {val}->{new_val}")

    return text, "; ".join(details)


def corrupt_diagnosis(note: dict) -> tuple[str, str]:
    """Add a fabricated diagnosis or swap one for an unrelated one."""
    text = note["text"]
    dxs = note["diagnoses"]
    if not dxs:
        return text, "no_dx_to_corrupt"

    # Pick a diagnosis NOT already in the note
    current_set = set(dxs) | set(note["pmh"])
    candidates = [d for d in DIAGNOSES if d not in current_set]
    if not candidates:
        candidates = DIAGNOSES

    fake_dx = random.choice(candidates)

    if random.random() < 0.5 and len(dxs) >= 1:
        # Strategy A: swap existing diagnosis
        target = random.choice(dxs)
        corrupted = text.replace(target, fake_dx)
        detail = f"swapped dx: {target} -> {fake_dx}"
    else:
        # Strategy B: add a fabricated diagnosis
        # Find the last diagnosis line and add after it
        lines = text.split("\n")
        last_dx_idx = None
        dx_count = 0
        for i, line in enumerate(lines):
            if line and line[0].isdigit() and "." in line[:3]:
                last_dx_idx = i
                dx_count += 1
        if last_dx_idx is not None:
            new_line = f"{dx_count + 1}. {fake_dx}"
            lines.insert(last_dx_idx + 1, new_line)
            corrupted = "\n".join(lines)
            detail = f"added fabricated dx: {fake_dx}"
        else:
            corrupted = text.replace(dxs[0], fake_dx)
            detail = f"swapped dx: {dxs[0]} -> {fake_dx}"

    return corrupted, detail


# ── API caller ────────────────────────────────────────────────────────────

def call_extract(ai_output: str, source: str) -> dict:
    """POST to the claim extractor and return the parsed JSON response."""
    payload = json.dumps({
        "ai_output": ai_output,
        "source": source,
    }).encode("utf-8")

    req = Request(
        EXTRACT_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"error": f"HTTP {e.code}: {body[:200]}"}
    except URLError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}


# ── Trust score ───────────────────────────────────────────────────────────

def compute_trust_score(resp: dict) -> float:
    """trust_score = verified / max(total_claims, 1), clamped to [0, 1]."""
    if "error" in resp:
        return 0.0
    total = resp.get("total_claims", 0)
    verified = resp.get("verified", 0)
    score = verified / max(total, 1)
    return max(0.0, min(1.0, score))


def avg_entailment(resp: dict) -> float:
    """Average entailment_score across all claims."""
    claims = resp.get("claims", [])
    if not claims:
        return 0.0
    scores = [c.get("entailment_score", 0.0) for c in claims]
    return sum(scores) / len(scores)


# ── Main pipeline ─────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("  MIMIC Validation Pipeline v3  —  40 notes × 4 variants = 160 calls")
    print(f"  Endpoint: {EXTRACT_URL}")
    print("=" * 70)
    print()

    # Step 1: Generate notes
    print(f"[1/5] Generating {NUM_NOTES} synthetic discharge summaries...")
    notes = [generate_note(i) for i in range(NUM_NOTES)]
    print(f"       Done. {len(notes)} notes generated.\n")

    # Step 2: Create variants
    print("[2/5] Creating corruption variants...")
    variants = []
    for note in notes:
        # Original
        variants.append({
            "note_id": note["note_id"],
            "variant": "original",
            "ai_output": note["text"],
            "source": note["text"],
            "corruption_detail": "none",
        })
        # Medication error
        corrupted_text, detail = corrupt_medication(note)
        variants.append({
            "note_id": note["note_id"],
            "variant": "medication_error",
            "ai_output": corrupted_text,
            "source": note["text"],
            "corruption_detail": detail,
        })
        # Lab fabrication
        corrupted_text, detail = corrupt_lab(note)
        variants.append({
            "note_id": note["note_id"],
            "variant": "lab_fabrication",
            "ai_output": corrupted_text,
            "source": note["text"],
            "corruption_detail": detail,
        })
        # Diagnosis fabrication
        corrupted_text, detail = corrupt_diagnosis(note)
        variants.append({
            "note_id": note["note_id"],
            "variant": "diagnosis_fabrication",
            "ai_output": corrupted_text,
            "source": note["text"],
            "corruption_detail": detail,
        })

    print(f"       {len(variants)} variants created ({NUM_NOTES} × 4).\n")

    # Step 3: Call claim extractor
    print(f"[3/5] Calling claim extractor ({len(variants)} requests)...")
    results = []
    errors = 0
    for i, v in enumerate(variants):
        resp = call_extract(v["ai_output"], v["source"])
        ts = compute_trust_score(resp)
        ae = avg_entailment(resp)

        result = {
            "note_id": v["note_id"],
            "variant": v["variant"],
            "corruption_detail": v["corruption_detail"],
            "trust_score": round(ts, 4),
            "avg_entailment": round(ae, 4),
            "response": resp,
        }
        results.append(result)

        if "error" in resp:
            errors += 1

        # Progress
        done = i + 1
        if done % 10 == 0 or done == len(variants):
            print(f"       {done}/{len(variants)} complete "
                  f"({errors} errors so far)")

        if i < len(variants) - 1:
            time.sleep(DELAY_BETWEEN_CALLS)

    print()

    # Step 4: Save results
    print("[4/5] Saving results...")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=2)
    print(f"       Saved to {OUTPUT_FILE}\n")

    # Step 5: Summary
    print("[5/5] Computing summary...\n")
    print_summary(results)


def print_summary(results: list[dict]):
    """Print summary statistics."""
    by_variant = {}
    for r in results:
        v = r["variant"]
        if v not in by_variant:
            by_variant[v] = []
        by_variant[v].append(r)

    variant_order = ["original", "medication_error", "lab_fabrication", "diagnosis_fabrication"]

    # Averages
    print("=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    print()
    print(f"{'Variant':<25} {'Avg Trust':>10} {'Avg Entail':>11} "
          f"{'Avg Claims':>11} {'Avg Verif':>10} {'Avg Contr':>10} {'Avg Ungr':>9}")
    print("-" * 86)

    orig_trust = 0.0
    for v in variant_order:
        group = by_variant.get(v, [])
        if not group:
            continue
        avg_ts = sum(r["trust_score"] for r in group) / len(group)
        avg_ae = sum(r["avg_entailment"] for r in group) / len(group)
        avg_claims = sum(r["response"].get("total_claims", 0) for r in group) / len(group)
        avg_verified = sum(r["response"].get("verified", 0) for r in group) / len(group)
        avg_contradicted = sum(r["response"].get("contradicted", 0) for r in group) / len(group)
        avg_ungrounded = sum(r["response"].get("ungrounded", 0) for r in group) / len(group)

        if v == "original":
            orig_trust = avg_ts

        print(f"{v:<25} {avg_ts:>10.4f} {avg_ae:>11.4f} "
              f"{avg_claims:>11.1f} {avg_verified:>10.1f} {avg_contradicted:>10.1f} {avg_ungrounded:>9.1f}")

    # Deltas
    print()
    print(f"{'Variant':<25} {'Delta Trust':>12} {'Detection Rate':>15} ")
    print("-" * 55)
    for v in variant_order:
        if v == "original":
            continue
        group = by_variant.get(v, [])
        if not group:
            continue
        avg_ts = sum(r["trust_score"] for r in group) / len(group)
        delta = avg_ts - orig_trust

        # Detection rate: % of corrupted notes scoring strictly lower than their original
        detected = 0
        for r in group:
            orig = next(
                (o for o in by_variant["original"] if o["note_id"] == r["note_id"]),
                None,
            )
            if orig and r["trust_score"] < orig["trust_score"]:
                detected += 1
        det_rate = detected / len(group) * 100

        print(f"{v:<25} {delta:>+12.4f} {det_rate:>14.1f}%")

    # False positive rate
    orig_group = by_variant.get("original", [])
    if orig_group:
        fp = sum(1 for r in orig_group if r["trust_score"] < 0.5)
        fp_rate = fp / len(orig_group) * 100
        print()
        print(f"False positive rate (original trust < 0.5): "
              f"{fp}/{len(orig_group)} = {fp_rate:.1f}%")

    # Error count
    error_count = sum(1 for r in results if "error" in r["response"])
    if error_count:
        print(f"\nAPI errors: {error_count}/{len(results)}")

    print()
    print("=" * 70)


if __name__ == "__main__":
    main()
