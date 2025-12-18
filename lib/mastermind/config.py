"""Mastermind configuration management.

Loads config from ~/.claude/config/mastermind.json with sensible defaults.
Provides typed access to all configuration values.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONFIG_PATH = Path.home() / ".claude" / "config" / "mastermind.json"

# =============================================================================
# PAL MANDATE LOCK - Single source of truth for lock file path and TTL
# Used by: hook_integration.py, pre_tool_use_runner.py, _hooks_state.py
# =============================================================================
PAL_MANDATE_LOCK_PATH = Path.home() / ".claude" / "tmp" / "pal_mandate.lock"
PAL_MANDATE_TTL_MINUTES = 30  # Auto-expire stale locks

# Singleton cache
_config_cache: MastermindConfig | None = None


@dataclass
class RouterConfig:
    """Session-start router configuration."""

    enabled: bool = False
    force_complex_when_uncertain: bool = True
    uncertainty_threshold: float = 0.6
    risk_lexicon_override: bool = True


@dataclass
class PlannerConfig:
    """Planner configuration. Model defaults to 'auto' for PAL auto-selection."""

    enabled: bool = False
    model: str = "auto"  # PAL auto-selects; can override with specific model
    mini_mode_threshold: str = "trivial"
    max_blueprint_tokens: int = 4000


@dataclass
class DriftConfig:
    """Mid-session drift detection configuration."""

    enabled: bool = False
    file_count_trigger: int = 5
    test_failure_trigger: int = 2
    approach_change_detection: bool = True
    cooldown_turns: int = 8
    max_escalations_per_session: int = 3


@dataclass
class ContextPackerConfig:
    """Context packing token budgets."""

    router_token_budget: int = 1200
    planner_token_budget: int = 4000
    include_repo_structure: bool = True
    include_git_diff: bool = True
    include_beads: bool = True
    include_test_status: bool = True
    include_serena_context: bool = True
    include_memory_hints: bool = True  # Path B: lightweight signals for router
    include_memory_content: bool = True  # Path A: full content for planner
    memory_token_budget: int = 800  # Max tokens for memory content


@dataclass
class TelemetryConfig:
    """Observability settings."""

    enabled: bool = True
    log_router_decisions: bool = True
    log_planner_calls: bool = True
    log_escalations: bool = True
    jsonl_per_session: bool = True


@dataclass
class SafetyConfig:
    """Secret redaction settings."""

    redact_secrets: bool = True
    redact_env_vars: bool = True
    redact_api_keys: bool = True
    preserve_shape: bool = True


@dataclass
class MastermindConfig:
    """Complete mastermind configuration."""

    router: RouterConfig = field(default_factory=RouterConfig)
    planner: PlannerConfig = field(default_factory=PlannerConfig)
    drift: DriftConfig = field(default_factory=DriftConfig)
    context_packer: ContextPackerConfig = field(default_factory=ContextPackerConfig)
    telemetry: TelemetryConfig = field(default_factory=TelemetryConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    rollout_phase: int = 0

    @property
    def is_enabled(self) -> bool:
        """Check if mastermind is enabled (any component active)."""
        return self.router.enabled or self.planner.enabled or self.drift.enabled

    @property
    def phase_name(self) -> str:
        """Human-readable rollout phase name."""
        phases = {
            0: "dark_launch",
            1: "explicit_override_only",
            2: "auto_planner_complex",
            3: "drift_escalation",
            4: "threshold_tuning",
        }
        return phases.get(self.rollout_phase, "unknown")


def _load_nested(data: dict[str, Any], key: str, cls: type) -> Any:
    """Load nested config section with defaults."""
    section = data.get(key, {})
    if isinstance(section, dict):
        # Filter to only valid fields for the dataclass
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in section.items() if k in valid_fields}
        return cls(**filtered)
    return cls()


def load_config(
    path: Path | None = None, force_reload: bool = False
) -> MastermindConfig:
    """Load mastermind configuration from JSON file.

    Args:
        path: Override config path (default: ~/.claude/config/mastermind.json)
        force_reload: Bypass cache and reload from disk

    Returns:
        MastermindConfig instance with all settings
    """
    global _config_cache

    if _config_cache is not None and not force_reload:
        return _config_cache

    config_path = path or CONFIG_PATH

    if not config_path.exists():
        _config_cache = MastermindConfig()
        return _config_cache

    try:
        with open(config_path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        _config_cache = MastermindConfig()
        return _config_cache

    config = MastermindConfig(
        router=_load_nested(data, "session_start_router", RouterConfig),
        planner=_load_nested(data, "planner", PlannerConfig),
        drift=_load_nested(data, "drift_detection", DriftConfig),
        context_packer=_load_nested(data, "context_packer", ContextPackerConfig),
        telemetry=_load_nested(data, "telemetry", TelemetryConfig),
        safety=_load_nested(data, "safety", SafetyConfig),
        rollout_phase=data.get("rollout_phase", 0),
    )

    _config_cache = config
    return config


def get_config() -> MastermindConfig:
    """Get cached config (loads on first call)."""
    return load_config()


def clear_cache() -> None:
    """Clear config cache (for testing)."""
    global _config_cache
    _config_cache = None


def save_config(config: MastermindConfig, path: Path | None = None) -> Path:
    """Save mastermind configuration to JSON file.

    Args:
        config: Configuration to save
        path: Override config path (default: ~/.claude/config/mastermind.json)

    Returns:
        Path where config was saved
    """
    global _config_cache
    config_path = path or CONFIG_PATH
    config_path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "session_start_router": {
            "enabled": config.router.enabled,
            "force_complex_when_uncertain": config.router.force_complex_when_uncertain,
            "uncertainty_threshold": config.router.uncertainty_threshold,
            "risk_lexicon_override": config.router.risk_lexicon_override,
        },
        "planner": {
            "enabled": config.planner.enabled,
            "model": config.planner.model,
            "mini_mode_threshold": config.planner.mini_mode_threshold,
            "max_blueprint_tokens": config.planner.max_blueprint_tokens,
        },
        "drift_detection": {
            "enabled": config.drift.enabled,
            "file_count_trigger": config.drift.file_count_trigger,
            "test_failure_trigger": config.drift.test_failure_trigger,
            "approach_change_detection": config.drift.approach_change_detection,
            "cooldown_turns": config.drift.cooldown_turns,
            "max_escalations_per_session": config.drift.max_escalations_per_session,
        },
        "context_packer": {
            "router_token_budget": config.context_packer.router_token_budget,
            "planner_token_budget": config.context_packer.planner_token_budget,
            "include_repo_structure": config.context_packer.include_repo_structure,
            "include_git_diff": config.context_packer.include_git_diff,
            "include_beads": config.context_packer.include_beads,
            "include_test_status": config.context_packer.include_test_status,
            "include_serena_context": config.context_packer.include_serena_context,
            "include_memory_hints": config.context_packer.include_memory_hints,
            "include_memory_content": config.context_packer.include_memory_content,
            "memory_token_budget": config.context_packer.memory_token_budget,
        },
        "telemetry": {
            "enabled": config.telemetry.enabled,
            "log_router_decisions": config.telemetry.log_router_decisions,
            "log_planner_calls": config.telemetry.log_planner_calls,
            "log_escalations": config.telemetry.log_escalations,
            "jsonl_per_session": config.telemetry.jsonl_per_session,
        },
        "safety": {
            "redact_secrets": config.safety.redact_secrets,
            "redact_env_vars": config.safety.redact_env_vars,
            "redact_api_keys": config.safety.redact_api_keys,
            "preserve_shape": config.safety.preserve_shape,
        },
        "rollout_phase": config.rollout_phase,
    }

    with open(config_path, "w") as f:
        json.dump(data, f, indent=2)

    _config_cache = config
    return config_path


def update_drift_thresholds(
    file_count: int | None = None,
    test_failures: int | None = None,
    cooldown: int | None = None,
    max_escalations: int | None = None,
) -> MastermindConfig:
    """Update drift detection thresholds at runtime.

    Args:
        file_count: New file count trigger (default: unchanged)
        test_failures: New test failure trigger (default: unchanged)
        cooldown: New cooldown turns (default: unchanged)
        max_escalations: New max escalations per session (default: unchanged)

    Returns:
        Updated config
    """
    config = load_config(force_reload=True)

    if file_count is not None:
        config.drift.file_count_trigger = file_count
    if test_failures is not None:
        config.drift.test_failure_trigger = test_failures
    if cooldown is not None:
        config.drift.cooldown_turns = cooldown
    if max_escalations is not None:
        config.drift.max_escalations_per_session = max_escalations

    save_config(config)
    return config
