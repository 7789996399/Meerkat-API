"""
Meerkat MCP Server -- Cowork Plugin Integration

Thin wrapper that exposes the Meerkat Governance API as MCP tools.
Any Anthropic Cowork plugin can connect by adding this server to its
MCP config. The server translates MCP tool calls into REST API calls
to the existing Meerkat endpoints.

No business logic lives here -- just HTTP calls and JSON formatting.

Run with:
    python mcp/meerkat_mcp_server.py

Environment variables:
    MEERKAT_API_URL  -- Base URL of the Meerkat API (default: http://localhost:8000)
    MEERKAT_API_KEY  -- API key for authentication (default: mk_demo_test123)
"""

import json
import os

import httpx
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Config -- read from environment or use demo defaults
# ---------------------------------------------------------------------------

API_URL = os.environ.get("MEERKAT_API_URL", "http://localhost:8000")
API_KEY = os.environ.get("MEERKAT_API_KEY", "mk_demo_test123")
TIMEOUT = 30.0

# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP("meerkat-governance")


async def _api_call(method: str, path: str, **kwargs) -> dict:
    """Make an HTTP call to the Meerkat REST API.
    Returns the JSON response or an error dict."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            url = f"{API_URL}{path}"
            headers = {"Authorization": f"Bearer {API_KEY}"}
            if method == "GET":
                r = await client.get(url, headers=headers, **kwargs)
            else:
                r = await client.post(url, headers=headers, **kwargs)
            r.raise_for_status()
            return r.json()
    except httpx.ConnectError:
        return {"error": f"Cannot connect to Meerkat API at {API_URL}. Is the server running?"}
    except httpx.HTTPStatusError as e:
        return {"error": f"API returned {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        return {"error": f"Unexpected error: {e}"}


# ---------------------------------------------------------------------------
# Tool 1: meerkat_shield
# ---------------------------------------------------------------------------

@mcp.tool()
async def meerkat_shield(
    input: str,
    domain: str = "general",
    sensitivity: str = "medium",
) -> str:
    """Scan input for prompt injection attacks before sending to AI. Returns threat assessment.

    Use this BEFORE sending user input to an AI model. Catches direct injection,
    jailbreak attempts, role manipulation, and prompt extraction attacks.

    Args:
        input: The raw user input to scan for threats.
        domain: Industry domain (legal, financial, healthcare, general).
        sensitivity: Detection sensitivity (low, medium, high).
    """
    data = await _api_call("POST", "/v1/shield", json={
        "input": input,
        "domain": domain,
        "sensitivity": sensitivity,
    })
    if "error" in data:
        return json.dumps(data, indent=2)
    return json.dumps({
        "safe": data["safe"],
        "threat_level": data["threat_level"],
        "action": data["action"],
        "detail": data["detail"],
        "attack_type": data.get("attack_type"),
    }, indent=2)


# ---------------------------------------------------------------------------
# Tool 2: meerkat_verify
# ---------------------------------------------------------------------------

@mcp.tool()
async def meerkat_verify(
    input: str,
    output: str,
    context: str = "",
    domain: str = "general",
    checks: list[str] | None = None,
    config_id: str | None = None,
) -> str:
    """Verify AI output for hallucinations, bias, and factual accuracy. Returns trust score and flags.

    Use this AFTER getting an AI response and BEFORE showing it to the user.
    Runs entailment checking, semantic entropy analysis, bias detection,
    and claim extraction against a source document.

    Args:
        input: The original user prompt that was sent to the AI.
        output: The AI model's response to verify.
        context: Source document or reference text for entailment checking.
        domain: Industry domain (legal, financial, healthcare, general).
        checks: Which checks to run (entailment, semantic_entropy, implicit_preference, claim_extraction).
        config_id: Organization config ID from meerkat_configure (overrides domain defaults).
    """
    payload: dict = {
        "input": input,
        "output": output,
        "domain": domain,
    }
    if context:
        payload["context"] = context
    if checks:
        payload["checks"] = checks
    if config_id:
        payload["config_id"] = config_id

    data = await _api_call("POST", "/v1/verify", json=payload)
    if "error" in data:
        return json.dumps(data, indent=2)
    return json.dumps({
        "trust_score": data["trust_score"],
        "status": data["status"],
        "audit_id": data["audit_id"],
        "checks": data["checks"],
        "recommendations": data["recommendations"],
    }, indent=2)


# ---------------------------------------------------------------------------
# Tool 3: meerkat_audit
# ---------------------------------------------------------------------------

@mcp.tool()
async def meerkat_audit(audit_id: str) -> str:
    """Retrieve governance audit trail for a previous verification.

    Every call to meerkat_verify creates an immutable audit record.
    Use the audit_id from a verify response to retrieve the full record,
    including timestamp, domain, scores, flags, and review status.

    Args:
        audit_id: The audit trail ID returned by meerkat_verify.
    """
    data = await _api_call("GET", f"/v1/audit/{audit_id}")
    if "error" in data:
        return json.dumps(data, indent=2)
    return json.dumps(data, indent=2)


# ---------------------------------------------------------------------------
# Tool 4: meerkat_configure
# ---------------------------------------------------------------------------

@mcp.tool()
async def meerkat_configure(
    org_id: str,
    domain: str = "general",
    auto_approve_threshold: int = 85,
    auto_block_threshold: int = 40,
    required_checks: list[str] | None = None,
) -> str:
    """Set governance thresholds and rules for your organization.

    Creates a reusable configuration. Pass the returned config_id
    to meerkat_verify to apply your custom rules automatically.

    Args:
        org_id: Your organization identifier.
        domain: Primary industry domain (legal, financial, healthcare, general).
        auto_approve_threshold: Trust scores at or above this value are auto-approved (0-100).
        auto_block_threshold: Trust scores below this value are auto-blocked (0-100).
        required_checks: Checks that must run on every verification (entailment, semantic_entropy, implicit_preference, claim_extraction).
    """
    payload: dict = {
        "org_id": org_id,
        "domain": domain,
        "auto_approve_threshold": auto_approve_threshold,
        "auto_block_threshold": auto_block_threshold,
    }
    if required_checks:
        payload["required_checks"] = required_checks

    data = await _api_call("POST", "/v1/configure", json=payload)
    if "error" in data:
        return json.dumps(data, indent=2)
    return json.dumps({
        "config_id": data["config_id"],
        "status": data["status"],
        "domain": data["domain"],
        "created": data["created"],
    }, indent=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
