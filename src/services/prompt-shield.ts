export type Sensitivity = "low" | "medium" | "high";

export interface ShieldResult {
  safe: boolean;
  threat_level: "NONE" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  attack_type:
    | "direct_injection"
    | "indirect_injection"
    | "jailbreak"
    | "data_exfiltration"
    | "credential_harvesting"
    | "privilege_escalation"
    | "social_engineering"
    | "tool_manipulation"
    | null;
  detail: string;
  action: "ALLOW" | "FLAG" | "BLOCK";
  sanitized_input: string | null;
  patterns_matched: string[];
}

interface Pattern {
  regex: RegExp;
  label: string;
  weight: number;
}

const DIRECT_INJECTION: Pattern[] = [
  { regex: /ignore\s+(all\s+)?previous\s+instructions/i, label: "ignore previous instructions", weight: 3 },
  { regex: /ignore\s+all\s+prior/i, label: "ignore all prior", weight: 3 },
  { regex: /ignore\s+(your\s+)?(rules|guidelines|constraints|safety)/i, label: "ignore rules", weight: 3 },
  { regex: /you\s+are\s+now\b/i, label: "you are now", weight: 3 },
  { regex: /new\s+instructions\s*:/i, label: "new instructions:", weight: 3 },
  { regex: /system\s*prompt\s*:/i, label: "system prompt:", weight: 3 },
  { regex: /act\s+as\s+if\b/i, label: "act as if", weight: 2 },
  { regex: /pretend\s+(you\s+are|to\s+be)\b/i, label: "pretend you are", weight: 2 },
  { regex: /\bdisregard\b.*\b(instructions|rules|guidelines|above|previous)\b/i, label: "disregard", weight: 3 },
  { regex: /override\s+(your\s+)?(instructions|rules|programming|guidelines)/i, label: "override instructions", weight: 3 },
  { regex: /forget\s+(everything|all|your)\s+(you|previous|prior)/i, label: "forget previous", weight: 3 },
  { regex: /from\s+now\s+on[,\s]+(you\s+)?(will|must|should|are)/i, label: "from now on", weight: 2 },
  { regex: /\[IMPORTANT\].*\b(override|ignore|disregard|new\s+instructions)\b/i, label: "bracketed override", weight: 3 },
  { regex: /ADMIN\s*:\s*|DEVELOPER\s*:\s*|SYSTEM\s*:\s*/i, label: "role impersonation prefix", weight: 2 },
];

const JAILBREAK: Pattern[] = [
  { regex: /\bDAN\b/, label: "DAN", weight: 3 },
  { regex: /do\s+anything\s+now/i, label: "do anything now", weight: 3 },
  { regex: /\bhypothetically\b/i, label: "hypothetically", weight: 1 },
  { regex: /for\s+educational\s+purposes/i, label: "for educational purposes", weight: 1 },
  { regex: /in\s+a\s+fictional\s+scenario/i, label: "in a fictional scenario", weight: 1 },
  { regex: /\buncensored\s+mode\b/i, label: "uncensored mode", weight: 3 },
  { regex: /\bdeveloper\s+mode\b/i, label: "developer mode", weight: 2 },
  { regex: /\bno\s+restrictions\b/i, label: "no restrictions", weight: 2 },
  { regex: /\bjailbreak\b/i, label: "jailbreak keyword", weight: 3 },
  { regex: /without\s+(any\s+)?(ethical|moral|safety)\s+(constraints|guidelines|restrictions)/i, label: "without safety constraints", weight: 3 },
];

const DATA_EXFILTRATION: Pattern[] = [
  { regex: /\b(send|forward|email|post|upload|transmit|share)\b.*\b(api[_\s-]?key|secret|token|password|credential|private[_\s-]?key)\b/i, label: "exfiltrate credentials", weight: 3 },
  { regex: /\b(send|forward|email|post|share)\b.*\bto\b.*@/i, label: "send to external email", weight: 1 },
  { regex: /\bforward\s+(all|every)\s+\w*\s*(emails?|messages?|conversations?|chats?|histor(y|ies))/i, label: "forward all messages", weight: 3 },
  { regex: /\b(copy|dump|export|extract)\s+(all|every|my)\s+(data|files|documents|contacts|emails)/i, label: "dump all data", weight: 3 },
  { regex: /\bsend\s+(this|the|your|my)\s+(to|towards)\s+\S+\.(com|org|net|io)/i, label: "send to domain", weight: 2 },
  { regex: /\bwebhook\b.*\b(https?:\/\/)/i, label: "webhook URL", weight: 2 },
  { regex: /\b(pipe|redirect|stream)\s+(output|data|results)\s+to\b/i, label: "redirect output", weight: 2 },
  { regex: /aHR0c[A-Za-z0-9+/=]{20,}/i, label: "base64-encoded URL (aHR0c = http)", weight: 3 },
];

const CREDENTIAL_HARVESTING: Pattern[] = [
  { regex: /\b(show|display|print|read|cat|echo|list)\b.*(?:\.env|\.ssh|\.aws|credentials|secrets|\.netrc|\.pgpass)/i, label: "read credential files", weight: 3 },
  { regex: /\benvironm?e?n?t?\s*\b(variable|var)\b.*\b(API|KEY|SECRET|TOKEN|PASSWORD)/i, label: "read env vars", weight: 3 },
  { regex: /\b(cat|type|less|more|head|tail)\s+.*(?:\.env|\.ssh|\.aws|config\/credentials|credentials)/i, label: "cat credential file", weight: 3 },
  { regex: /process\.env\s*\[?\s*['"]?(API|SECRET|KEY|TOKEN|PASSWORD)/i, label: "access process.env credentials", weight: 2 },
  { regex: /\$\{?(API_KEY|SECRET_KEY|ACCESS_TOKEN|PRIVATE_KEY|DB_PASSWORD|AWS_SECRET)\}?/i, label: "reference credential variable", weight: 2 },
];

const PRIVILEGE_ESCALATION: Pattern[] = [
  { regex: /\bsudo\b/i, label: "sudo command", weight: 2 },
  { regex: /\bchmod\s+[0-7]*7[0-7]*/i, label: "chmod world-writable", weight: 2 },
  { regex: /\brm\s+(-rf?|--force)\s+\//i, label: "rm -rf /", weight: 3 },
  { regex: /\bcurl\b.*\|\s*(bash|sh|python|node)/i, label: "curl pipe to shell", weight: 3 },
  { regex: /\beval\s*\(/i, label: "eval()", weight: 2 },
  { regex: /\b(add|create)\s+(admin|root|superuser)\b/i, label: "create admin user", weight: 3 },
];

const SOCIAL_ENGINEERING: Pattern[] = [
  { regex: /\b(the\s+user|your\s+owner|your\s+creator)\s+(wants|said|asked|told|authorized|approved)\b/i, label: "false authority claim", weight: 2 },
  { regex: /\b(Anthropic|OpenAI|Google|admin|security\s+team)\s+(says|requires|demands|instructed|authorized)/i, label: "vendor impersonation", weight: 3 },
  { regex: /\byou\s+(must|have\s+to|need\s+to)\s+(obey|comply|follow|execute)\b/i, label: "compliance pressure", weight: 2 },
  { regex: /\bpre[_\s-]?authorized\b/i, label: "pre-authorized claim", weight: 2 },
  { regex: /\bthe\s+user\s+already\s+(agreed|consented|approved|authorized)/i, label: "false consent claim", weight: 3 },
];

const TOOL_MANIPULATION: Pattern[] = [
  { regex: /\b(before|after)\s+(responding|answering|replying)[,\s]+(run|execute|call|use)\b/i, label: "hidden tool trigger", weight: 3 },
  { regex: /\bsilently\s+(run|execute|send|post|call|fetch)\b/i, label: "silent execution", weight: 3 },
  { regex: /\bdo\s+not\s+(mention|tell|inform|alert|notify)\s+(the\s+)?(user|human|owner)/i, label: "hide from user", weight: 3 },
  { regex: /\b(without|before)\s+(telling|informing|notifying|alerting)\s+(the\s+)?(user|human|owner)\b/i, label: "stealth action", weight: 3 },
  { regex: /\b(remember|store|save)\s+this\s+(for|until)\s+later\b/i, label: "delayed payload (memory poisoning)", weight: 2 },
  { regex: /\bnext\s+time\s+(the\s+user|you|someone)\b.*\b(run|execute|send|do)\b/i, label: "time-shifted injection", weight: 3 },
  { regex: /\bwhen\s+(asked|prompted|told)\s+about\b.*\b(instead|actually|really)\b/i, label: "conditional injection", weight: 3 },
];

function hasBase64(input: string): string | null {
  const match = input.match(/[A-Za-z0-9+/]{40,}={0,2}/);
  if (!match) return null;
  try {
    const decoded = Buffer.from(match[0], "base64").toString("utf-8");
    const printable = decoded.replace(/[^\x20-\x7E]/g, "");
    if (printable.length > decoded.length * 0.7) {
      return `Base64-encoded string (${match[0].length} chars) with readable content.`;
    }
  } catch {}
  return null;
}

function hasUnusualUnicode(input: string): string | null {
  const suspicious = input.match(/[\u200B-\u200F\u2028-\u202F\uFEFF\u2060-\u2064\u00AD]/g);
  if (suspicious && suspicious.length > 0) {
    return `${suspicious.length} invisible/control Unicode character(s) detected.`;
  }
  const hasLatin = /[a-zA-Z]/.test(input);
  const hasCyrillic = /[\u0400-\u04FF]/.test(input);
  const hasGreek = /[\u0370-\u03FF]/.test(input);
  if (hasLatin && (hasCyrillic || hasGreek)) {
    return "Mixed Latin and Cyrillic/Greek characters (homoglyph attack).";
  }
  return null;
}

function isOverlong(input: string): string | null {
  if (input.length > 10000) {
    return `Input is ${input.length} chars (limit: 10,000). May hide injection payloads.`;
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
    { regex: /<\|begin_of_text\|>/i, label: "<|begin_of_text|>" },
    { regex: /###\s*(System|Instruction|Human|Assistant)\s*:/i, label: "### Role:" },
  ];
  const found = markers.filter(m => m.regex.test(input)).map(m => m.label);
  return found.length > 0 ? `System prompt markers: ${found.join(", ")}.` : null;
}

function hasHiddenContent(input: string): string | null {
  const signals: string[] = [];
  if (/<[^>]*(display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0|font-size\s*:\s*0)/i.test(input)) {
    signals.push("CSS-hidden content");
  }
  if (/<[^>]*(color\s*:\s*(white|#fff|#ffffff|rgb\(255))/i.test(input)) {
    signals.push("White-on-white text");
  }
  if (/<!--.*\b(instruction|execute|run|send|ignore|override)\b.*-->/is.test(input)) {
    signals.push("Instructions in HTML comments");
  }
  if (/<[^>]*font-size\s*:\s*[01]px/i.test(input)) {
    signals.push("Near-invisible font size");
  }
  return signals.length > 0 ? signals.join(". ") + "." : null;
}

function sanitize(input: string): string {
  let cleaned = input;
  cleaned = cleaned.replace(/[\u200B-\u200F\u2028-\u202F\uFEFF\u2060-\u2064\u00AD]/g, "");
  for (const { regex } of DIRECT_INJECTION) {
    cleaned = cleaned.replace(regex, "[REDACTED]");
  }
  cleaned = cleaned.replace(/```system\b/gi, "[REDACTED]");
  cleaned = cleaned.replace(/\[INST\]/gi, "[REDACTED]");
  cleaned = cleaned.replace(/<<SYS>>/gi, "[REDACTED]");
  cleaned = cleaned.replace(/<\|im_start\|>system/gi, "[REDACTED]");
  if (cleaned.length > 10000) cleaned = cleaned.slice(0, 10000);
  return cleaned;
}

interface CategoryResult {
  matched: boolean;
  patterns: string[];
  totalWeight: number;
  attackType: ShieldResult["attack_type"];
}

function scanCategory(input: string, patterns: Pattern[], attackType: ShieldResult["attack_type"]): CategoryResult {
  const matched: string[] = [];
  let totalWeight = 0;
  for (const p of patterns) {
    if (p.regex.test(input)) {
      matched.push(p.label);
      totalWeight += p.weight;
    }
  }
  return { matched: matched.length > 0, patterns: matched, totalWeight, attackType };
}

export function scan(input: string, sensitivity: Sensitivity = "medium"): ShieldResult {
  // 1. Direct injection -- always highest severity
  const direct = scanCategory(input, DIRECT_INJECTION, "direct_injection");
  if (direct.matched) {
    return {
      safe: false,
      threat_level: direct.totalWeight >= 3 ? "CRITICAL" : "HIGH",
      attack_type: "direct_injection",
      detail: `Direct injection: ${direct.patterns.join(", ")}.`,
      action: "BLOCK",
      sanitized_input: null,
      patterns_matched: direct.patterns,
    };
  }

  // 2. Data exfiltration -- critical for AI agents
  const exfil = scanCategory(input, DATA_EXFILTRATION, "data_exfiltration");
  if (exfil.matched && exfil.totalWeight >= 3) {
    return {
      safe: false,
      threat_level: "CRITICAL",
      attack_type: "data_exfiltration",
      detail: `Data exfiltration attempt: ${exfil.patterns.join(", ")}.`,
      action: "BLOCK",
      sanitized_input: null,
      patterns_matched: exfil.patterns,
    };
  }

  // 3. Tool manipulation -- agent-specific
  const toolManip = scanCategory(input, TOOL_MANIPULATION, "tool_manipulation");
  if (toolManip.matched && toolManip.totalWeight >= 3) {
    return {
      safe: false,
      threat_level: "HIGH",
      attack_type: "tool_manipulation",
      detail: `Tool manipulation: ${toolManip.patterns.join(", ")}.`,
      action: "BLOCK",
      sanitized_input: null,
      patterns_matched: toolManip.patterns,
    };
  }

  // 4. Credential harvesting
  const creds = scanCategory(input, CREDENTIAL_HARVESTING, "credential_harvesting");
  if (creds.matched && creds.totalWeight >= 3) {
    return {
      safe: false,
      threat_level: "HIGH",
      attack_type: "credential_harvesting",
      detail: `Credential harvesting: ${creds.patterns.join(", ")}.`,
      action: "BLOCK",
      sanitized_input: null,
      patterns_matched: creds.patterns,
    };
  }

  // 5. Privilege escalation
  const privesc = scanCategory(input, PRIVILEGE_ESCALATION, "privilege_escalation");
  if (privesc.matched && privesc.totalWeight >= 3) {
    return {
      safe: false,
      threat_level: "HIGH",
      attack_type: "privilege_escalation",
      detail: `Privilege escalation: ${privesc.patterns.join(", ")}.`,
      action: "BLOCK",
      sanitized_input: null,
      patterns_matched: privesc.patterns,
    };
  }

  // 6. Social engineering
  const social = scanCategory(input, SOCIAL_ENGINEERING, "social_engineering");
  if (social.matched && social.totalWeight >= 2) {
    const severity = social.totalWeight >= 3 ? "HIGH" : "MEDIUM";
    return {
      safe: false,
      threat_level: severity,
      attack_type: "social_engineering",
      detail: `Social engineering: ${social.patterns.join(", ")}.`,
      action: severity === "HIGH" ? "BLOCK" : "FLAG",
      sanitized_input: severity === "HIGH" ? null : sanitize(input),
      patterns_matched: social.patterns,
    };
  }

  // 7. Indirect injection (encoding, Unicode, hidden content)
  const indirectChecks = [
    hasBase64(input),
    hasUnusualUnicode(input),
    isOverlong(input),
    hasSystemPromptMarkers(input),
    hasHiddenContent(input),
  ].filter(Boolean) as string[];

  if (indirectChecks.length > 0) {
    const multi = indirectChecks.length > 1;
    if (sensitivity === "high" || multi) {
      return {
        safe: false,
        threat_level: multi ? "HIGH" : "MEDIUM",
        attack_type: "indirect_injection",
        detail: indirectChecks.join(" "),
        action: multi ? "BLOCK" : "FLAG",
        sanitized_input: multi ? null : sanitize(input),
        patterns_matched: indirectChecks,
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
        patterns_matched: indirectChecks,
      };
    }
    if (indirectChecks.some(c => c.includes("System prompt") || c.includes("Base64"))) {
      return {
        safe: false,
        threat_level: "LOW",
        attack_type: "indirect_injection",
        detail: indirectChecks.join(" "),
        action: "FLAG",
        sanitized_input: sanitize(input),
        patterns_matched: indirectChecks,
      };
    }
  }

  // 8. Jailbreak
  const jailbreak = scanCategory(input, JAILBREAK, "jailbreak");
  if (jailbreak.matched) {
    if (sensitivity === "low" && jailbreak.totalWeight < 3) {
      // Low sensitivity ignores weak jailbreaks
    } else {
      const isHigh = sensitivity === "high" || jailbreak.totalWeight >= 3;
      return {
        safe: false,
        threat_level: isHigh ? "HIGH" : "MEDIUM",
        attack_type: "jailbreak",
        detail: `Jailbreak: ${jailbreak.patterns.join(", ")}.`,
        action: isHigh ? "BLOCK" : "FLAG",
        sanitized_input: isHigh ? null : sanitize(input),
        patterns_matched: jailbreak.patterns,
      };
    }
  }

  // 9. Aggregate low-weight signals across categories
  const allCategories = [exfil, toolManip, creds, privesc, social, jailbreak];
  const totalLowWeight = allCategories.reduce((sum, cat) => sum + cat.totalWeight, 0);
  if (totalLowWeight >= 3 && sensitivity !== "low") {
    const allPatterns = allCategories.flatMap(c => c.patterns);
    return {
      safe: false,
      threat_level: "MEDIUM",
      attack_type: "indirect_injection",
      detail: `Multiple suspicious signals: ${allPatterns.join(", ")}.`,
      action: "FLAG",
      sanitized_input: sanitize(input),
      patterns_matched: allPatterns,
    };
  }

  // 10. Clean
  return {
    safe: true,
    threat_level: "NONE",
    attack_type: null,
    detail: "No injection patterns detected.",
    action: "ALLOW",
    sanitized_input: null,
    patterns_matched: [],
  };
}
