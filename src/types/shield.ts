export type ShieldThreatType =
  | "direct_injection"
  | "indirect_injection"
  | "jailbreak"
  | "data_exfiltration"
  | "credential_harvesting"
  | "privilege_escalation"
  | "social_engineering"
  | "tool_manipulation"
  | "encoding_attack";

export type ShieldSeverity = "critical" | "high" | "medium" | "low";

export type ShieldSuggestedAction =
  | "PROCEED_WITH_SANITIZED"
  | "QUARANTINE_FULL_MESSAGE"
  | "REQUEST_HUMAN_REVIEW";

export type ThreatActionTaken = "REMOVED" | "QUARANTINED" | "FLAGGED";

export interface ThreatDetail {
  type: ShieldThreatType;
  severity: ShieldSeverity;
  location: string;
  matched_pattern: string;
  original_text: string;
  action_taken: ThreatActionTaken;
}

export interface ContentSummary {
  total_sections: number;
  safe_sections: number;
  removed_sections: number;
  content_preserved_pct: number;
}

export interface ShieldRemediation {
  message: string;
  agent_instruction: string;
  content_summary: ContentSummary;
  suggested_action: ShieldSuggestedAction;
}

export interface EnhancedShieldResult {
  safe: boolean;
  threat_level: "NONE" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  threats: ThreatDetail[];
  sanitized_input: string | null;
  remediation: ShieldRemediation | null;
}
