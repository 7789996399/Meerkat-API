"""
Meerkat AI — LangGraph Integration

Drop-in trust layer for LangGraph workflows. Shields inputs and verifies
outputs at graph edges, blocking unsafe content and pausing for human
review when needed.

Usage:

    from meerkat import MeerkatClient
    from meerkat.integrations.langgraph import MeerkatVerifier

    client = MeerkatClient("mk_live_...", domain="healthcare")
    verifier = MeerkatVerifier(client)

    # As a node function in your graph
    from langgraph.graph import StateGraph

    def research(state):
        # ... your research logic ...
        return {**state, "research_output": result, "research_context": sources}

    def draft(state):
        # ... your drafting logic ...
        return {**state, "draft_output": result}

    graph = StateGraph(dict)
    graph.add_node("research", research)
    graph.add_node("verify_research", verifier.as_node("research_output", "research_context"))
    graph.add_node("draft", draft)

    graph.add_edge("research", "verify_research")
    graph.add_edge("verify_research", "draft")

    # Or use the convenience wrapper for conditional edges
    graph.add_conditional_edges(
        "draft",
        verifier.as_gate("draft_output", "research_context"),
        {"pass": "publish", "review": "human_review", "block": "revise"},
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import sys
import os

# Allow importing from parent directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from meerkat import MeerkatClient, MeerkatBlockError, VerifyResult


MEERKAT_TRUST_KEY = "meerkat_trust"


@dataclass
class MeerkatNodeResult:
    """Trust metadata attached to graph state after verification."""

    trust_score: int
    status: str
    audit_id: str
    session_id: str
    suggested_action: Optional[str] = None
    remediation: Optional[Dict[str, Any]] = None


class MeerkatVerifier:
    """
    Trust layer for LangGraph workflows.

    Shields inputs for prompt injection and verifies outputs against source
    context. Integrates as a graph node or conditional edge function.

    Args:
        client: A configured MeerkatClient instance.
        shield_inputs: Whether to run prompt shield on inputs. Default True.
        raise_on_block: Raise MeerkatBlockError on BLOCK status. Default True.
        trust_key: State key to store trust metadata under. Default "meerkat_trust".
    """

    def __init__(
        self,
        client: MeerkatClient,
        *,
        shield_inputs: bool = True,
        raise_on_block: bool = True,
        trust_key: str = MEERKAT_TRUST_KEY,
    ):
        self.client = client
        self.shield_inputs = shield_inputs
        self.raise_on_block = raise_on_block
        self.trust_key = trust_key

    def verify_state(
        self,
        state: Dict[str, Any],
        output_key: str,
        context_key: str,
        input_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Verify a state dict's output against its context.

        Args:
            state: The LangGraph state dict.
            output_key: Key containing the AI output to verify.
            context_key: Key containing the source context.
            input_key: Optional key containing the original user input.

        Returns:
            Updated state with trust metadata under self.trust_key.

        Raises:
            MeerkatBlockError: If status is BLOCK and raise_on_block is True.
        """
        output = state.get(output_key, "")
        context = state.get(context_key, "")
        user_input = state.get(input_key, "") if input_key else None

        if not output:
            return state

        # Shield the input if enabled and available
        if self.shield_inputs and user_input:
            shield_result = self.client.shield(user_input)
            if not shield_result.safe:
                if self.raise_on_block:
                    raise MeerkatBlockError(VerifyResult(
                        trust_score=0,
                        status="BLOCK",
                        checks={},
                        audit_id=shield_result.audit_id,
                        session_id=shield_result.session_id,
                        attempt=0,
                        verification_mode="shield",
                        remediation=shield_result.remediation,
                    ))
                state[self.trust_key] = MeerkatNodeResult(
                    trust_score=0,
                    status="BLOCK",
                    audit_id=shield_result.audit_id,
                    session_id=shield_result.session_id,
                    suggested_action="ABORT_ACTION",
                    remediation=shield_result.remediation,
                )
                return state

        # Verify output against context
        result = self.client.verify(
            output=output,
            context=context,
            input=user_input,
        )

        trust_meta = MeerkatNodeResult(
            trust_score=result.trust_score,
            status=result.status,
            audit_id=result.audit_id,
            session_id=result.session_id,
            suggested_action=(
                result.remediation.get("suggested_action") if result.remediation else None
            ),
            remediation=result.remediation,
        )
        state[self.trust_key] = trust_meta

        if result.status == "BLOCK" and self.raise_on_block:
            raise MeerkatBlockError(result)

        return state

    def as_node(
        self,
        output_key: str,
        context_key: str,
        input_key: Optional[str] = None,
    ) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
        """
        Return a LangGraph node function that verifies state.

        Usage:
            graph.add_node("verify", verifier.as_node("output", "context"))
        """

        def node_fn(state: Dict[str, Any]) -> Dict[str, Any]:
            return self.verify_state(state, output_key, context_key, input_key)

        node_fn.__name__ = f"meerkat_verify_{output_key}"
        return node_fn

    def as_gate(
        self,
        output_key: str,
        context_key: str,
        input_key: Optional[str] = None,
    ) -> Callable[[Dict[str, Any]], str]:
        """
        Return a conditional edge function for routing based on trust status.

        Returns "pass", "review", or "block" based on verification result.

        Usage:
            graph.add_conditional_edges(
                "draft",
                verifier.as_gate("draft_output", "context"),
                {"pass": "publish", "review": "human_review", "block": "revise"},
            )
        """

        def gate_fn(state: Dict[str, Any]) -> str:
            updated = self.verify_state(
                state, output_key, context_key, input_key
            )
            trust: Optional[MeerkatNodeResult] = updated.get(self.trust_key)
            if trust is None:
                return "pass"
            if trust.status == "BLOCK":
                return "block"
            if trust.suggested_action == "REQUEST_HUMAN_REVIEW":
                return "review"
            return "pass"

        gate_fn.__name__ = f"meerkat_gate_{output_key}"
        return gate_fn
