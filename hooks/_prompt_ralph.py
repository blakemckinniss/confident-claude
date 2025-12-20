#!/usr/bin/env python3
"""
Ralph-Wiggum Task Detection Hook (v4.23)

Detects non-trivial tasks and activates "always-on ralph" mode.
This ensures tasks are completed fully through sessions until done.

Philosophy: https://ghuntley.com/ralph/
- Iteration > Perfection
- Failures Are Data
- Persistence Wins

Priority: 15 (early in UserPromptSubmit chain, before mastermind routing)
"""

from __future__ import annotations

import re

from _prompt_registry import register_hook
from _hook_result import HookResult
from session_state import SessionState

# Task complexity signals
IMPLEMENTATION_KEYWORDS = {
    # Strong signals (multi-file, substantial work)
    "implement",
    "build",
    "create",
    "develop",
    "add feature",
    "new feature",
    "refactor",
    "migrate",
    "rewrite",
    "redesign",
    "integrate",
    "setup",
    "configure",
    # Medium signals (code changes)
    "fix bug",
    "debug",
    "update",
    "modify",
    "change",
    "extend",
    "enhance",
    "improve",
    "optimize",
}

TRIVIAL_KEYWORDS = {
    # Skip ralph for these
    "explain",
    "what is",
    "how does",
    "why does",
    "show me",
    "list",
    "describe",
    "help",
    "question",
    "lookup",
    "find",
    "search",
    "read",
    "check",
    "verify",  # verification is quick
    "status",
    "diff",
    "log",
}

# Interrogative patterns that indicate questions about feasibility, not implementation requests
# These contain implementation keywords but are asking "could we?" not "do it"
FEASIBILITY_PATTERNS = [
    r"\bcould\s+(it|this|we|i)\s+(?:be\s+)?(?:implement|build|create|integrate)",
    r"\bcan\s+(it|this|we|i)\s+(?:be\s+)?(?:implement|build|create|integrate)",
    r"\bis\s+it\s+possible\s+to\s+(?:implement|build|create|integrate)",
    r"\bwould\s+it\s+(?:be\s+)?possible\s+to",
    r"\bhow\s+(?:would|could)\s+(?:we|i|you)\s+(?:implement|build|create|integrate)",
    r"\bwhat\s+would\s+it\s+take\s+to",
    r"\bfeasib(?:le|ility)\b",
    r"\bpossible\s+to\s+(?:implement|build|add|create)",
    r"\?\s*$",  # Ends with question mark - strong signal
]

# File patterns that indicate substantial work
MULTI_FILE_PATTERNS = [
    r"\b\d+\s*files?\b",  # "5 files", "multiple files"
    r"\bmultiple\b",
    r"\bacross\b",
    r"\bthroughout\b",
    r"\bsystem\b",
    r"\barchitecture\b",
    r"\binfrastructure\b",
    r"\bframework\b",
]

# Test/build requirement patterns
VERIFICATION_PATTERNS = [
    r"\btest",
    r"\bbuild\b",
    r"\blint\b",
    r"\bci\b",
    r"\bpipeline\b",
    r"\bdeploy\b",
]


def detect_task_complexity(prompt: str) -> tuple[str, list[str]]:
    """
    Analyze prompt to determine if ralph mode should activate.

    Returns:
        (mode, criteria) where:
        - mode: "" (skip), "auto" (activate)
        - criteria: list of inferred acceptance criteria
    """
    prompt_lower = prompt.lower()

    # Check for feasibility/interrogative patterns FIRST
    # These contain implementation keywords but are questions, not requests
    for pattern in FEASIBILITY_PATTERNS:
        if re.search(pattern, prompt_lower):
            return "", []  # Skip ralph - this is a research/feasibility question

    # Check for trivial task signals first
    for keyword in TRIVIAL_KEYWORDS:
        if keyword in prompt_lower:
            # But check if it's combined with implementation
            has_impl = any(kw in prompt_lower for kw in IMPLEMENTATION_KEYWORDS)
            if not has_impl:
                return "", []

    # Check for implementation signals
    impl_signals = []
    for keyword in IMPLEMENTATION_KEYWORDS:
        if keyword in prompt_lower:
            impl_signals.append(keyword)

    # Check for multi-file patterns
    multi_file = False
    for pattern in MULTI_FILE_PATTERNS:
        if re.search(pattern, prompt_lower):
            multi_file = True
            break

    # Check for verification requirements
    needs_verification = []
    for pattern in VERIFICATION_PATTERNS:
        if re.search(pattern, prompt_lower):
            needs_verification.append(pattern.replace(r"\b", ""))

    # Decision logic
    if not impl_signals and not multi_file:
        return "", []

    # Build acceptance criteria from prompt analysis
    criteria = []

    if needs_verification:
        if any("test" in v for v in needs_verification):
            criteria.append("Tests pass")
        if any("build" in v for v in needs_verification):
            criteria.append("Build succeeds")
        if any("lint" in v for v in needs_verification):
            criteria.append("Lint passes")
    else:
        # Default criteria for implementation tasks
        criteria.append("Tests pass (if applicable)")
        criteria.append("No errors in execution")

    if multi_file:
        criteria.append("All affected files updated")

    return "auto", criteria


def extract_goal_summary(prompt: str, max_length: int = 100) -> str:
    """Extract a concise goal summary from the prompt."""
    # Take first sentence or first N chars
    first_sentence = prompt.split(".")[0].strip()
    if len(first_sentence) <= max_length:
        return first_sentence
    return prompt[:max_length].rsplit(" ", 1)[0] + "..."


@register_hook("ralph_detection", priority=15)
def check_ralph_detection(data: dict, state: SessionState) -> HookResult:
    """
    Detect non-trivial tasks and activate ralph mode.

    Updates state with:
    - ralph_mode: str
    - task_contract: dict
    - completion_confidence: int
    - completion_evidence: list
    """
    prompt = data.get("prompt", "")

    # Skip if ralph already explicitly activated
    if state.ralph_mode == "explicit":
        return HookResult.none()

    # Skip very short prompts (likely follow-ups)
    if len(prompt.strip()) < 20:
        return HookResult.none()

    # Detect complexity
    mode, criteria = detect_task_complexity(prompt)

    if not mode:
        # Trivial task - ensure ralph is off
        if state.ralph_mode:
            state.ralph_mode = ""
        return HookResult.none()

    # Build task contract
    goal = extract_goal_summary(prompt)
    contract = {
        "goal": goal,
        "criteria": criteria,
        "evidence_required": ["test_pass", "build_success"],
        "created_turn": state.turn_count,
    }

    # Update state directly
    state.ralph_mode = mode
    state.task_contract = contract
    state.completion_confidence = 0
    state.completion_evidence = []
    state.ralph_strictness = "strict"
    state.ralph_nag_budget = 2

    # Injection message (subtle, not intrusive)
    message = f"""🎯 **Task Tracking Active** (ralph-wiggum)
Goal: {goal}
Criteria: {", ".join(criteria)}
Evidence required before completion."""

    return HookResult.with_context(message)


# For direct testing
if __name__ == "__main__":
    test_prompts = [
        "Explain how the confidence system works",
        "Implement a new feature for user authentication",
        "Build a REST API with tests",
        "Fix the bug in the login flow",
        "What is ralph-wiggum?",
        "Refactor the hooks system across multiple files",
        "Create a new hook that integrates with beads",
    ]

    for prompt in test_prompts:
        mode, criteria = detect_task_complexity(prompt)
        print(f"Prompt: {prompt[:50]}...")
        print(f"  Mode: {mode or '(skip)'}")
        print(f"  Criteria: {criteria}")
        print()
