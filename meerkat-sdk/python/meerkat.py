"""
Meerkat AI — Python SDK

Lightweight client for the Meerkat Governance API. Adds a trust and safety
layer to any AI pipeline: prompt shielding, output verification, and audit.

    pip install meerkat-ai

Usage:

    from meerkat import MeerkatClient

    mk = MeerkatClient("mk_live_...", domain="healthcare")

    # Shield user input before sending to LLM
    shield = mk.shield("Summarize the patient note")
    if not shield.safe:
        print(f"Blocked: {shield.threats}")

    # Verify LLM output against source
    result = mk.verify(
        output=llm_response,
        context=patient_record,
        input="Summarize the patient note",
    )
    print(f"Trust: {result.trust_score}  Status: {result.status}")

    if result.remediation:
        print(f"Action: {result.remediation['suggested_action']}")

    # Retrieve full audit trail
    audit = mk.audit(result.audit_id)

Requirements: requests
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests

__version__ = "0.1.0"

DEFAULT_BASE_URL = "https://api.meerkatplatform.com"
DEFAULT_TIMEOUT = 120


# ── Result types ──────────────────────────────────────────────────────────


@dataclass
class ShieldResult:
    """Result from the /v1/shield endpoint."""

    safe: bool
    threat_level: str
    audit_id: str
    session_id: str
    threats: List[Dict[str, Any]] = field(default_factory=list)
    sanitized_input: Optional[str] = None
    remediation: Optional[Dict[str, Any]] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class VerifyResult:
    """Result from the /v1/verify endpoint."""

    trust_score: int
    status: str  # "PASS" | "FLAG" | "BLOCK"
    checks: Dict[str, Any]
    audit_id: str
    session_id: str
    attempt: int
    verification_mode: str
    recommendations: List[str] = field(default_factory=list)
    remediation: Optional[Dict[str, Any]] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class AuditResult:
    """Result from the /v1/audit/:auditId endpoint."""

    audit_id: str
    trust_score: int
    status: str
    domain: str
    checks: Dict[str, Any]
    timestamp: str
    remediation: Optional[Dict[str, Any]] = None
    session: Optional[Dict[str, Any]] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)


# ── Exceptions ────────────────────────────────────────────────────────────


class MeerkatError(Exception):
    """Base exception for Meerkat SDK errors."""

    def __init__(self, message: str, status_code: Optional[int] = None, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class MeerkatBlockError(MeerkatError):
    """Raised when verification returns BLOCK status."""

    def __init__(self, result: VerifyResult):
        super().__init__(
            f"Verification BLOCK (trust_score={result.trust_score})",
            status_code=None,
            body=result.raw,
        )
        self.result = result


# ── Client ────────────────────────────────────────────────────────────────


class MeerkatClient:
    """
    Client for the Meerkat Governance API.

    Args:
        api_key: Your Meerkat API key (mk_live_...).
        domain: Default domain for requests ("healthcare", "financial", "legal", "general").
        base_url: API base URL. Defaults to https://api.meerkatplatform.com.
        timeout: Request timeout in seconds. Defaults to 120.
    """

    def __init__(
        self,
        api_key: str,
        domain: str = "general",
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.api_key = api_key
        self.domain = domain
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
        )

    def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        kwargs.setdefault("timeout", self.timeout)
        resp = self._session.request(method, url, **kwargs)
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except Exception:
                body = resp.text
            raise MeerkatError(
                f"API error {resp.status_code}: {body}",
                status_code=resp.status_code,
                body=body,
            )
        return resp.json()

    # ── Shield ────────────────────────────────────────────────────────

    def shield(
        self,
        input_text: str,
        *,
        sensitivity: str = "medium",
        session_id: Optional[str] = None,
    ) -> ShieldResult:
        """
        Scan input for prompt injection, data exfiltration, and other attacks.

        Args:
            input_text: The user/agent input to scan.
            sensitivity: Detection sensitivity ("low", "medium", "high").
            session_id: Optional session ID to link with verification calls.

        Returns:
            ShieldResult with safe/threat_level/threats.
        """
        payload: Dict[str, Any] = {
            "input": input_text,
            "domain": self.domain,
            "sensitivity": sensitivity,
        }
        if session_id:
            payload["session_id"] = session_id

        data = self._request("POST", "/v1/shield", json=payload)
        return ShieldResult(
            safe=data["safe"],
            threat_level=data["threat_level"],
            audit_id=data["audit_id"],
            session_id=data["session_id"],
            threats=data.get("threats", []),
            sanitized_input=data.get("sanitized_input"),
            remediation=data.get("remediation"),
            raw=data,
        )

    # ── Verify ────────────────────────────────────────────────────────

    def verify(
        self,
        output: str,
        context: str,
        *,
        input: Optional[str] = None,
        domain: Optional[str] = None,
        session_id: Optional[str] = None,
        checks: Optional[List[str]] = None,
        config_id: Optional[str] = None,
        agent_name: Optional[str] = None,
        model: Optional[str] = None,
    ) -> VerifyResult:
        """
        Verify AI output against source context.

        Args:
            output: The AI-generated text to verify.
            context: Source/reference text to verify against.
            input: The original user prompt (used for entropy check).
            domain: Override the client-level domain for this call.
            session_id: Session ID for multi-attempt retry flows.
            checks: Specific checks to run (default: all required by config).
            config_id: Configuration ID to use.
            agent_name: Name of the agent that produced the output.
            model: Model that generated the output.

        Returns:
            VerifyResult with trust_score/status/checks/remediation.
        """
        payload: Dict[str, Any] = {
            "input": input or "Verify this output",
            "output": output,
            "context": context,
            "domain": domain or self.domain,
        }
        if session_id:
            payload["session_id"] = session_id
        if checks:
            payload["checks"] = checks
        if config_id:
            payload["config_id"] = config_id
        if agent_name:
            payload["agent_name"] = agent_name
        if model:
            payload["model"] = model

        data = self._request("POST", "/v1/verify", json=payload)
        return VerifyResult(
            trust_score=data["trust_score"],
            status=data["status"],
            checks=data["checks"],
            audit_id=data["audit_id"],
            session_id=data["session_id"],
            attempt=data["attempt"],
            verification_mode=data["verification_mode"],
            recommendations=data.get("recommendations", []),
            remediation=data.get("remediation"),
            raw=data,
        )

    # ── Audit ─────────────────────────────────────────────────────────

    def audit(
        self,
        audit_id: str,
        *,
        include_session: bool = False,
    ) -> AuditResult:
        """
        Retrieve the full audit record for a verification.

        Args:
            audit_id: The audit ID returned from shield() or verify().
            include_session: Include full session history with all attempts.

        Returns:
            AuditResult with the complete verification record.
        """
        path = f"/v1/audit/{audit_id}"
        if include_session:
            path += "?include=session"

        data = self._request("GET", path)
        return AuditResult(
            audit_id=data["audit_id"],
            trust_score=data["trust_score"],
            status=data["status"],
            domain=data["domain"],
            checks=data["checks"],
            timestamp=data["timestamp"],
            remediation=data.get("remediation"),
            session=data.get("session"),
            raw=data,
        )
