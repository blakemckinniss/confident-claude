"""Safety and redaction for mastermind context.

Redacts secrets and sensitive data before sending to external services.
Preserves data "shape" for debugging (e.g., "REDACTED_API_KEY_32_CHARS").
"""

from __future__ import annotations

import re
from typing import Callable

from .config import get_config

# Patterns for sensitive data detection
PATTERNS: list[tuple[str, re.Pattern[str], Callable[[re.Match[str]], str]]] = [
    # API keys (various formats)
    (
        "api_key",
        re.compile(
            r'(?:api[_-]?key|apikey|api_secret|secret_key)\s*[=:]\s*["\']?([a-zA-Z0-9_\-]{20,})["\']?',
            re.IGNORECASE,
        ),
        lambda m: f"REDACTED_API_KEY_{len(m.group(1))}chars",
    ),
    # Bearer tokens
    (
        "bearer_token",
        re.compile(r"Bearer\s+([a-zA-Z0-9_\-\.]+)", re.IGNORECASE),
        lambda m: f"Bearer REDACTED_TOKEN_{len(m.group(1))}chars",
    ),
    # AWS keys
    (
        "aws_key",
        re.compile(r"(AKIA[0-9A-Z]{16})"),
        lambda m: "REDACTED_AWS_KEY",
    ),
    # Private keys
    (
        "private_key",
        re.compile(
            r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"
        ),
        lambda m: "-----BEGIN PRIVATE KEY-----\nREDACTED_KEY_CONTENT\n-----END PRIVATE KEY-----",
    ),
    # Generic secrets in env format
    (
        "env_secret",
        re.compile(
            r"^([A-Z][A-Z0-9_]*(?:SECRET|PASSWORD|TOKEN|KEY|CREDENTIAL|AUTH)[A-Z0-9_]*)\s*=\s*(.+)$",
            re.MULTILINE | re.IGNORECASE,
        ),
        lambda m: f"{m.group(1)}=REDACTED_{len(m.group(2))}chars",
    ),
    # Database URLs with credentials
    (
        "database_url",
        re.compile(
            r"((?:postgres|mysql|mongodb|redis)(?:ql)?://)[^:]+:([^@]+)@",
            re.IGNORECASE,
        ),
        lambda m: f"{m.group(1)}USER:REDACTED_PASSWORD@",
    ),
    # GitHub tokens
    (
        "github_token",
        re.compile(r"(ghp_[a-zA-Z0-9]{36}|github_pat_[a-zA-Z0-9_]{22,})"),
        lambda m: f"REDACTED_GITHUB_TOKEN_{len(m.group(1))}chars",
    ),
    # OpenAI/Anthropic keys
    (
        "llm_key",
        re.compile(r"(sk-[a-zA-Z0-9]{20,}|sk-ant-[a-zA-Z0-9\-]{20,})"),
        lambda m: f"REDACTED_LLM_KEY_{len(m.group(1))}chars",
    ),
    # Groq keys
    (
        "groq_key",
        re.compile(r"(gsk_[a-zA-Z0-9]{20,})"),
        lambda m: f"REDACTED_GROQ_KEY_{len(m.group(1))}chars",
    ),
    # .env file paths (just warn, don't redact path)
    (
        "env_file_mention",
        re.compile(r"\.env(?:\.local|\.production|\.development)?"),
        lambda m: m.group(0),  # Keep the reference, redact content if included
    ),
]


def redact_text(text: str) -> tuple[str, list[str]]:
    """Redact sensitive data from text.

    Args:
        text: Input text that may contain secrets

    Returns:
        (redacted_text, list of redaction types applied)
    """
    config = get_config()

    if not config.safety.redact_secrets:
        return text, []

    redacted = text
    applied: list[str] = []

    for name, pattern, replacer in PATTERNS:
        # Skip certain pattern types based on config
        if name == "env_secret" and not config.safety.redact_env_vars:
            continue
        if (
            name
            in (
                "api_key",
                "bearer_token",
                "llm_key",
                "groq_key",
                "github_token",
                "aws_key",
            )
            and not config.safety.redact_api_keys
        ):
            continue

        matches = pattern.findall(text)
        if matches:
            redacted = pattern.sub(replacer, redacted)
            if name not in applied:
                applied.append(name)

    return redacted, applied


def redact_dict(data: dict, depth: int = 0, max_depth: int = 10) -> dict:
    """Recursively redact sensitive data in a dictionary.

    Args:
        data: Dictionary that may contain secrets
        depth: Current recursion depth
        max_depth: Maximum recursion depth

    Returns:
        Dictionary with sensitive values redacted
    """
    if depth > max_depth:
        return data

    result = {}
    for key, value in data.items():
        key_lower = key.lower()

        # Check if key name suggests sensitive data
        if any(
            s in key_lower
            for s in (
                "secret",
                "password",
                "token",
                "key",
                "credential",
                "auth",
                "api_key",
            )
        ):
            if isinstance(value, str):
                result[key] = f"REDACTED_{len(value)}chars"
            else:
                result[key] = "REDACTED"
        elif isinstance(value, str):
            result[key], _ = redact_text(value)
        elif isinstance(value, dict):
            result[key] = redact_dict(value, depth + 1, max_depth)
        elif isinstance(value, list):
            result[key] = [
                redact_dict(v, depth + 1, max_depth)
                if isinstance(v, dict)
                else (redact_text(v)[0] if isinstance(v, str) else v)
                for v in value
            ]
        else:
            result[key] = value

    return result


def is_safe_to_send(text: str) -> tuple[bool, list[str]]:
    """Check if text is safe to send externally.

    Returns:
        (is_safe, list of detected sensitive patterns)
    """
    _, detections = redact_text(text)
    return len(detections) == 0, detections
