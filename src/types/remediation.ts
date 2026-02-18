export type CorrectionType =
  | "numerical_distortion"
  | "source_contradiction"
  | "fabricated_claim"
  | "bias_detected";

export type Severity = "critical" | "high" | "medium" | "low";

export type SuggestedAction =
  | "RETRY_WITH_CORRECTION"
  | "REQUEST_HUMAN_REVIEW"
  | "ABORT_ACTION"
  | "PROCEED_WITH_WARNING";

export interface CorrectionDetail {
  type: CorrectionType;
  check: string;
  found: string;
  expected?: string;
  severity: Severity;
  source_reference?: string;
}

export interface Remediation {
  message: string;
  agent_instruction: string;
  corrections: CorrectionDetail[];
  retry_allowed: boolean;
  max_retries: number;
  suggested_action: SuggestedAction;
}
