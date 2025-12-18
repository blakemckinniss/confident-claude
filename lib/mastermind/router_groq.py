"""Groq API router client using Kimi K2 for task classification.

Classifies user prompts as: trivial, medium, or complex.
Returns structured JSON with classification, confidence, and reason codes.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

from .config import get_config

# Groq API endpoint
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "moonshotai/kimi-k2-instruct"

# Classification prompt
ROUTER_SYSTEM_PROMPT = """You are a task complexity classifier for an AI coding assistant.

Classify the user's request into one of three categories:
- trivial: Simple questions, lookups, single-file changes, explanations
- medium: Multi-file changes, moderate refactoring, adding features to existing code
- complex: New systems, architecture changes, multi-component features, security-sensitive work

IMPORTANT: If "Agent State" shows LOW confidence (<70%), bias toward escalating classification:
- If would be trivial but confidence LOW -> classify as medium
- If would be medium but confidence LOW -> classify as complex
- If confidence VERY LOW (<50%), always classify as complex and suggest PAL consultation

Also identify the task TYPE and suggest the best PAL MCP tool:
- debugging: Bug investigation, error tracing, fix attempts -> suggest "debug"
- planning: New features, implementation design, multi-step work -> suggest "planner"
- review: Code review, quality check, refactoring assessment -> suggest "codereview"
- architecture: System design, technology choices, tradeoffs -> suggest "consensus"
- research: API lookups, documentation needs, library usage -> suggest "apilookup"
- validation: Pre-commit checks, change verification -> suggest "precommit"
- general: Discussion, brainstorming, unclear category -> suggest "chat"

Determine if web research should be done BEFORE the main task:
- needs_research: true if current docs/APIs/versions needed
- research_topics: specific search queries (max 3)

Research triggers (set needs_research=true):
- Version-specific: "latest", "v19", "new API", "deprecated", "breaking changes"
- External tech: unfamiliar library/framework, integration questions
- Best practices: "what's the best way", "recommended approach"
- Error investigation: specific error messages with potential online solutions

Output JSON only:
{
  "classification": "trivial|medium|complex",
  "confidence": 0.0-1.0,
  "task_type": "debugging|planning|review|architecture|research|validation|general",
  "suggested_tool": "debug|planner|codereview|consensus|apilookup|precommit|chat",
  "reason_codes": ["code1", "code2"],
  "needs_research": false,
  "research_topics": []
}

Reason codes (pick 1-3):
- single_file: Affects one file
- multi_file: Affects multiple files
- new_feature: Creating new functionality
- refactor: Restructuring existing code
- bug_fix: Fixing a bug
- explanation: Just explaining/answering
- security: Security-sensitive changes
- architecture: System design changes
- config: Configuration changes
- docs: Documentation only
- test: Test-related work
- external_api: Involves external services/APIs
- version_specific: Depends on specific version behavior"""


@dataclass
class RouterResponse:
    """Parsed router classification response."""

    classification: str  # trivial, medium, complex
    confidence: float
    reason_codes: list[str]
    raw_response: str
    latency_ms: int
    task_type: str = "general"  # debugging, planning, review, architecture, research, validation, general
    suggested_tool: str = (
        "chat"  # debug, planner, codereview, consensus, apilookup, precommit, chat
    )
    needs_research: bool = False  # whether web research should be done first
    research_topics: list[str] | None = None  # specific topics to search (max 3)
    error: str | None = None

    @property
    def is_complex(self) -> bool:
        return self.classification == "complex"

    @property
    def is_uncertain(self) -> bool:
        config = get_config()
        return self.confidence < config.router.uncertainty_threshold

    @property
    def pal_tool_name(self) -> str:
        """Return the full MCP tool name for the suggested tool."""
        tool_map = {
            "debug": "mcp__pal__debug",
            "planner": "mcp__pal__planner",
            "codereview": "mcp__pal__codereview",
            "consensus": "mcp__pal__consensus",
            "apilookup": "mcp__pal__apilookup",
            "precommit": "mcp__pal__precommit",
            "chat": "mcp__pal__chat",
            "thinkdeep": "mcp__pal__thinkdeep",
        }
        return tool_map.get(self.suggested_tool, "mcp__pal__chat")


def _parse_response(text: str) -> dict[str, Any]:
    """Parse JSON from model response, handling markdown code blocks."""
    text = text.strip()

    # Handle markdown code blocks
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last lines (``` markers)
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to extract JSON from text
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
        raise


def call_groq_router(prompt: str, timeout: float = 10.0) -> RouterResponse:
    """Call Groq API to classify task complexity.

    Args:
        prompt: The packed context prompt for classification
        timeout: Request timeout in seconds

    Returns:
        RouterResponse with classification, confidence, and reason codes
    """
    import urllib.request
    import urllib.error

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return RouterResponse(
            classification="complex",
            confidence=0.0,
            reason_codes=["no_api_key"],
            raw_response="",
            latency_ms=0,
            task_type="general",
            suggested_tool="chat",
            error="GROQ_API_KEY not set",
        )

    start = time.time()

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 150,
        "response_format": {"type": "json_object"},
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        req = urllib.request.Request(
            GROQ_API_URL,
            data=json.dumps(payload).encode(),
            headers=headers,
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode())

        latency_ms = int((time.time() - start) * 1000)
        raw_text = result["choices"][0]["message"]["content"]

        try:
            parsed = _parse_response(raw_text)
            return RouterResponse(
                classification=parsed.get("classification", "complex"),
                confidence=float(parsed.get("confidence", 0.5)),
                reason_codes=parsed.get("reason_codes", []),
                raw_response=raw_text,
                latency_ms=latency_ms,
                task_type=parsed.get("task_type", "general"),
                suggested_tool=parsed.get("suggested_tool", "chat"),
                needs_research=bool(parsed.get("needs_research", False)),
                research_topics=parsed.get("research_topics") or [],
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            # Parse error - default to complex (safe fallback)
            return RouterResponse(
                classification="complex",
                confidence=0.5,
                reason_codes=["parse_error"],
                raw_response=raw_text,
                latency_ms=latency_ms,
                task_type="general",
                suggested_tool="chat",
                error=f"Parse error: {e}",
            )

    except urllib.error.HTTPError as e:
        latency_ms = int((time.time() - start) * 1000)
        return RouterResponse(
            classification="complex",
            confidence=0.0,
            reason_codes=["http_error"],
            raw_response="",
            latency_ms=latency_ms,
            task_type="general",
            suggested_tool="chat",
            error=f"HTTP {e.code}: {e.reason}",
        )
    except urllib.error.URLError as e:
        latency_ms = int((time.time() - start) * 1000)
        return RouterResponse(
            classification="complex",
            confidence=0.0,
            reason_codes=["network_error"],
            raw_response="",
            latency_ms=latency_ms,
            task_type="general",
            suggested_tool="chat",
            error=f"Network error: {e.reason}",
        )
    except TimeoutError:
        latency_ms = int((time.time() - start) * 1000)
        return RouterResponse(
            classification="complex",
            confidence=0.0,
            reason_codes=["timeout"],
            raw_response="",
            latency_ms=latency_ms,
            task_type="general",
            suggested_tool="chat",
            error="Request timed out",
        )


def apply_risk_lexicon(prompt: str, response: RouterResponse) -> RouterResponse:
    """Override classification for high-risk keywords.

    Certain keywords always escalate to complex regardless of router decision.
    """
    config = get_config()
    if not config.router.risk_lexicon_override:
        return response

    # High-risk keywords that force complex classification
    risk_keywords = [
        "security",
        "auth",
        "authentication",
        "authorization",
        "password",
        "credential",
        "secret",
        "api key",
        "token",
        "encrypt",
        "decrypt",
        "vulnerability",
        "injection",
        "delete all",
        "drop table",
        "rm -rf",
        "sudo",
        "production",
        "deploy",
        "migration",
        "rollback",
    ]

    prompt_lower = prompt.lower()
    triggered = [kw for kw in risk_keywords if kw in prompt_lower]

    if triggered and response.classification != "complex":
        return RouterResponse(
            classification="complex",
            confidence=response.confidence,
            reason_codes=response.reason_codes + ["risk_lexicon_override"],
            raw_response=response.raw_response,
            latency_ms=response.latency_ms,
            task_type=response.task_type,
            suggested_tool=response.suggested_tool,
            error=response.error,
        )

    return response
