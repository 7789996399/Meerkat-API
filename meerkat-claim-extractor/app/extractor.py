"""
Claim extraction using spaCy en_core_web_sm.

Identifies verifiable factual claims based on:
- Named entities (PERSON, ORG, DATE, MONEY, PERCENT, CARDINAL, etc.)
- Specific numbers or measurements
- Causal assertions ("causes", "requires", "leads to")
- Legal/medical/financial assertions
- Medical content: demographics, diagnoses, medications, lab values,
  procedures, vital signs, temporal claims
"""

import re
import spacy

_nlp = None

# ── spaCy NER entity types that indicate a factual claim ──────────

FACTUAL_ENTITY_TYPES = {
    "PERSON", "ORG", "GPE", "DATE", "TIME", "MONEY", "PERCENT",
    "CARDINAL", "ORDINAL", "QUANTITY", "LAW", "PRODUCT", "EVENT",
    "NORP", "FAC", "LOC", "WORK_OF_ART",
}

# ── Causal assertion patterns ─────────────────────────────────────

CAUSAL_PATTERNS = [
    r"\b(?:causes?|caused|causing)\b",
    r"\b(?:requires?|required|requiring)\b",
    r"\b(?:leads?\s+to|led\s+to|leading\s+to)\b",
    r"\b(?:results?\s+in|resulted\s+in|resulting\s+in)\b",
    r"\b(?:due\s+to|because\s+of|as\s+a\s+result\s+of)\b",
    r"\b(?:therefore|consequently|hence|thus)\b",
    r"\b(?:if\s+.+then)\b",
]

# ── Legal/financial assertion patterns ────────────────────────────

DOMAIN_ASSERTION_PATTERNS = [
    # Legal
    r"\bis\s+(?:enforceable|binding|prohibited|unlawful|lawful|permitted)\b",
    r"\b(?:in\s+(?:breach|violation|compliance|accordance))\b",
    r"\b(?:shall|must\s+not|is\s+required\s+to)\b",
    # Financial
    r"\b(?:exceeds?\s+(?:threshold|limit|target|benchmark))\b",
    r"\b(?:increased|decreased|grew|declined)\s+(?:by|to)\s+\d",
    r"\b(?:valued\s+at|priced\s+at|worth)\b",
]

# ── Medical patterns ──────────────────────────────────────────────

MEDICAL_PATTERNS = [
    # --- Demographics ---
    r"\b\d+[\s-]*year[\s-]*old\b",
    r"\bage\s+(?:of\s+)?\d+\b",
    r"\b(?:male|female|man|woman|boy|girl|infant|neonate|adolescent)\b",

    # --- Diagnoses / conditions (verb phrases) ---
    r"\b(?:diagnosed\s+with|presents?\s+with|presented\s+with|"
    r"history\s+of|h/o|hx\s+of|"
    r"suffers?\s+from|suffering\s+from|"
    r"complains?\s+of|complaining\s+of|c/o|"
    r"positive\s+for|negative\s+for|"
    r"tested\s+(?:positive|negative)|"
    r"confirmed|ruled\s+out|"
    r"consistent\s+with|suggestive\s+of|indicative\s+of|compatible\s+with|"
    r"known\s+case\s+of|known\s+to\s+have)\b",

    # "patient/he/she has [condition]" — anchored to subject
    r"\b(?:patient|pt|he|she|individual|subject|client|mr|mrs|ms)\s+"
    r"(?:has|had|have|exhibits?|displays?|shows?|demonstrates?|developed|"
    r"is\s+(?:a|an)\s+\w+\s+(?:with|who)|"
    r"was\s+(?:found|noted|observed)\s+to)\b",

    # Condition terms (diseases, syndromes, common medical suffixes)
    r"\b\w*(?:itis|osis|emia|penia|uria|trophy|plasia|pathy|"
    r"ectomy|otomy|ostomy|plasty|scopy|graphy|algia|plegia|paresis)\b",
    r"\b(?:diabetes|hypertension|hypotension|cancer|carcinoma|"
    r"melanoma|lymphoma|leukemia|anemia|anaemia|pneumonia|"
    r"asthma|copd|chf|cad|ckd|esrd|dvt|pe|ards|"
    r"sepsis|septic|infection|fracture|hemorrhage|haemorrhage|"
    r"edema|oedema|fibrosis|stenosis|thrombosis|embolism|infarction|"
    r"ischemia|ischaemia|obesity|malnutrition|dehydration|"
    r"arrhythmia|fibrillation|flutter|tachycardia|bradycardia|"
    r"epilepsy|seizure|stroke|dementia|alzheimer|parkinson|"
    r"cirrhosis|hepatitis|pancreatitis|cholecystitis|"
    r"depression|anxiety|schizophrenia|bipolar|"
    r"osteoporosis|arthritis|lupus|"
    r"hiv|aids|covid|tuberculosis|tb|mrsa|uti|"
    r"uncontrolled|poorly\s+controlled|well[\s-]controlled|"
    r"type\s+(?:1|2|i|ii|iii|iv)\s+\w+|"
    r"stage\s+(?:1|2|3|4|i|ii|iii|iv)|"
    r"grade\s+(?:1|2|3|4|i|ii|iii|iv))\b",

    # --- Medications ---
    r"\b(?:prescribed|prescribing|taking|on|started\s+on|receiving|"
    r"administered|given|treated\s+with|discontinued|"
    r"dose(?:d|s)?(?:\s+(?:at|of|with))?|titrated|switched\s+to|"
    r"allergic\s+to|intolerant\s+to|"
    r"medication|medications|regimen|therapy|prophylaxis)\b",
    # Drug name suffixes
    r"\b\w+(?:mab|nib|zole|pine|mine|pril|olol|statin|sartan|"
    r"dipine|floxacin|mycin|cillin|azepam|codone|phen|"
    r"formin|gliptin|tide|mide|oxide|azole|navir|vudine)\b",
    # Common drug names
    r"\b(?:metformin|insulin|aspirin|warfarin|heparin|enoxaparin|"
    r"lisinopril|losartan|amlodipine|metoprolol|atenolol|carvedilol|"
    r"atorvastatin|simvastatin|rosuvastatin|"
    r"omeprazole|pantoprazole|lansoprazole|"
    r"acetaminophen|tylenol|ibuprofen|naproxen|"
    r"prednisone|prednisolone|dexamethasone|hydrocortisone|"
    r"furosemide|hydrochlorothiazide|spironolactone|"
    r"amoxicillin|azithromycin|ciprofloxacin|vancomycin|"
    r"levothyroxine|gabapentin|pregabalin|"
    r"sertraline|fluoxetine|escitalopram|duloxetine|"
    r"morphine|oxycodone|fentanyl|tramadol|"
    r"albuterol|ipratropium|tiotropium|"
    r"clopidogrel|apixaban|rivaroxaban|dabigatran)\b",

    # --- Lab values ---
    r"\b(?:hemoglobin|hgb|hb|hba1c|a1c|glucose|fasting\s+glucose|"
    r"creatinine|cr|bun|gfr|egfr|"
    r"sodium|na|potassium|k\+?|calcium|ca|magnesium|mg|phosph|"
    r"platelets?|plt|wbc|rbc|hematocrit|hct|mcv|mch|mchc|"
    r"inr|pt|ptt|aptt|"
    r"troponin|bnp|nt-?probnp|ck|cpk|"
    r"albumin|bilirubin|alt|ast|alp|ggt|"
    r"ldl|hdl|total\s+cholesterol|triglycerides?|"
    r"tsh|t3|t4|free\s+t4|"
    r"psa|cea|afp|ca[\s-]?125|ca[\s-]?19|"
    r"ferritin|iron|tibc|transferrin|"
    r"lactate|d[\s-]?dimer|fibrinogen|"
    r"urine|urinalysis|ua|serum|plasma|blood\s+gas|abg)\s*"
    r"(?:of|is|was|=|:|level|levels|count|result|value)?\s*\d",

    # --- Vital signs ---
    r"\b(?:blood\s+pressure|bp|systolic|diastolic|"
    r"heart\s+rate|hr|pulse|"
    r"temperature|temp|febrile|afebrile|"
    r"respiratory\s+rate|rr|respirations|"
    r"oxygen\s+saturation|spo2|o2\s+sat|sats|"
    r"bmi|body\s+mass\s+index|"
    r"weight|height)\s*(?:of|is|was|=|:)?\s*\d",
    r"\b\d{2,3}\s*/\s*\d{2,3}\s*(?:mmhg|mm\s*hg)?\b",

    # --- Procedures ---
    r"\b(?:underwent|undergoing|performed|scheduled\s+for|"
    r"status\s+post|s/p|post[\s-]?op(?:erative)?|pre[\s-]?op(?:erative)?|"
    r"surgery|surgical|operation|"
    r"biopsy|catheter(?:ization)?|intubat(?:ed|ion)|extubat(?:ed|ion)|"
    r"dialysis|hemodialysis|transfus(?:ed|ion)|ventilat(?:ed|ion)|"
    r"resect(?:ed|ion)|excis(?:ed|ion)|implant(?:ed|ation)|"
    r"endoscopy|colonoscopy|bronchoscopy|"
    r"mri|ct\s+scan|x[\s-]?ray|ultrasound|echocardiogram|ekg|ecg|eeg|"
    r"angiography|angioplasty|stent(?:ing)?|bypass|"
    r"transplant(?:ation)?|amputation|debridement|drainage|"
    r"lumbar\s+puncture|thoracentesis|paracentesis)\b",

    # --- Temporal medical ---
    r"\b(?:admitted|admission|discharged|discharge|"
    r"onset|duration|since|"
    r"worsened|worsening|improved|improving|"
    r"resolved|resolving|persists?|persistent|"
    r"progressive|progressing|"
    r"acute|chronic|subacute|recurrent|intermittent|"
    r"new[\s-]?onset|long[\s-]?standing)\b",

    # --- Physical exam findings ---
    r"\b(?:tenderness|swelling|erythema|induration|"
    r"murmur|gallop|rales|crackles|wheezing|rhonchi|"
    r"guarding|rebound|distension|"
    r"edematous|cyanotic|diaphoretic|jaundiced|pallor|"
    r"oriented|disoriented|alert|lethargic|obtunded|"
    r"pupils?\s+(?:equal|unequal|reactive|dilated|constricted))\b",
]

# ── Number/measurement pattern ────────────────────────────────────

NUMBER_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:%|percent|dollars?|USD|EUR|GBP|kg|mg|ml|"
    r"mcg|mEq|mmol|g/dL|mg/dL|mmHg|bpm|"
    r"months?|years?|days?|hours?|minutes?|weeks?|billion|million|thousand)\b",
    re.IGNORECASE,
)

# ── Hedging patterns (filter out opinion sentences) ───────────────

HEDGE_PATTERNS = [
    r"\b(?:it\s+(?:seems|appears)|(?:seems|appears)\s+(?:to|that))\b",
    r"\b(?:in\s+my\s+opinion|I\s+think|I\s+believe)\b",
    r"\b(?:arguably|debatable|uncertain)\b",
]
# Note: "may", "might", "could" removed from hedging -- in medical text
# these often describe real clinical possibilities, not vague opinions.
# "The patient may have pneumonia" is a clinical assessment, not hedging.


def _get_nlp():
    global _nlp
    if _nlp is None:
        _nlp = spacy.load("en_core_web_sm")
    return _nlp


def extract_claims(text: str) -> list[dict]:
    """
    Extract verifiable factual claims from text.

    Returns a list of dicts:
      { "text": str, "source_sentence": str, "entities": [str] }
    """
    nlp = _get_nlp()
    doc = nlp(text)

    claims = []
    for sent in doc.sents:
        sent_text = sent.text.strip()
        if len(sent_text) < 10:
            continue

        # Check if this sentence is hedged (opinion, not factual)
        if _is_hedged(sent_text):
            continue

        # Collect entities in this sentence
        entities = []
        has_factual_entity = False
        for ent in sent.ents:
            if ent.label_ in FACTUAL_ENTITY_TYPES:
                has_factual_entity = True
                entities.append(ent.text)

        # Also extract medical terms as entities (spaCy doesn't tag these)
        medical_entities = _extract_medical_entities(sent_text)
        entities.extend(medical_entities)

        # Check for factual indicators
        has_number = bool(NUMBER_PATTERN.search(sent_text))
        has_causal = _matches_any(sent_text, CAUSAL_PATTERNS)
        has_domain_assertion = _matches_any(sent_text, DOMAIN_ASSERTION_PATTERNS)
        has_medical = _matches_any(sent_text, MEDICAL_PATTERNS)

        if has_factual_entity or has_number or has_causal or has_domain_assertion or has_medical:
            claim_text = _clean_claim(sent_text)
            claims.append({
                "text": claim_text,
                "source_sentence": sent_text,
                "entities": entities,
            })

    return claims


# ── Medical entity extraction ─────────────────────────────────────

# Patterns that capture specific medical terms as entities
_MEDICAL_ENTITY_PATTERNS = [
    # Age
    (re.compile(r"\b(\d+[\s-]*year[\s-]*old)\b", re.I), "AGE"),
    # BP readings
    (re.compile(r"\b(\d{2,3}\s*/\s*\d{2,3})\s*(?:mmhg)?", re.I), "VITAL"),
    # Lab values with numbers
    (re.compile(
        r"\b((?:hemoglobin|hgb|hba1c|a1c|glucose|creatinine|sodium|potassium|"
        r"calcium|platelets?|wbc|rbc|inr|troponin|albumin|bilirubin|"
        r"alt|ast|ldl|hdl|cholesterol|gfr|egfr|tsh|bmi|ferritin|lactate)"
        r"\s*(?:of|is|was|=|:)?\s*\d+(?:\.\d+)?)",
        re.I,
    ), "LAB"),
    # Conditions with type/stage
    (re.compile(r"\b(type\s+(?:1|2|i|ii|iii|iv)\s+\w+)\b", re.I), "CONDITION"),
    (re.compile(r"\b(stage\s+(?:1|2|3|4|i|ii|iii|iv)\s*\w*)\b", re.I), "CONDITION"),
    # Drug names (common)
    (re.compile(
        r"\b(metformin|insulin|aspirin|warfarin|heparin|lisinopril|losartan|"
        r"amlodipine|metoprolol|atorvastatin|omeprazole|acetaminophen|"
        r"ibuprofen|prednisone|furosemide|amoxicillin|levothyroxine|"
        r"gabapentin|sertraline|morphine|oxycodone|clopidogrel|apixaban)\b",
        re.I,
    ), "DRUG"),
    # Disease names
    (re.compile(
        r"\b(diabetes|hypertension|pneumonia|asthma|copd|sepsis|"
        r"cancer|carcinoma|anemia|cirrhosis|hepatitis|epilepsy|"
        r"stroke|dementia|arthritis|osteoporosis|obesity|"
        r"depression|anxiety|tuberculosis|hiv)\b",
        re.I,
    ), "CONDITION"),
]


def _extract_medical_entities(text: str) -> list[str]:
    """Extract medical terms from text that spaCy NER would miss."""
    entities = []
    seen = set()
    for pattern, _label in _MEDICAL_ENTITY_PATTERNS:
        for match in pattern.finditer(text):
            term = match.group(1).strip()
            normalized = term.lower()
            if normalized not in seen:
                entities.append(term)
                seen.add(normalized)
    return entities


# ── Helper functions ──────────────────────────────────────────────

def _is_hedged(text: str) -> bool:
    """Check if text contains hedging language that marks it as opinion."""
    for pattern in HEDGE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def _matches_any(text: str, patterns: list[str]) -> bool:
    """Check if text matches any of the given regex patterns."""
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def _clean_claim(text: str) -> str:
    """Clean up a claim string."""
    text = re.sub(r"^(?:However|Additionally|Furthermore|Moreover|Also|In addition),?\s*", "", text)
    return text.strip()
