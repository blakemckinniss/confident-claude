#!/usr/bin/env python3
"""
Advisory Personas - BMAD-inspired contextual guidance.

Adds persona-flavored messages to hook advisories. Instead of generic warnings,
messages come from context-appropriate advisors with distinct identities.

Inspired by BMAD-METHOD's agent persona architecture where each agent has:
- role: Primary expertise area
- identity: Background and specializations
- communication_style: How they interact
- principles: Decision-making guidelines

Usage:
    advisor = get_advisor("security")
    message = advisor.advise("Hardcoded credentials detected in config.py")
    # Returns: "🛡️ **Security Advisor**: Hardcoded credentials detected..."

Integration:
    Hooks can use advisors for contextual guidance:
    message = format_advisory("security", "SQL injection risk", severity=75)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class AdvisorPersona:
    """
    Advisory persona with BMAD-style identity.

    Each advisor has a distinct role and communication style
    that shapes how they deliver guidance.
    """

    id: str
    name: str
    emoji: str
    role: str
    specializations: list[str]
    communication_style: str
    principles: list[str]

    def advise(self, message: str, severity: int = 50) -> str:
        """Format an advisory message from this persona."""
        severity_indicator = self._severity_prefix(severity)
        return f"{self.emoji} **{self.name}** {severity_indicator}: {message}"

    def _severity_prefix(self, severity: int) -> str:
        """Get severity indicator based on score."""
        if severity >= 75:
            return "[CRITICAL]"
        elif severity >= 50:
            return "[WARNING]"
        elif severity >= 25:
            return "[NOTICE]"
        return "[INFO]"

    def get_intro(self) -> str:
        """Get a brief introduction for context injection."""
        return f"{self.emoji} {self.name} ({self.role})"


# Advisory personas registry
ADVISORS: dict[str, AdvisorPersona] = {
    "security": AdvisorPersona(
        id="security",
        name="Security Advisor",
        emoji="🛡️",
        role="Security & Vulnerability Expert",
        specializations=[
            "OWASP Top 10",
            "Authentication/Authorization",
            "Input validation",
            "Secrets management",
            "Injection prevention",
        ],
        communication_style="Direct and urgent for high-severity issues, educational for lower severity",
        principles=[
            "Assume all input is malicious until validated",
            "Defense in depth - multiple layers",
            "Principle of least privilege",
            "Fail securely - errors shouldn't expose info",
        ],
    ),
    "architecture": AdvisorPersona(
        id="architecture",
        name="Architecture Advisor",
        emoji="🏗️",
        role="System Design & Patterns Expert",
        specializations=[
            "Design patterns",
            "SOLID principles",
            "Dependency management",
            "Module boundaries",
            "Technical debt assessment",
        ],
        communication_style="Strategic and long-term focused, considers trade-offs",
        principles=[
            "Prefer composition over inheritance",
            "Single responsibility per module",
            "Explicit dependencies over implicit",
            "Design for change, not prediction",
        ],
    ),
    "performance": AdvisorPersona(
        id="performance",
        name="Performance Advisor",
        emoji="⚡",
        role="Performance & Optimization Expert",
        specializations=[
            "Query optimization",
            "Memory management",
            "Caching strategies",
            "Async patterns",
            "Profiling and measurement",
        ],
        communication_style="Data-driven, requires evidence before optimization",
        principles=[
            "Measure before optimizing",
            "Optimize the bottleneck, not the noise",
            "Big-O matters for scale",
            "Premature optimization is the root of evil",
        ],
    ),
    "reliability": AdvisorPersona(
        id="reliability",
        name="Reliability Advisor",
        emoji="🔧",
        role="Error Handling & Resilience Expert",
        specializations=[
            "Error propagation",
            "Graceful degradation",
            "Retry strategies",
            "Circuit breakers",
            "Observability",
        ],
        communication_style="Pragmatic, focused on failure modes and recovery",
        principles=[
            "Crash early, recover gracefully",
            "Every error should be actionable",
            "Silent failures are worse than loud ones",
            "Plan for partial failures",
        ],
    ),
    "testing": AdvisorPersona(
        id="testing",
        name="Testing Advisor",
        emoji="🧪",
        role="Quality Assurance & Testing Expert",
        specializations=[
            "Test coverage strategy",
            "Integration testing",
            "Mocking patterns",
            "Edge case identification",
            "TDD/BDD practices",
        ],
        communication_style="Methodical, emphasizes verification over assumption",
        principles=[
            "Tests are documentation",
            "Test behavior, not implementation",
            "Flaky tests are worse than no tests",
            "Coverage is a metric, not a goal",
        ],
    ),
    "data": AdvisorPersona(
        id="data",
        name="Data Advisor",
        emoji="💾",
        role="Data Integrity & Schema Expert",
        specializations=[
            "Schema design",
            "Migration safety",
            "Data validation",
            "Consistency guarantees",
            "Backup strategies",
        ],
        communication_style="Cautious about destructive operations, emphasizes reversibility",
        principles=[
            "Data is the hardest thing to fix",
            "Always have a rollback plan",
            "Validate at boundaries",
            "Schema changes need migration paths",
        ],
    ),
    "integration": AdvisorPersona(
        id="integration",
        name="Integration Advisor",
        emoji="🔗",
        role="API & Integration Expert",
        specializations=[
            "API design",
            "Contract testing",
            "Versioning strategies",
            "Error handling across boundaries",
            "Rate limiting",
        ],
        communication_style="Focused on boundaries and contracts, considers downstream impact",
        principles=[
            "APIs are forever (or need deprecation paths)",
            "Validate inputs, trust nothing external",
            "Idempotency prevents duplicate operations",
            "Document breaking changes explicitly",
        ],
    ),
    "ux": AdvisorPersona(
        id="ux",
        name="UX Advisor",
        emoji="🎨",
        role="User Experience & Accessibility Expert",
        specializations=[
            "Accessibility (a11y)",
            "Error messaging",
            "Loading states",
            "Form validation UX",
            "Responsive design",
        ],
        communication_style="User-centric, considers edge cases from user perspective",
        principles=[
            "Users don't read error messages - make them scannable",
            "Accessibility benefits everyone",
            "Progressive disclosure reduces overwhelm",
            "Provide feedback for every action",
        ],
    ),
}


def get_advisor(advisor_id: str) -> Optional[AdvisorPersona]:
    """Get an advisor by ID."""
    return ADVISORS.get(advisor_id)


def format_advisory(
    advisor_id: str,
    message: str,
    severity: int = 50,
    context: Optional[str] = None,
) -> str:
    """
    Format an advisory message from a specific advisor.

    Args:
        advisor_id: Advisor to use (security, architecture, etc.)
        message: The advisory message
        severity: Severity score 0-100
        context: Optional additional context

    Returns:
        Formatted advisory string
    """
    advisor = ADVISORS.get(advisor_id)
    if not advisor:
        return f"⚠️ {message}"

    result = advisor.advise(message, severity)
    if context:
        result += f"\n  → {context}"

    return result


def detect_advisor_context(prompt: str, file_path: Optional[str] = None) -> list[str]:
    """
    Detect which advisors are relevant based on prompt and file context.

    Returns list of advisor IDs that should be consulted.
    """
    relevant = []
    prompt_lower = prompt.lower()

    # Security patterns
    if re.search(
        r"\b(auth|security|password|secret|token|credential|inject|xss|csrf)\b",
        prompt_lower,
    ):
        relevant.append("security")

    # Architecture patterns
    if re.search(
        r"\b(refactor|design|pattern|architecture|structure|dependency|coupling)\b",
        prompt_lower,
    ):
        relevant.append("architecture")

    # Performance patterns
    if re.search(
        r"\b(slow|fast|performance|optimi[sz]e|cache|memory|query|n\+1)\b", prompt_lower
    ):
        relevant.append("performance")

    # Reliability patterns
    if re.search(
        r"\b(error|exception|retry|timeout|failover|resilient|handle)\b", prompt_lower
    ):
        relevant.append("reliability")

    # Testing patterns
    if re.search(r"\b(test|coverage|mock|fixture|assert|spec|tdd|bdd)\b", prompt_lower):
        relevant.append("testing")

    # Data patterns
    if re.search(
        r"\b(database|schema|migration|data|backup|rollback|table|column)\b",
        prompt_lower,
    ):
        relevant.append("data")

    # Integration patterns
    if re.search(
        r"\b(api|endpoint|webhook|integration|contract|versioning)\b", prompt_lower
    ):
        relevant.append("integration")

    # UX patterns
    if re.search(
        r"\b(user|ux|ui|accessibility|a11y|form|button|modal|responsive)\b",
        prompt_lower,
    ):
        relevant.append("ux")

    # File-based detection
    if file_path:
        path_lower = file_path.lower()
        if "auth" in path_lower or "security" in path_lower:
            if "security" not in relevant:
                relevant.append("security")
        if "test" in path_lower:
            if "testing" not in relevant:
                relevant.append("testing")
        if "api" in path_lower or "endpoint" in path_lower:
            if "integration" not in relevant:
                relevant.append("integration")

    return relevant[:3]  # Limit to top 3 most relevant


def get_advisory_context_injection(
    advisors: list[str],
    prompt: str,
    severity_override: Optional[int] = None,
) -> Optional[str]:
    """
    Generate context injection from relevant advisors.

    Args:
        advisors: List of advisor IDs to include
        prompt: User's prompt for context
        severity_override: Override severity for all advisors

    Returns:
        Formatted context injection string or None
    """
    if not advisors:
        return None

    lines = ["🎭 **ADVISORY CONTEXT**:"]

    for advisor_id in advisors:
        advisor = ADVISORS.get(advisor_id)
        if advisor:
            lines.append(f"  {advisor.get_intro()}")
            # Add one relevant principle
            if advisor.principles:
                lines.append(f"    → {advisor.principles[0]}")

    return "\n".join(lines) if len(lines) > 1 else None


def get_advisor_principle(advisor_id: str, index: int = 0) -> Optional[str]:
    """Get a specific principle from an advisor."""
    advisor = ADVISORS.get(advisor_id)
    if advisor and advisor.principles:
        idx = index % len(advisor.principles)
        return advisor.principles[idx]
    return None


def format_multi_advisor_response(
    findings: dict[str, list[str]],
) -> str:
    """
    Format findings from multiple advisors into a cohesive response.

    Args:
        findings: Dict mapping advisor_id to list of findings

    Returns:
        Formatted multi-advisor response
    """
    lines = []

    for advisor_id, advisor_findings in findings.items():
        advisor = ADVISORS.get(advisor_id)
        if not advisor or not advisor_findings:
            continue

        lines.append(f"\n{advisor.emoji} **{advisor.name}**:")
        for finding in advisor_findings[:3]:  # Limit findings per advisor
            lines.append(f"  • {finding}")

    return "\n".join(lines) if lines else ""
