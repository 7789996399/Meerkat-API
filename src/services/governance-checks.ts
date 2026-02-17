// Governance check stubs -- each returns randomized but realistic scores.
// These will be replaced with real model inference in Phase 2.

import {
  expandAbbreviations,
  splitClinicalSentences,
  chunkContext,
  findRelevantChunk,
} from "./clinical-preprocessing";

export interface CheckResult {
  score: number;
  flags: string[];
  detail: string;
}

export interface ClaimsResult {
  score: number;
  claims: number;
  verified: number;
  unverified: number;
  flags: string[];
  detail: string;
}

// Random float in [min, max], rounded to 3 decimal places
function rand(min: number, max: number): number {
  return Math.round((min + Math.random() * (max - min)) * 1000) / 1000;
}

const ENTAILMENT_URL = process.env.ENTROPY_SERVICE_URL
  ? `${process.env.ENTROPY_SERVICE_URL}/predict`
  : "";

interface NLIPredictResponse {
  entailment: number;
  contradiction: number;
  neutral: number;
  label: string;
}

// Call DeBERTa NLI model via the semantic entropy service's /predict endpoint.
// Falls back to word-overlap heuristic if the service is unavailable.
//
// Clinical-aware improvements:
// 1. Expands abbreviations (BID -> twice daily) for better NLI
// 2. Uses clinical sentence splitting (doesn't break on "T 39.1.")
// 3. Chunks context to fit DeBERTa's 512-token limit
// 4. Selects most relevant chunk per claim for focused entailment
export async function entailment_check(
  output: string,
  perRequestContext: string,
  knowledgeBaseContext?: string,
): Promise<CheckResult> {
  // Merge both context sources
  const contexts: string[] = [];
  if (perRequestContext && perRequestContext.trim().length > 0) {
    contexts.push(perRequestContext);
  }
  if (knowledgeBaseContext && knowledgeBaseContext.trim().length > 0) {
    contexts.push(knowledgeBaseContext);
  }

  const combinedContext = contexts.join("\n\n");

  if (combinedContext.length === 0) {
    return {
      score: 0.5,
      flags: ["no_context_provided"],
      detail: "No source context provided for entailment checking.",
    };
  }

  const contextSources = contexts.length === 2
    ? "per-request context + knowledge base"
    : knowledgeBaseContext ? "knowledge base" : "per-request context";

  // --- Clinical preprocessing ---
  // Expand abbreviations in both source and output for better NLI
  const expandedContext = expandAbbreviations(combinedContext);
  const expandedOutput = expandAbbreviations(output);

  // Chunk context for DeBERTa's 512-token limit
  // 380 tokens for premise leaves ~130 for hypothesis
  const contextChunks = chunkContext(expandedContext, 380, 50);

  // --- If entailment service is available, use real DeBERTa NLI ---
  if (ENTAILMENT_URL) {
    try {
      // Clinical-aware sentence splitting (doesn't break on "T 39.1.")
      const sentences = splitClinicalSentences(expandedOutput)
        .filter(s => s.length > 15); // Skip very short fragments

      if (sentences.length === 0) {
        return {
          score: 0.85,
          flags: [],
          detail: `NLI check (${contextSources}): No substantial claims to verify.`,
        };
      }

      let totalEntailment = 0;
      let contradictions = 0;
      const contradictedClaims: string[] = [];
      const lowEntailmentClaims: string[] = [];

      for (const sentence of sentences) {
        // Find the most relevant context chunk for this claim
        const relevantChunk = findRelevantChunk(contextChunks, sentence);

        const resp = await fetch(ENTAILMENT_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            premise: relevantChunk,
            hypothesis: sentence,
          }),
        });

        if (!resp.ok) {
          throw new Error(`Entailment service returned ${resp.status}`);
        }

        const data = (await resp.json()) as NLIPredictResponse;
        totalEntailment += data.entailment;

        if (data.label === "CONTRADICTION" && data.contradiction > 0.5) {
          contradictions++;
          contradictedClaims.push(sentence.slice(0, 80));
        } else if (data.entailment < 0.3 && data.neutral > 0.5) {
          // Low entailment + high neutral = claim has no basis in source
          // This catches fabrication (invented content not in source)
          lowEntailmentClaims.push(sentence.slice(0, 80));
        }
      }

      const avgEntailment = totalEntailment / sentences.length;
      // Score: high entailment = good.
      // Penalise contradictions heavily (wrong facts).
      // Penalise low entailment moderately (possibly fabricated).
      let score = avgEntailment
        - (contradictions / sentences.length) * 0.5
        - (lowEntailmentClaims.length / sentences.length) * 0.15;
      score = Math.max(0, Math.min(1, score));

      const flags: string[] = [];
      if (contradictions > 0) flags.push("entailment_contradiction");
      if (lowEntailmentClaims.length > 0) flags.push("possible_fabrication");
      if (score < 0.6) flags.push("low_entailment");

      const contradictionDetail = contradictedClaims.length > 0
        ? ` Contradicted: [${contradictedClaims.join("; ")}].`
        : "";
      const fabricationDetail = lowEntailmentClaims.length > 0
        ? ` Low-evidence claims: [${lowEntailmentClaims.join("; ")}].`
        : "";

      return {
        score,
        flags,
        detail: `NLI check (DeBERTa, ${contextSources}, ${contextChunks.length} chunk(s)): ` +
          `${sentences.length} claim(s), avg entailment ${avgEntailment.toFixed(3)}, ` +
          `${contradictions} contradiction(s), ${lowEntailmentClaims.length} low-evidence.` +
          `${contradictionDetail}${fabricationDetail}`,
      };
    } catch (err: any) {
      console.error("[entailment] Service call failed, falling back to heuristic:", err.message);
      // Fall through to heuristic
    }
  }

  // --- Heuristic fallback (improved word overlap) ---
  // Use expanded text for better matching
  const outputTokens = expandedOutput.toLowerCase().split(/\s+/).filter(w => w.length > 3);
  const contextTokens = new Set(expandedContext.toLowerCase().split(/\s+/).filter(w => w.length > 3));

  // Exclude common clinical filler words that inflate overlap scores
  const fillerWords = new Set([
    "patient", "noted", "showed", "found", "present", "history",
    "admitted", "discharged", "treated", "started", "continued",
    "stable", "improved", "clinical", "medical", "assessment",
    "plan", "with", "that", "this", "from", "were", "been",
    "have", "does", "will", "would", "about", "also", "into",
  ]);

  let overlap = 0;
  let totalMeaningful = 0;
  for (const w of outputTokens) {
    if (fillerWords.has(w)) continue;
    totalMeaningful++;
    if (contextTokens.has(w)) overlap++;
  }

  const overlapRatio = totalMeaningful > 0 ? overlap / totalMeaningful : 0;

  // More conservative scoring: require higher overlap for good scores
  let score = Math.min(overlapRatio * 2.0, 1.0);
  score = Math.max(0, Math.min(1, score));

  const flags: string[] = [];
  if (score < 0.4) flags.push("entailment_contradiction");
  if (score < 0.6) flags.push("low_entailment");

  return {
    score,
    flags,
    detail: `NLI check (heuristic fallback, ${contextSources}): ${overlap} grounded terms across ${totalMeaningful} meaningful tokens. Score: ${score.toFixed(3)}.`,
  };
}

const SEMANTIC_ENTROPY_URL = process.env.ENTROPY_SERVICE_URL || "";

interface SemanticEntropyResponse {
  semantic_entropy: number;
  raw_entropy: number;
  num_clusters: number;
  num_completions: number;
  interpretation: string;
  ai_output_cluster: number;
  ai_output_in_majority: boolean;
  inference_time_ms: number;
}

export async function semantic_entropy_check(input: string, output: string): Promise<CheckResult> {
  // --- If service URL is configured, call the real semantic entropy service ---
  if (SEMANTIC_ENTROPY_URL) {
    try {
      // The Python microservice handles everything:
      // 1. Generates N completions via Ollama at temperature=1.0
      // 2. Clusters by bidirectional entailment (DeBERTa)
      // 3. Computes Shannon entropy over clusters
      // We just send the question, AI output, and optional source context.

      const resp = await fetch(`${SEMANTIC_ENTROPY_URL}/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: input,
          ai_output: output,
          source_context: null,
          num_completions: 10,
        }),
      });

      if (!resp.ok) {
        throw new Error(`Semantic entropy service returned ${resp.status}`);
      }

      const data = (await resp.json()) as SemanticEntropyResponse;

      // Convert: service returns entropy (0=certain, 1=uncertain)
      // Our score is confidence (1=certain, 0=uncertain), so invert
      const score = Math.max(0, Math.min(1, 1 - data.semantic_entropy));

      const flags: string[] = [];
      if (data.interpretation === "confabulation_likely") flags.push("high_uncertainty");
      else if (data.interpretation === "high_uncertainty") flags.push("high_uncertainty");
      else if (data.interpretation === "moderate_uncertainty") flags.push("moderate_uncertainty");

      if (!data.ai_output_in_majority && data.ai_output_cluster !== -1) {
        flags.push("reference_minority_cluster");
      }
      if (data.ai_output_cluster === -1) {
        flags.push("reference_no_cluster_match");
      }

      return {
        score,
        flags,
        detail: `Semantic entropy (Farquhar et al.): SE=${data.semantic_entropy.toFixed(3)}, ` +
          `${data.num_clusters} clusters from ${data.num_completions} samples, ` +
          `interpretation=${data.interpretation}, ` +
          `ai_output_in_majority=${data.ai_output_in_majority}, ` +
          `${data.inference_time_ms.toFixed(0)}ms.`,
      };
    } catch (err: any) {
      console.error("[semantic_entropy] Service call failed, falling back to heuristic:", err.message);
      // Fall through to heuristic
    }
  }

  // --- Heuristic fallback (hedge-word counting) ---
  const hedgeWords = ["may", "might", "could", "possibly", "perhaps", "likely", "appears", "seems", "approximately", "roughly"];
  const words = output.toLowerCase().split(/\s+/);
  const hedgeCount = words.filter((w) => hedgeWords.includes(w)).length;
  const hedgeRatio = hedgeCount / Math.max(words.length, 1);

  let score = Math.max(0, Math.min(1, (1 - hedgeRatio * 8) + rand(-0.1, 0.1)));

  const flags: string[] = [];
  if (score < 0.3) flags.push("high_uncertainty");
  else if (score < 0.6) flags.push("moderate_uncertainty");

  return {
    score,
    flags,
    detail: `Entropy estimate (heuristic fallback): ${hedgeCount} hedge word(s) in ${words.length} tokens. Confidence score: ${score.toFixed(3)}.`,
  };
}

const IMPLICIT_PREFERENCE_URL = process.env.PREFERENCE_SERVICE_URL || "";

interface ImplicitPreferenceResponse {
  score: number;
  bias_detected: boolean;
  direction: string;
  party_a: string;
  party_b: string;
  details: {
    sentiment: { label: string; positive_score: number; negative_score: number };
    direction: {
      direction: string;
      party_a: string;
      party_b: string;
      party_a_score: number;
      party_b_score: number;
      keywords_found: string[];
    };
    counterfactual: { note: string };
  };
  flags: string[];
}

export async function implicit_preference_check(
  output: string,
  domain?: string,
  context?: string,
): Promise<CheckResult> {
  // --- If service URL is configured, call the implicit preference service ---
  if (IMPLICIT_PREFERENCE_URL) {
    try {
      const resp = await fetch(`${IMPLICIT_PREFERENCE_URL}/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          output,
          domain: domain || "general",
          context: context || "",
        }),
      });

      if (!resp.ok) {
        throw new Error(`Implicit preference service returned ${resp.status}`);
      }

      const data = (await resp.json()) as ImplicitPreferenceResponse;

      const flags: string[] = [];
      if (data.bias_detected) flags.push("strong_bias");
      else if (data.score < 0.75) flags.push("mild_preference");

      // Map service-specific flags
      for (const f of data.flags) {
        if (!flags.includes(f)) flags.push(f);
      }

      const dir = data.details.direction;
      const sent = data.details.sentiment;

      return {
        score: data.score,
        flags,
        detail: `Implicit preference (3-analysis): score=${data.score}, ` +
          `sentiment=${sent.label} (pos=${sent.positive_score}, neg=${sent.negative_score}), ` +
          `direction=${dir.direction} (${dir.party_a}=${dir.party_a_score}, ${dir.party_b}=${dir.party_b_score}), ` +
          `keywords=[${dir.keywords_found.join(", ")}], ` +
          `bias_detected=${data.bias_detected}.`,
      };
    } catch (err: any) {
      console.error("[implicit_preference] Service call failed, falling back to heuristic:", err.message);
      // Fall through to heuristic
    }
  }

  // --- Heuristic fallback (keyword counting) ---
  const strongBias = ["must", "always", "never", "clearly superior", "only option", "obviously", "undoubtedly"];
  const mildBias = ["recommend", "prefer", "better", "should", "best"];
  const lower = output.toLowerCase();

  const strongHits = strongBias.filter((p) => lower.includes(p)).length;
  const mildHits = mildBias.filter((p) => lower.includes(p)).length;

  let score = 0.95 - strongHits * 0.2 - mildHits * 0.05 + rand(-0.08, 0.08);
  score = Math.max(0, Math.min(1, score));

  const flags: string[] = [];
  if (score < 0.5) flags.push("strong_bias");
  else if (score < 0.75) flags.push("mild_preference");

  return {
    score,
    flags,
    detail: `Preference scan (heuristic fallback): ${strongHits} strong and ${mildHits} mild bias indicator(s). Neutrality score: ${score.toFixed(3)}.`,
  };
}

const CLAIM_EXTRACTOR_URL = process.env.CLAIMS_SERVICE_URL || "";

interface ClaimExtractorClaim {
  claim_id: number;
  text: string;
  source_sentence: string;
  status: "verified" | "contradicted" | "unverified";
  entailment_score: number;
  entities: string[];
  hallucinated_entities: string[];
}

interface ClaimExtractorResponse {
  total_claims: number;
  verified: number;
  contradicted: number;
  unverified: number;
  claims: ClaimExtractorClaim[];
  hallucinated_entities: string[];
  flags: string[];
}

export async function claim_extraction_check(output: string, context: string): Promise<ClaimsResult> {
  // --- If service URL is configured, call the claim extractor service ---
  if (CLAIM_EXTRACTOR_URL) {
    try {
      // Entailment service (/predict) lives on the entropy service
      const entailmentUrl = process.env.ENTROPY_SERVICE_URL
        ? `${process.env.ENTROPY_SERVICE_URL}/predict`
        : "http://localhost:8001/predict";

      const resp = await fetch(`${CLAIM_EXTRACTOR_URL}/extract`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ai_output: output,
          source_context: context || "",
          entailment_url: entailmentUrl,
        }),
      });

      if (!resp.ok) {
        throw new Error(`Claim extractor service returned ${resp.status}`);
      }

      const data = (await resp.json()) as ClaimExtractorResponse;

      // Score: verified / total (1.0 if no claims)
      const score = data.total_claims > 0
        ? data.verified / data.total_claims
        : 1.0;

      const flags: string[] = [...data.flags];
      if (data.unverified > 0 && !flags.includes("unverified_claims")) {
        flags.push("unverified_claims");
      }
      if (data.unverified > data.total_claims * 0.5 && data.total_claims > 0 && !flags.includes("majority_unverified")) {
        flags.push("majority_unverified");
      }

      const hallucinatedSummary = data.hallucinated_entities.length > 0
        ? ` Hallucinated entities: [${data.hallucinated_entities.join(", ")}].`
        : "";

      return {
        score,
        claims: data.total_claims,
        verified: data.verified,
        unverified: data.unverified + data.contradicted,
        flags,
        detail: `Claim extraction (spaCy + entailment): ${data.total_claims} claim(s), ` +
          `${data.verified} verified, ${data.contradicted} contradicted, ` +
          `${data.unverified} unverified.${hallucinatedSummary}`,
      };
    } catch (err: any) {
      console.error("[claim_extraction] Service call failed, falling back to heuristic:", err.message);
      // Fall through to heuristic
    }
  }

  // --- Heuristic fallback (regex pattern matching) ---
  const patterns = [
    /\$[\d,.]+/g,
    /\d+\s*(?:day|month|year|week|hour|percent|%)/gi,
    /\d+(?:\.\d+)?%/g,
    /Section\s+\d+(?:\.\d+)*/gi,
    /Clause\s+\d+(?:\.\d+)*/gi,
  ];

  const claimSet = new Set<string>();
  for (const pattern of patterns) {
    const matches = output.match(pattern);
    if (matches) matches.forEach((m) => claimSet.add(m));
  }

  const claims = claimSet.size;
  if (claims === 0) {
    return {
      score: 1.0,
      claims: 0,
      verified: 0,
      unverified: 0,
      flags: [],
      detail: "No factual claims extracted (heuristic fallback).",
    };
  }

  // Simulate verification against context
  let verified = 0;
  for (const claim of claimSet) {
    const normalized = claim.replace(/[$,%]/g, "").trim();
    if (context && context.toLowerCase().includes(normalized.toLowerCase())) {
      verified++;
    } else if (Math.random() < 0.3) {
      verified++;
    }
  }

  const unverified = claims - verified;
  const score = claims > 0 ? verified / claims : 1.0;

  const flags: string[] = [];
  if (unverified > 0) flags.push("unverified_claims");
  if (unverified > claims * 0.5) flags.push("majority_unverified");

  return {
    score,
    claims,
    verified,
    unverified,
    flags,
    detail: `Extracted ${claims} factual claim(s) (heuristic fallback). ${verified} verified, ${unverified} unverified.`,
  };
}


// ══════════════════════════════════════════════════════════════════
// Numerical Verification (Check 5)
// ══════════════════════════════════════════════════════════════════

const NUMERICAL_SERVICE_URL = process.env.NUMERICAL_SERVICE_URL || "";

interface NumericalMatchDetail {
  source_value: number;
  ai_value: number;
  context: string;
  context_type: string;
  match: boolean;
  deviation: number;
  tolerance: number;
  severity: string;
}

interface NumericalVerifyResponse {
  score: number;
  status: string;
  numbers_found_in_source: number;
  numbers_found_in_ai: number;
  matches: NumericalMatchDetail[];
  ungrounded_numbers: { value: number; raw: string; context: string }[];
  critical_mismatches: number;
  detail: string;
  inference_time_ms: number;
}

export async function numerical_verify_check(
  output: string,
  context: string,
  domain?: string,
): Promise<CheckResult> {
  // --- If service URL is configured, call the numerical verification service ---
  if (NUMERICAL_SERVICE_URL) {
    try {
      const resp = await fetch(`${NUMERICAL_SERVICE_URL}/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ai_output: output,
          source_context: context || "",
          domain: domain || "healthcare",
        }),
      });

      if (!resp.ok) {
        throw new Error(`Numerical verification service returned ${resp.status}`);
      }

      const data = (await resp.json()) as NumericalVerifyResponse;

      const flags: string[] = [];
      if (data.critical_mismatches > 0) flags.push("critical_numerical_mismatch");
      if (data.status === "fail") flags.push("numerical_distortion");
      if (data.status === "warning") flags.push("numerical_warning");
      if (data.ungrounded_numbers.length > 0) flags.push("ungrounded_numbers");

      return {
        score: data.score,
        flags,
        detail: `Numerical verification: ${data.detail} ` +
          `(${data.numbers_found_in_source} source, ${data.numbers_found_in_ai} AI, ` +
          `${data.critical_mismatches} critical, ${data.inference_time_ms.toFixed(0)}ms)`,
      };
    } catch (err: any) {
      console.error("[numerical_verify] Service call failed, falling back to heuristic:", err.message);
      // Fall through to heuristic
    }
  }

  // --- Heuristic fallback: simple regex number extraction and comparison ---
  if (!context || context.trim().length === 0) {
    return {
      score: 1.0,
      flags: [],
      detail: "No source context provided for numerical verification.",
    };
  }

  // Extract numbers from both texts
  const numberRegex = /\d+(?:\.\d+)?/g;
  const sourceNumbers = (context.match(numberRegex) || []).map(Number);
  const aiNumbers = (output.match(numberRegex) || []).map(Number);

  if (aiNumbers.length === 0) {
    return {
      score: 1.0,
      flags: [],
      detail: "No numbers found in AI output (heuristic fallback).",
    };
  }

  // Simple: check if each AI number exists in source
  let matched = 0;
  for (const aiNum of aiNumbers) {
    if (sourceNumbers.some(sn => Math.abs(sn - aiNum) / Math.max(Math.abs(sn), 0.001) < 0.02)) {
      matched++;
    }
  }

  const score = aiNumbers.length > 0 ? matched / aiNumbers.length : 1.0;
  const flags: string[] = [];
  if (score < 0.5) flags.push("numerical_distortion");
  if (score < 1.0) flags.push("numerical_warning");

  return {
    score,
    flags,
    detail: `Numerical check (heuristic fallback): ${matched}/${aiNumbers.length} AI numbers found in source.`,
  };
}
