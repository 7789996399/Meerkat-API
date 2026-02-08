# Meerkat MCP Server

Connect Meerkat governance to any Anthropic Cowork plugin with a single config block.

The MCP (Model Context Protocol) server is a thin wrapper that translates
MCP tool calls into REST API calls to your running Meerkat instance. No
business logic lives here -- all governance checks run on the Meerkat API.

---

## Setup

### Step 1: Make sure the Meerkat API is running

```bash
# From the project root
pip install -r requirements.txt
uvicorn api.main:app --host 0.0.0.0 --port 8000

# Or with Docker
docker compose up
```

Verify it is running:

```bash
curl http://localhost:8000/v1/health
```

### Step 2: Add Meerkat to your plugin's MCP config

In your Cowork plugin configuration file, add:

```json
{
  "mcp_servers": {
    "meerkat-governance": {
      "command": "python",
      "args": ["path/to/meerkat_mcp_server.py"],
      "env": {
        "MEERKAT_API_URL": "http://localhost:8000",
        "MEERKAT_API_KEY": "mk_demo_test123"
      }
    }
  }
}
```

Replace `path/to/meerkat_mcp_server.py` with the actual path on your
system.

### Step 3: Use your plugin as normal

Once connected, Claude automatically has access to four governance tools.
You can use them explicitly ("scan this input with meerkat") or the plugin
can call them automatically as part of its workflow.

---

## Available Tools

| Tool | Purpose |
|------|---------|
| `meerkat_shield` | Pre-flight scan of user input for prompt injection, jailbreaks, and policy violations |
| `meerkat_verify` | Post-flight verification of AI output for hallucinations, bias, and factual accuracy |
| `meerkat_audit` | Retrieve the immutable audit trail for any previous verification |
| `meerkat_configure` | Set organization-specific thresholds, required checks, and domain rules |

---

## What Claude sees

When the MCP server is connected, Claude sees these tools available:

```
Available tools:
  - meerkat_shield: Scan input for prompt injection attacks before sending
    to AI. Returns threat assessment.
  - meerkat_verify: Verify AI output for hallucinations, bias, and factual
    accuracy. Returns trust score and flags.
  - meerkat_audit: Retrieve governance audit trail for a previous verification.
  - meerkat_configure: Set governance thresholds and rules for your organization.
```

---

## Example: Shield + Verify workflow

**Step 1 -- Claude scans the user input before processing:**

```json
{
  "tool": "meerkat_shield",
  "arguments": {
    "input": "Review this NDA and identify high-risk clauses.",
    "domain": "legal",
    "sensitivity": "high"
  }
}
```

Response:

```json
{
  "safe": true,
  "threat_level": "NONE",
  "action": "ALLOW",
  "detail": "Input passed all threat checks. No injection patterns detected.",
  "attack_type": null
}
```

**Step 2 -- Claude generates a response, then verifies it:**

```json
{
  "tool": "meerkat_verify",
  "arguments": {
    "input": "Review this NDA and identify high-risk clauses.",
    "output": "Section 3.1 contains a twelve month non-compete clause...",
    "context": "<full NDA text>",
    "domain": "legal"
  }
}
```

Response:

```json
{
  "trust_score": 94,
  "status": "PASS",
  "audit_id": "aud_20260208_a1b2c3d4",
  "checks": {
    "entailment": { "score": 1.0, "flags": [], "detail": "All 5 claims are grounded in the source document." },
    "semantic_entropy": { "score": 0.867, "flags": [], "detail": "Output shows high confidence with specific facts." },
    "implicit_preference": { "score": 0.88, "flags": [], "detail": "Output uses neutral, balanced language." },
    "claim_extraction": { "score": 1.0, "flags": [], "detail": "Extracted 11 factual claim(s). 11 verified." }
  },
  "recommendations": []
}
```

Score >= 75 means PASS -- the response is safe to deliver to the user.

---

## Testing

Run the integration tests (requires the API server to be running):

```bash
# Start the API
uvicorn api.main:app --port 8000 &

# Run the MCP test suite
python mcp/test_mcp.py
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MEERKAT_API_URL` | `http://localhost:8000` | Base URL of the Meerkat REST API |
| `MEERKAT_API_KEY` | `mk_demo_test123` | API key for authentication |

---

## How it works

```
Cowork Plugin                 MCP Server                    Meerkat API
    |                             |                              |
    |-- call meerkat_shield ----->|                              |
    |                             |-- POST /v1/shield ---------->|
    |                             |<-- { safe, action, ... } ----|
    |<-- tool result -------------|                              |
    |                             |                              |
    |-- call meerkat_verify ----->|                              |
    |                             |-- POST /v1/verify ---------->|
    |                             |<-- { score, status, ... } ---|
    |<-- tool result -------------|                              |
```

The MCP server is stateless. All state (audit records, configs) lives
in the Meerkat API.
