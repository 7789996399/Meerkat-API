"""
Meerkat AI — CrewAI Integration

Tools that any CrewAI agent can use to shield untrusted content and verify
AI-generated output against source material.

Usage:

    from meerkat import MeerkatClient
    from meerkat.integrations.crewai import MeerkatShieldTool, MeerkatVerifyTool

    client = MeerkatClient("mk_live_...", domain="healthcare")

    shield_tool = MeerkatShieldTool(client=client)
    verify_tool = MeerkatVerifyTool(client=client)

    from crewai import Agent

    researcher = Agent(
        role="Medical Researcher",
        goal="Summarize clinical notes accurately",
        tools=[shield_tool, verify_tool],
    )

    # The agent can now call these tools during task execution:
    #   shield_tool.run("user input to scan")
    #   verify_tool.run(output="AI text", context="source text")
"""

from __future__ import annotations

from typing import Any, Optional, Type

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from meerkat import MeerkatClient

try:
    from crewai.tools import BaseTool
    from pydantic import BaseModel, Field
except ImportError:
    raise ImportError(
        "CrewAI integration requires 'crewai' and 'pydantic'. "
        "Install with: pip install crewai pydantic"
    )


# ── Shield Tool ───────────────────────────────────────────────────────────


class ShieldInput(BaseModel):
    input_text: str = Field(description="The text content to scan for attacks or injection attempts")
    sensitivity: str = Field(default="medium", description="Detection sensitivity: low, medium, or high")


class MeerkatShieldTool(BaseTool):
    """Scan untrusted content for prompt injection, data exfiltration, and other attacks."""

    name: str = "meerkat_shield"
    description: str = (
        "Scan text for prompt injection attacks, data exfiltration attempts, "
        "credential harvesting, and other threats. Returns safe/unsafe with "
        "threat details. Use this before processing any untrusted user input."
    )
    args_schema: Type[BaseModel] = ShieldInput
    client: Any = None  # MeerkatClient, typed as Any to avoid pydantic issues

    def __init__(self, client: MeerkatClient, **kwargs):
        super().__init__(client=client, **kwargs)

    def _run(self, input_text: str, sensitivity: str = "medium") -> str:
        result = self.client.shield(input_text, sensitivity=sensitivity)

        if result.safe:
            return f"SAFE — No threats detected. Threat level: {result.threat_level}"

        threat_lines = []
        for t in result.threats:
            threat_lines.append(f"  - {t.get('type', 'unknown')}: {t.get('description', '')}")

        return (
            f"UNSAFE — {len(result.threats)} threat(s) detected.\n"
            f"Threat level: {result.threat_level}\n"
            f"Threats:\n" + "\n".join(threat_lines) + "\n"
            f"Audit ID: {result.audit_id}"
        )


# ── Verify Tool ───────────────────────────────────────────────────────────


class VerifyInput(BaseModel):
    output: str = Field(description="The AI-generated text to verify for accuracy")
    context: str = Field(description="The source/reference text to verify against")
    input_text: Optional[str] = Field(default=None, description="The original user prompt that generated the output")


class MeerkatVerifyTool(BaseTool):
    """Verify AI-generated content against source material for accuracy and safety."""

    name: str = "meerkat_verify"
    description: str = (
        "Verify AI-generated text against source/reference material. Checks for "
        "numerical distortion, fabricated claims, source contradictions, and bias. "
        "Returns a trust score (0-100), status (PASS/FLAG/BLOCK), and specific "
        "corrections if issues are found. Use this after generating any output "
        "that will be shown to users or used for decisions."
    )
    args_schema: Type[BaseModel] = VerifyInput
    client: Any = None

    def __init__(self, client: MeerkatClient, **kwargs):
        super().__init__(client=client, **kwargs)

    def _run(self, output: str, context: str, input_text: Optional[str] = None) -> str:
        result = self.client.verify(
            output=output,
            context=context,
            input=input_text,
        )

        lines = [
            f"Trust Score: {result.trust_score}/100",
            f"Status: {result.status}",
            f"Mode: {result.verification_mode}",
        ]

        if result.recommendations:
            lines.append("Recommendations:")
            for rec in result.recommendations:
                lines.append(f"  - {rec}")

        if result.remediation:
            action = result.remediation.get("suggested_action", "")
            lines.append(f"Suggested Action: {action}")
            instruction = result.remediation.get("agent_instruction", "")
            if instruction:
                lines.append(f"Instruction: {instruction}")

        lines.append(f"Audit ID: {result.audit_id}")
        return "\n".join(lines)
