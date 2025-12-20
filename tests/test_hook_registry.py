#!/usr/bin/env python3
"""Tests for hook_registry module.

Tests cover:
- Hook scanning and discovery
- Metadata extraction
- Event type inference
- Hook validation
- Health summary generation
"""

import json
import sys
import tempfile
from pathlib import Path

import pytest

# Add lib to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from hook_registry import HookRegistry


class TestHookScanning:
    """Tests for hook scanning functionality."""

    def test_scan_empty_directory(self):
        """Should return empty dict when hooks directory is empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            hooks_dir = project_root / ".claude" / "hooks"
            hooks_dir.mkdir(parents=True)

            registry = HookRegistry(project_root)
            hooks = registry.scan_hooks()

            assert hooks == {}

    def test_scan_nonexistent_directory(self):
        """Should return empty dict when hooks directory doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            registry = HookRegistry(project_root)
            hooks = registry.scan_hooks()

            assert hooks == {}

    def test_scan_finds_python_hooks(self):
        """Should find .py files in hooks directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            hooks_dir = project_root / ".claude" / "hooks"
            hooks_dir.mkdir(parents=True)

            # Create a simple hook file
            hook_file = hooks_dir / "test_hook.py"
            hook_file.write_text('"""Test hook."""\ndef main():\n    return {}\n')

            registry = HookRegistry(project_root)
            hooks = registry.scan_hooks()

            assert "test_hook.py" in hooks
            assert hooks["test_hook.py"]["filename"] == "test_hook.py"

    def test_scan_skips_underscore_files(self):
        """Should skip files starting with underscore."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            hooks_dir = project_root / ".claude" / "hooks"
            hooks_dir.mkdir(parents=True)

            # Create files with underscores
            (hooks_dir / "_private.py").write_text("# private")
            (hooks_dir / "__init__.py").write_text("")
            (hooks_dir / "public.py").write_text("def main():\n    return {}\n")

            registry = HookRegistry(project_root)
            hooks = registry.scan_hooks()

            assert "_private.py" not in hooks
            assert "__init__.py" not in hooks
            assert "public.py" in hooks


class TestMetadataExtraction:
    """Tests for hook metadata extraction."""

    def test_extracts_docstring(self):
        """Should extract first line of module docstring."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            hooks_dir = project_root / ".claude" / "hooks"
            hooks_dir.mkdir(parents=True)

            hook_file = hooks_dir / "documented.py"
            hook_file.write_text(
                '"""This is the description.\n\nMore details here."""\n'
                "def main():\n    return {}\n"
            )

            registry = HookRegistry(project_root)
            hooks = registry.scan_hooks()

            assert hooks["documented.py"]["description"] == "This is the description."

    def test_handles_missing_docstring(self):
        """Should handle files without docstrings gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            hooks_dir = project_root / ".claude" / "hooks"
            hooks_dir.mkdir(parents=True)

            hook_file = hooks_dir / "nodoc.py"
            hook_file.write_text("def main():\n    return {}\n")

            registry = HookRegistry(project_root)
            hooks = registry.scan_hooks()

            assert "description" not in hooks["nodoc.py"]


class TestEventTypeInference:
    """Tests for event type inference from hook content."""

    def test_infers_from_content(self):
        """Should infer event type from hook content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            hooks_dir = project_root / ".claude" / "hooks"
            hooks_dir.mkdir(parents=True)

            hook_file = hooks_dir / "post_tool.py"
            hook_file.write_text(
                '"""PostToolUse handler."""\n'
                "def main():\n    # Handle PostToolUse\n    return {}\n"
            )

            registry = HookRegistry(project_root)
            hooks = registry.scan_hooks()

            assert hooks["post_tool.py"]["event_type"] == "PostToolUse"

    def test_infers_from_settings(self):
        """Should infer event type from settings.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            hooks_dir = project_root / ".claude" / "hooks"
            hooks_dir.mkdir(parents=True)
            claude_dir = project_root / ".claude"

            hook_file = hooks_dir / "my_hook.py"
            hook_file.write_text("def main():\n    return {}\n")

            settings_file = claude_dir / "settings.json"
            settings_file.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [{"file": "my_hook.py"}],
                        }
                    }
                )
            )

            registry = HookRegistry(project_root)
            hooks = registry.scan_hooks()

            assert hooks["my_hook.py"]["event_type"] == "PreToolUse"


class TestHookValidation:
    """Tests for hook health validation."""

    def test_validates_syntax(self):
        """Should detect valid Python syntax."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            hooks_dir = project_root / ".claude" / "hooks"
            hooks_dir.mkdir(parents=True)

            hook_file = hooks_dir / "valid.py"
            hook_file.write_text("def main():\n    return {}\n")

            registry = HookRegistry(project_root)
            health = registry.validate_hook(hook_file)

            assert health["syntax_valid"] is True
            assert health["imports_valid"] is True

    def test_detects_syntax_errors(self):
        """Should detect invalid Python syntax."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            hooks_dir = project_root / ".claude" / "hooks"
            hooks_dir.mkdir(parents=True)

            hook_file = hooks_dir / "invalid.py"
            hook_file.write_text("def main(\n    return {}\n")  # Missing closing paren

            registry = HookRegistry(project_root)
            health = registry.validate_hook(hook_file)

            assert health["syntax_valid"] is False
            assert len(health["errors"]) > 0

    def test_detects_main_function(self):
        """Should detect presence of main function."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            hooks_dir = project_root / ".claude" / "hooks"
            hooks_dir.mkdir(parents=True)

            hook_with_main = hooks_dir / "has_main.py"
            hook_with_main.write_text("def main():\n    return {}\n")

            hook_without_main = hooks_dir / "no_main.py"
            hook_without_main.write_text("def other():\n    return {}\n")

            registry = HookRegistry(project_root)

            assert registry.validate_hook(hook_with_main)["has_main"] is True
            assert registry.validate_hook(hook_without_main)["has_main"] is False

    def test_caches_validation_results(self):
        """Should cache validation results by file mtime."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            hooks_dir = project_root / ".claude" / "hooks"
            hooks_dir.mkdir(parents=True)

            hook_file = hooks_dir / "cached.py"
            hook_file.write_text("def main():\n    return {}\n")

            registry = HookRegistry(project_root)

            # First validation
            health1 = registry.validate_hook(hook_file)
            # Second validation (should hit cache)
            health2 = registry.validate_hook(hook_file)

            assert health1 == health2


class TestCategorization:
    """Tests for hook categorization by event type."""

    def test_categorizes_by_event(self):
        """Should group hooks by event type."""
        hooks = {
            "hook1.py": {"event_type": "PreToolUse"},
            "hook2.py": {"event_type": "PostToolUse"},
            "hook3.py": {"event_type": "PreToolUse"},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            registry = HookRegistry(Path(tmpdir))
            categorized = registry.categorize_by_event(hooks)

            assert "PreToolUse" in categorized
            assert "PostToolUse" in categorized
            assert len(categorized["PreToolUse"]) == 2
            assert len(categorized["PostToolUse"]) == 1


class TestHealthSummary:
    """Tests for health summary generation."""

    def test_counts_passing_hooks(self):
        """Should count hooks with all health checks passing."""
        hooks = {
            "healthy.py": {
                "health": {
                    "syntax_valid": True,
                    "imports_valid": True,
                    "has_main": True,
                    "has_proper_return": True,
                    "errors": [],
                }
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            registry = HookRegistry(Path(tmpdir))
            summary = registry.get_health_summary(hooks)

            assert summary["passing"] == 1
            assert summary["warnings"] == 0
            assert summary["failing"] == 0

    def test_counts_warning_hooks(self):
        """Should count hooks with structure warnings."""
        hooks = {
            "warning.py": {
                "health": {
                    "syntax_valid": True,
                    "imports_valid": True,
                    "has_main": False,  # Warning: missing main
                    "has_proper_return": True,
                    "errors": [],
                }
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            registry = HookRegistry(Path(tmpdir))
            summary = registry.get_health_summary(hooks)

            assert summary["passing"] == 0
            assert summary["warnings"] == 1
            assert summary["failing"] == 0

    def test_counts_failing_hooks(self):
        """Should count hooks with syntax/import errors."""
        hooks = {
            "failing.py": {
                "health": {
                    "syntax_valid": False,
                    "imports_valid": False,
                    "has_main": False,
                    "has_proper_return": False,
                    "errors": ["Syntax error: invalid syntax"],
                }
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            registry = HookRegistry(Path(tmpdir))
            summary = registry.get_health_summary(hooks)

            assert summary["passing"] == 0
            assert summary["warnings"] == 0
            assert summary["failing"] == 1
            assert len(summary["failed_hooks"]) == 1


class TestRegistryPersistence:
    """Tests for registry save/load functionality."""

    def test_saves_registry_to_disk(self):
        """Should save registry JSON to disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            memory_dir = project_root / ".claude" / "memory"
            memory_dir.mkdir(parents=True)

            registry = HookRegistry(project_root)
            hooks = {"test.py": {"filename": "test.py", "event_type": "PreToolUse"}}

            success = registry.save_registry(hooks)

            assert success is True
            assert registry.registry_path.exists()

            saved = json.loads(registry.registry_path.read_text())
            assert saved["total_hooks"] == 1
            assert "test.py" in saved["hooks"]

    def test_loads_registry_from_disk(self):
        """Should load registry JSON from disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            memory_dir = project_root / ".claude" / "memory"
            memory_dir.mkdir(parents=True)

            registry = HookRegistry(project_root)
            registry.registry_path.write_text(
                json.dumps({"total_hooks": 5, "hooks": {"a.py": {}}})
            )

            loaded = registry.load_registry()

            assert loaded is not None
            assert loaded["total_hooks"] == 5

    def test_returns_none_for_missing_registry(self):
        """Should return None when registry file doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = HookRegistry(Path(tmpdir))
            loaded = registry.load_registry()

            assert loaded is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
