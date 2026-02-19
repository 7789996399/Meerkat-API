# Meerkat AI SDK

Lightweight client libraries and framework integrations for the [Meerkat Governance API](https://api.meerkatplatform.com). Add a trust and safety layer to any AI pipeline in minutes.

## What's Included

| Package | Path | Publish Target | Dependencies |
|---------|------|----------------|--------------|
| **Python SDK** | `python/meerkat.py` | PyPI: `meerkat-ai` | `requests` |
| **LangGraph Integration** | `python/integrations/langgraph.py` | Bundled with SDK | `langgraph` |
| **CrewAI Integration** | `python/integrations/crewai.py` | Bundled with SDK | `crewai`, `pydantic` |
| **OpenAI Integration** | `python/integrations/openai.py` | Bundled with SDK | `openai` |
| **TypeScript SDK** | `typescript/src/index.ts` | npm: `@meerkat-ai/sdk` | None (native fetch) |

## Quick Start

### Python

```python
from meerkat import MeerkatClient

mk = MeerkatClient("mk_live_...", domain="healthcare")

# Shield user input before sending to your LLM
shield = mk.shield("Summarize the patient note")
if not shield.safe:
    print(f"Blocked: {shield.threats}")

# Verify LLM output against source material
result = mk.verify(
    output=llm_response,
    context=patient_record,
    input="Summarize the patient note",
)
print(f"Trust: {result.trust_score}/100  Status: {result.status}")

# Retrieve full audit trail
audit = mk.audit(result.audit_id, include_session=True)
```

### TypeScript / Node.js

```typescript
import { Meerkat } from "@meerkat-ai/sdk";

const mk = new Meerkat("mk_live_...", { domain: "healthcare" });

const shield = await mk.shield("Summarize the patient note");
if (!shield.safe) {
  console.log("Blocked:", shield.threats);
}

const result = await mk.verify({
  output: llmResponse,
  context: patientRecord,
  input: "Summarize the patient note",
});
console.log(`Trust: ${result.trust_score}/100  Status: ${result.status}`);
```

## Framework Integrations

### LangGraph — Edge Validator

Drop Meerkat into any LangGraph workflow as a verification node or conditional edge.

```python
from meerkat import MeerkatClient
from meerkat.integrations.langgraph import MeerkatVerifier

mk = MeerkatClient("mk_live_...", domain="healthcare")
verifier = MeerkatVerifier(mk)

# As a verification node
graph.add_node("verify", verifier.as_node("output", "context"))
graph.add_edge("research", "verify")
graph.add_edge("verify", "draft")

# As a conditional gate (routes to pass/review/block)
graph.add_conditional_edges(
    "draft",
    verifier.as_gate("draft_output", "context"),
    {"pass": "publish", "review": "human_review", "block": "revise"},
)
```

**Behavior:**
- `PASS` / `FLAG` → continues the workflow, attaches trust metadata to state
- `BLOCK` → raises `MeerkatBlockError` (or routes to "block" in gate mode)
- `REQUEST_HUMAN_REVIEW` → routes to "review" in gate mode

### CrewAI — Agent Tools

Give any CrewAI agent the ability to shield inputs and verify outputs.

```python
from meerkat import MeerkatClient
from meerkat.integrations.crewai import MeerkatShieldTool, MeerkatVerifyTool

mk = MeerkatClient("mk_live_...", domain="healthcare")

agent = Agent(
    role="Medical Researcher",
    goal="Summarize clinical notes accurately",
    tools=[MeerkatShieldTool(client=mk), MeerkatVerifyTool(client=mk)],
)
```

The agent decides when to call each tool. `meerkat_shield` scans untrusted content; `meerkat_verify` checks AI output against source material.

### OpenAI — Function Calling

Pre-built tool schemas for OpenAI's function calling API.

```python
import openai
from meerkat import MeerkatClient
from meerkat.integrations.openai import MEERKAT_TOOLS, handle_tool_call

client = openai.OpenAI()
mk = MeerkatClient("mk_live_...", domain="healthcare")

response = client.chat.completions.create(
    model="gpt-4o",
    messages=messages,
    tools=MEERKAT_TOOLS,
)

# Handle any Meerkat tool calls
for call in response.choices[0].message.tool_calls or []:
    result = handle_tool_call(mk, call)
    # Append as tool message for the next turn
    messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
```

Available tools: `meerkat_shield`, `meerkat_verify`, `meerkat_audit`.

## API Reference

### MeerkatClient / Meerkat

| Method | Description | Returns |
|--------|-------------|---------|
| `shield(input)` | Scan text for prompt injection and attacks | `ShieldResult` |
| `verify(output, context)` | Verify AI output against source material | `VerifyResult` |
| `audit(audit_id)` | Retrieve full audit record | `AuditResult` |

### ShieldResult

| Field | Type | Description |
|-------|------|-------------|
| `safe` | `bool` | Whether the input is safe |
| `threat_level` | `str` | `NONE`, `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` |
| `threats` | `list` | Detected threats with type, description, severity |
| `audit_id` | `str` | Audit trail identifier |
| `sanitized_input` | `str?` | Input with threats removed (if applicable) |
| `remediation` | `dict?` | Suggested remediation action |

### VerifyResult

| Field | Type | Description |
|-------|------|-------------|
| `trust_score` | `int` | 0–100 composite trust score |
| `status` | `str` | `PASS`, `FLAG`, or `BLOCK` |
| `checks` | `dict` | Per-check scores (entailment, numerical, claims, preference, entropy) |
| `remediation` | `dict?` | Corrections, suggested action, agent instructions |
| `audit_id` | `str` | Audit trail identifier |
| `session_id` | `str` | Session ID for multi-attempt retry flows |
| `recommendations` | `list` | Human-readable recommendations |

## Authentication

All API calls require an API key passed as `Authorization: Bearer mk_live_...`. Get your key from the [Meerkat Dashboard](https://app.meerkatplatform.com) or via the registration endpoint:

```bash
curl -X POST https://api.meerkatplatform.com/v1/register \
  -H "Content-Type: application/json" \
  -d '{"org_name": "My Org", "domain": "healthcare", "email": "admin@example.com"}'
```

## Status

These SDKs are ready for internal use and testing. Not yet published to PyPI or npm.
