export type Sensitivity = "low" | "medium" | "high";

export interface ShieldResult {
  safe: boolean;
  threat_level: "NONE" | "LOW" | "MEDIUM" | "HIGH";
  attack_type: "direct_injection" | "indirect_injection" | "jailbreak" | null;
  detail: string;
  action: "ALLOW" | "FLAG" | "BLOCK";
  sanitized_input: string | null;
}

// --- Pattern definitions ---

interface Pattern {
  regex: RegExp;
  label: string;
}

const DIRECT_INJECTION: Pattern[] = [
  { regex: /ignore\s+(all\s+)?previous\s+instructions/i, label: "ignore previous instructions" },
  { regex: /ignore\s+all\s+prior/i, label: "ignore all prior" },
  { regex: /you\s+are\s+now\b/i, label: "you are now" },
  { regex: /new\s+instructions\s*:/i, label: "new instructions:" },
  { regex: /system\s*prompt\s*:/i, label: "system prompt:" },
  { regex: /act\s+as\s+if\b/i, label: "act as if" },
  { regex: /pretend\s+(you\s+are|to\s+be)\b/i, label: "pretend you are" },
  { regex: /\bdisregard\b.*\b(instructions|rules|guidelines|above|previous)\b/i, label: "disregard" },
];

const JAILBREAK: Pattern[] = [
  { regex: /\bDAN\b/, label: "DAN" },
  { regex: /do\s+anything\s+now/i, label: "do anything now" },
  { regex: /\bhypothetically\b/i, label: "hypothetically" },
  { regex: /for\s+educational\s+purposes/i, label: "for educational purposes" },
  { regex: /in\s+a\s+fictional\s+scenario/i, label: "in a fictional scenario" },
];

// --- Indirect injection checks ---

function hasBase64(input: string): string | null {
  // Match long base64 strings (at least 40 chars to avoid false positives on normal text)
  const match = input.match(/[A-Za-z0-9+/]{40,}={0,2}/);
  if (!match) return null;

  try {
    const decoded = Buffer.from(match[0], "base64").toString("utf-8");
    // Check if decoded text looks like readable instructions (mostly printable ASCII)
    const printable = decoded.replace(/[^\x20-\x7E]/g, "");
    if (printable.length > decoded.length * 0.7) {
      return `Base64-encoded string detected (${match[0].length} chars). Decoded content appears to contain readable text.`;
    }
  } catch {
    // Not valid base64, ignore
  }
  return null;
}

function hasUnusualUnicode(input: string): string | null {
  // Detect zero-width characters, RTL overrides, homoglyphs outside standard Latin/common ranges
  const suspicious = input.match(/[\u200B-\u200F\u2028-\u202F\uFEFF\u2060-\u2064\u00AD]/g);
  if (suspicious && suspicious.length > 0) {
    return `${suspicious.length} invisible/control Unicode character(s) detected. May hide injected instructions.`;
  }

  // Detect Cyrillic/Greek characters mixed with Latin (homoglyph attack)
  const hasLatin = /[a-zA-Z]/.test(input);
  const hasCyrillic = /[\u0400-\u04FF]/.test(input);
  const hasGreek = /[\u0370-\u03FF]/.test(input);
  if (hasLatin && (hasCyrillic || hasGreek)) {
    return "Mixed Latin and Cyrillic/Greek characters detected. Possible homoglyph attack.";
  }

  return null;
}

function isOverlong(input: string): string | null {
  if (input.length > 10000) {
    return `Input length is ${input.length} characters (limit: 10,000). Extremely long inputs may hide injection payloads.`;
  }
  return null;
}

function hasSystemPromptMarkers(input: string): string | null {
  const markers = [
    { regex: /```system\b/i, label: "```system" },
    { regex: /\[INST\]/i, label: "[INST]" },
    { regex: /<<SYS>>/i, label: "<<SYS>>" },
    { regex: /\[SYSTEM\]/i, label: "[SYSTEM]" },
    { regex: /<\|im_start\|>system/i, label: "<|im_start|>system" },
  ];

  for (const { regex, label } of markers) {
    if (regex.test(input)) {
      return `System prompt marker "${label}" detected. Input may contain embedded system-level instructions.`;
    }
  }
  return null;
}

// --- Sanitizer ---

function sanitize(input: string): string {
  let cleaned = input;

  // Strip zero-width / control characters
  cleaned = cleaned.replace(/[\u200B-\u200F\u2028-\u202F\uFEFF\u2060-\u2064\u00AD]/g, "");

  // Remove matched direct injection phrases
  for (const { regex } of DIRECT_INJECTION) {
    cleaned = cleaned.replace(regex, "[REDACTED]");
  }

  // Remove system prompt markers
  cleaned = cleaned.replace(/```system\b/gi, "[REDACTED]");
  cleaned = cleaned.replace(/\[INST\]/gi, "[REDACTED]");
  cleaned = cleaned.replace(/<<SYS>>/gi, "[REDACTED]");
  cleaned = cleaned.replace(/<\|im_start\|>system/gi, "[REDACTED]");

  // Truncate if overlong
  if (cleaned.length > 10000) {
    cleaned = cleaned.slice(0, 10000);
  }

  return cleaned;
}

// --- Main scan ---

export function scan(input: string, sensitivity: Sensitivity = "medium"): ShieldResult {
  // 1. Direct injection patterns -- always HIGH severity
  for (const { regex, label } of DIRECT_INJECTION) {
    if (regex.test(input)) {
      return {
        safe: false,
        threat_level: "HIGH",
        attack_type: "direct_injection",
        detail: `Direct injection detected: "${label}" pattern matched.`,
        action: "BLOCK",
        sanitized_input: null,
      };
    }
  }

  // 2. Indirect injection checks -- severity depends on sensitivity
  const indirectChecks = [
    hasBase64(input),
    hasUnusualUnicode(input),
    isOverlong(input),
    hasSystemPromptMarkers(input),
  ].filter(Boolean) as string[];

  if (indirectChecks.length > 0) {
    // Multiple indirect signals = higher severity
    const multi = indirectChecks.length > 1;

    if (sensitivity === "high" || multi) {
      return {
        safe: false,
        threat_level: multi ? "HIGH" : "MEDIUM",
        attack_type: "indirect_injection",
        detail: indirectChecks.join(" "),
        action: multi ? "BLOCK" : "FLAG",
        sanitized_input: multi ? null : sanitize(input),
      };
    }

    if (sensitivity === "medium") {
      return {
        safe: false,
        threat_level: "MEDIUM",
        attack_type: "indirect_injection",
        detail: indirectChecks.join(" "),
        action: "FLAG",
        sanitized_input: sanitize(input),
      };
    }

    // sensitivity === "low": only flag, don't block
    if (indirectChecks.some((c) => c.includes("System prompt marker") || c.includes("Base64"))) {
      return {
        safe: false,
        threat_level: "LOW",
        attack_type: "indirect_injection",
        detail: indirectChecks.join(" "),
        action: "FLAG",
        sanitized_input: sanitize(input),
      };
    }
  }

  // 3. Jailbreak patterns -- severity depends on sensitivity
  for (const { regex, label } of JAILBREAK) {
    if (regex.test(input)) {
      if (sensitivity === "low") {
        // Low sensitivity ignores jailbreak heuristics
        continue;
      }

      const isHigh = sensitivity === "high";
      return {
        safe: false,
        threat_level: isHigh ? "MEDIUM" : "LOW",
        attack_type: "jailbreak",
        detail: `Jailbreak pattern detected: "${label}" matched.`,
        action: isHigh ? "BLOCK" : "FLAG",
        sanitized_input: isHigh ? null : sanitize(input),
      };
    }
  }

  // 4. Clean
  return {
    safe: true,
    threat_level: "NONE",
    attack_type: null,
    detail: "Input passed all threat checks. No injection patterns detected.",
    action: "ALLOW",
    sanitized_input: null,
  };
}
