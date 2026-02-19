"""
Meerkat AI — OpenAI Function Calling Integration

Pre-built tool definitions for OpenAI's function calling API. Register these
as tools in any chat completion call to let the model invoke Meerkat's
shield and verify endpoints.

Usage:

    import openai
    from meerkat import MeerkatClient
    from meerkat.integrations.openai import MEERKAT_TOOLS, handle_tool_call

    client = openai.OpenAI()
    mk = MeerkatClient("mk_live_...", domain="healthcare")

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "Summarize the patient note"}],
        tools=MEERKAT_TOOLS,
    )

    # Handle tool calls
    for call in response.choices[0].message.tool_calls or []:
        result = handle_tool_call(mk, call)
        print(result)
"""

from __future__ import annotations

import json
from typing import Any, Dict

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from meerkat import MeerkatClient

# ── Tool definitions ──────────────────────────────────────────────────────

MEERKAT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "meerkat_shield",
            "description": (
                "Scan untrusted text for prompt injection attacks, data "
                "exfiltration attempts, credential harvesting, jailbreaks, "
                "and other threats. Call this before processing any user input "
                "that hasn't been verified."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "input_text": {
                        "type": "string",
                        "description": "The text content to scan for attacks",
                    },
                    "sensitivity": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                        "description": "Detection sensitivity level. Default: medium",
                    },
                },
                "required": ["input_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "meerkat_verify",
            "description": (
                "Verify AI-generated text against source/reference material. "
                "Checks for numerical distortion, fabricated claims, source "
                "contradictions, and bias. Returns a trust score (0-100) and "
                "specific corrections. Call this before presenting any AI output "
                "to users or using it for decisions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "output": {
                        "type": "string",
                        "description": "The AI-generated text to verify",
                    },
                    "context": {
                        "type": "string",
                        "description": "The source/reference text to check against",
                    },
                    "input_text": {
                        "type": "string",
                        "description": "The original prompt that produced the output",
                    },
                },
                "required": ["output", "context"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "meerkat_audit",
            "description": (
                "Retrieve the full audit record for a previous shield or "
                "verify call. Use this to inspect detailed check results, "
                "session history, or review status."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "audit_id": {
                        "type": "string",
                        "description": "The audit ID from a previous shield or verify call",
                    },
                    "include_session": {
                        "type": "boolean",
                        "description": "Include full session history with all retry attempts",
                    },
                },
                "required": ["audit_id"],
            },
        },
    },
]


# ── Tool call handler ─────────────────────────────────────────────────────


def handle_tool_call(client: MeerkatClient, tool_call: Any) -> str:
    """
    Execute a Meerkat tool call from an OpenAI chat completion response.

    Args:
        client: A configured MeerkatClient instance.
        tool_call: A tool_call object from response.choices[0].message.tool_calls.

    Returns:
        JSON string with the tool result, suitable for sending back as a
        tool message in the conversation.
    """
    name = tool_call.function.name
    args = json.loads(tool_call.function.arguments)

    if name == "meerkat_shield":
        result = client.shield(
            args["input_text"],
            sensitivity=args.get("sensitivity", "medium"),
        )
        return json.dumps({
            "safe": result.safe,
            "threat_level": result.threat_level,
            "threats": result.threats,
            "audit_id": result.audit_id,
        })

    elif name == "meerkat_verify":
        result = client.verify(
            output=args["output"],
            context=args["context"],
            input=args.get("input_text"),
        )
        return json.dumps({
            "trust_score": result.trust_score,
            "status": result.status,
            "recommendations": result.recommendations,
            "remediation": result.remediation,
            "audit_id": result.audit_id,
        })

    elif name == "meerkat_audit":
        result = client.audit(
            args["audit_id"],
            include_session=args.get("include_session", False),
        )
        return json.dumps({
            "audit_id": result.audit_id,
            "trust_score": result.trust_score,
            "status": result.status,
            "domain": result.domain,
            "checks": result.checks,
            "remediation": result.remediation,
        })

    else:
        return json.dumps({"error": f"Unknown tool: {name}"})
