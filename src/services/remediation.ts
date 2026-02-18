import {
  CorrectionDetail,
  CorrectionType,
  Remediation,
  Severity,
  SuggestedAction,
} from "../types/remediation";
import { CheckResult } from "./governance-checks";

const SEVERITY_RANK: Record<Severity, number> = {
  critical: 4,
  high: 3,
  medium: 2,
  low: 1,
};

interface BuildRemediationInput {
  status: "FLAG" | "BLOCK";
  checksResults: Record<string, CheckResult>;
  allFlags: string[];
  attempt: number;
  maxRetries: number;
}

export function buildRemediation({
  status,
  checksResults,
  allFlags,
  attempt,
  maxRetries,
}: BuildRemediationInput): Remediation {
  // 1. Collect corrections from all check results
  const corrections: CorrectionDetail[] = [];
  for (const result of Object.values(checksResults)) {
    if (result.corrections) {
      corrections.push(...result.corrections);
    }
  }

  // 2. Determine highest severity across corrections
  let highestSeverity: Severity = "low";
  for (const c of corrections) {
    if (SEVERITY_RANK[c.severity] > SEVERITY_RANK[highestSeverity]) {
      highestSeverity = c.severity;
    }
  }

  // 3. Determine suggested_action
  const retryAllowed = attempt < maxRetries;
  let suggestedAction: SuggestedAction;

  if (!retryAllowed) {
    suggestedAction = "REQUEST_HUMAN_REVIEW";
  } else if (status === "BLOCK") {
    if (highestSeverity === "critical" && corrections.length > 0) {
      suggestedAction = "RETRY_WITH_CORRECTION";
    } else if (highestSeverity === "high") {
      suggestedAction = "RETRY_WITH_CORRECTION";
    } else if (corrections.length > 0) {
      suggestedAction = "RETRY_WITH_CORRECTION";
    } else {
      suggestedAction = "ABORT_ACTION";
    }
  } else {
    // FLAG
    suggestedAction =
      highestSeverity === "medium" || highestSeverity === "low"
        ? "PROCEED_WITH_WARNING"
        : "RETRY_WITH_CORRECTION";
  }

  // 4. Build message — summarize counts by correction type
  const message = buildMessage(status, corrections, allFlags, retryAllowed);

  // 5. Build agent_instruction
  const agentInstruction = buildAgentInstruction(suggestedAction, corrections);

  return {
    message,
    agent_instruction: agentInstruction,
    corrections,
    retry_allowed: retryAllowed,
    max_retries: maxRetries,
    suggested_action: suggestedAction,
  };
}

function buildMessage(
  status: "FLAG" | "BLOCK",
  corrections: CorrectionDetail[],
  allFlags: string[],
  retryAllowed: boolean,
): string {
  const parts: string[] = [];

  parts.push(`Verification ${status}.`);

  if (corrections.length > 0) {
    const countsByType: Partial<Record<CorrectionType, number>> = {};
    for (const c of corrections) {
      countsByType[c.type] = (countsByType[c.type] || 0) + 1;
    }

    const typeSummaries: string[] = [];
    for (const [type, count] of Object.entries(countsByType)) {
      const label = type.replace(/_/g, " ");
      typeSummaries.push(`${count} ${label}${count > 1 ? "s" : ""}`);
    }
    parts.push(`Found ${corrections.length} issue(s): ${typeSummaries.join(", ")}.`);
  } else if (allFlags.length > 0) {
    parts.push(`Flagged issues: ${allFlags.join(", ")}.`);
  }

  if (!retryAllowed) {
    parts.push("Maximum retry attempts reached. Human review required.");
  }

  return parts.join(" ");
}

function buildAgentInstruction(
  action: SuggestedAction,
  corrections: CorrectionDetail[],
): string {
  switch (action) {
    case "RETRY_WITH_CORRECTION": {
      const directives: string[] = [
        "Regenerate your response with the following corrections:",
      ];
      for (const c of corrections) {
        switch (c.type) {
          case "source_contradiction":
            directives.push(
              `- CONTRADICTION in ${c.check}: Your output "${c.found}" contradicts the source.${c.expected ? ` Correct value: "${c.expected}".` : ""}`,
            );
            break;
          case "fabricated_claim":
            directives.push(
              `- UNVERIFIED CLAIM in ${c.check}: "${c.found}" could not be verified against source material. Remove or verify this claim.`,
            );
            break;
          case "numerical_distortion":
            directives.push(
              `- NUMERICAL ERROR in ${c.check}: "${c.found}" does not match source.${c.expected ? ` Expected: "${c.expected}".` : ""} Correct the figure.`,
            );
            break;
          case "bias_detected":
            directives.push(
              `- BIAS in ${c.check}: ${c.found}. Rewrite using neutral, balanced language.`,
            );
            break;
        }
      }
      if (corrections.length === 0) {
        directives.push(
          "- Review your output against the provided source context and ensure all claims are grounded.",
        );
      }
      return directives.join("\n");
    }
    case "PROCEED_WITH_WARNING":
      return "Minor issues detected. You may proceed but consider addressing flagged items for improved accuracy.";
    case "REQUEST_HUMAN_REVIEW":
      return "This response requires human review before it can be used. Do not proceed autonomously.";
    case "ABORT_ACTION":
      return "Verification failed with no actionable corrections available. Do not use this response.";
  }
}
