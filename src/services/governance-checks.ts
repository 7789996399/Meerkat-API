// Governance check stubs -- each returns randomized but realistic scores.
// These will be replaced with real model inference in Phase 2.

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

// TODO: Replace with real DeBERTa-v3 ONNX model
// Production: tokenize (premise=context, hypothesis=output), run NLI inference,
// return entailment/contradiction/neutral probabilities per claim.
export function entailment_check(
  output: string,
  perRequestContext: string,
  knowledgeBaseContext?: string,
): CheckResult {
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

  // Simulate: longer context overlap = higher score, with variance
  const outputWords = new Set(output.toLowerCase().split(/\s+/));
  const contextWords = new Set(combinedContext.toLowerCase().split(/\s+/));
  let overlap = 0;
  for (const w of outputWords) {
    if (contextWords.has(w) && w.length > 3) overlap++;
  }
  const overlapRatio = overlap / Math.max(outputWords.size, 1);

  // Base score from overlap, plus random noise
  let score = Math.min(overlapRatio * 2.5, 1.0) + rand(-0.15, 0.15);
  score = Math.max(0, Math.min(1, score));

  const flags: string[] = [];
  if (score < 0.4) flags.push("entailment_contradiction");
  if (score < 0.6) flags.push("low_entailment");

  const contextSources = contexts.length === 2
    ? "per-request context + knowledge base"
    : knowledgeBaseContext ? "knowledge base" : "per-request context";

  return {
    score,
    flags,
    detail: `NLI check (${contextSources}): ${overlap} grounded terms across ${outputWords.size} output tokens. Entailment score: ${score.toFixed(3)}.`,
  };
}

const SEMANTIC_ENTROPY_URL = process.env.MEERKAT_SEMANTIC_ENTROPY_URL || "";

interface SemanticEntropyResponse {
  semantic_entropy: number;
  num_clusters: number;
  num_completions: number;
  interpretation: string;
  reference_answer_cluster: number;
  reference_in_majority: boolean;
  entailment_calls: number;
  inference_time_ms: number;
}

export async function semantic_entropy_check(input: string, output: string): Promise<CheckResult> {
  // --- If service URL is configured, call the real semantic entropy service ---
  if (SEMANTIC_ENTROPY_URL) {
    try {
      // TODO: Replace mock completions with real LLM sampling.
      // Production: call the AI model API N times with temperature=0.7 to get
      // diverse sampled completions for the same input prompt. For example:
      //   const completions = await Promise.all(
      //     Array.from({ length: 10 }, () =>
      //       callLLM({ prompt: input, temperature: 0.7, max_tokens: 512 })
      //     )
      //   );
      const mockCompletions = generateMockCompletions(output, 10);

      // TODO: Replace with real entailment service URL from config/env
      const entailmentUrl = process.env.MEERKAT_ENTAILMENT_URL || "http://localhost:8001/predict";

      const resp = await fetch(`${SEMANTIC_ENTROPY_URL}/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: input,
          reference_answer: output,
          sampled_completions: mockCompletions,
          entailment_url: entailmentUrl,
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

      if (!data.reference_in_majority && data.reference_answer_cluster !== -1) {
        flags.push("reference_minority_cluster");
      }
      if (data.reference_answer_cluster === -1) {
        flags.push("reference_no_cluster_match");
      }

      return {
        score,
        flags,
        detail: `Semantic entropy (Farquhar et al.): SE=${data.semantic_entropy.toFixed(3)}, ` +
          `${data.num_clusters} clusters from ${data.num_completions} samples, ` +
          `interpretation=${data.interpretation}, ` +
          `reference_in_majority=${data.reference_in_majority}, ` +
          `${data.entailment_calls} entailment calls in ${data.inference_time_ms.toFixed(0)}ms.`,
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

/**
 * Generate mock sampled completions by perturbing the reference output.
 * TODO: Replace with real LLM multi-sampling at temperature > 0.
 */
function generateMockCompletions(reference: string, n: number): string[] {
  const completions: string[] = [];
  const words = reference.split(/\s+/);

  for (let i = 0; i < n; i++) {
    // Create slight variations: shuffle some words, drop some, add hedging
    const variant = [...words];
    // Randomly drop ~10% of words for variation
    const filtered = variant.filter(() => Math.random() > 0.1);
    // Occasionally add a hedge word
    if (Math.random() < 0.3) {
      const hedges = ["perhaps", "likely", "approximately", "generally"];
      filtered.splice(Math.floor(Math.random() * filtered.length), 0, hedges[i % hedges.length]);
    }
    completions.push(filtered.join(" "));
  }

  return completions;
}

const IMPLICIT_PREFERENCE_URL = process.env.MEERKAT_IMPLICIT_PREFERENCE_URL || "";

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

const CLAIM_EXTRACTOR_URL = process.env.MEERKAT_CLAIM_EXTRACTOR_URL || "";

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
      const entailmentUrl = process.env.MEERKAT_ENTAILMENT_URL || "http://localhost:8001/predict";

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
