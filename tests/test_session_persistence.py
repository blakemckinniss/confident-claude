#!/usr/bin/env python3
"""Tests for _session_persistence module.

Tests cover:
- Session ID validation logic
- State loading with caching
- State saving with atomic writes
- Lock acquisition and release
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add lib to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))


class TestValidateSessionId:
    """Tests for _validate_session_id function."""

    def test_matching_session_ids_returns_true(self):
        """Matching session IDs should return True."""
        from _session_persistence import _validate_session_id

        data = {"session_id": "abc123"}
        result = _validate_session_id(data, "abc123", "/fake/path")
        assert result is True

    def test_mismatched_session_ids_returns_false(self):
        """Mismatched session IDs should return False."""
        from _session_persistence import _validate_session_id

        data = {"session_id": "abc123"}
        result = _validate_session_id(data, "xyz789", "/fake/path")
        assert result is False

    def test_empty_expected_id_returns_true(self):
        """Empty expected session ID should return True (no validation)."""
        from _session_persistence import _validate_session_id

        data = {"session_id": "abc123"}
        result = _validate_session_id(data, "", "/fake/path")
        assert result is True

    def test_empty_loaded_id_returns_true(self):
        """Empty loaded session ID should return True (fresh state)."""
        from _session_persistence import _validate_session_id

        data = {"session_id": ""}
        result = _validate_session_id(data, "abc123", "/fake/path")
        assert result is True

    def test_missing_session_id_key_returns_true(self):
        """Missing session_id key should return True (fresh state)."""
        from _session_persistence import _validate_session_id

        data = {}
        result = _validate_session_id(data, "abc123", "/fake/path")
        assert result is True

    def test_truncates_to_16_chars(self):
        """Session IDs should be truncated to 16 chars for comparison."""
        from _session_persistence import _validate_session_id

        # These match on first 16 chars
        data = {"session_id": "1234567890123456_extra"}
        result = _validate_session_id(data, "1234567890123456_different", "/fake/path")
        assert result is True

    def test_strips_whitespace(self):
        """Session IDs should have whitespace stripped."""
        from _session_persistence import _validate_session_id

        data = {"session_id": "  abc123  "}
        result = _validate_session_id(data, "abc123", "/fake/path")
        assert result is True


class TestEnsureMemoryDir:
    """Tests for _ensure_memory_dir function."""

    def test_creates_directory_if_missing(self):
        """Should create memory directory if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_state_file = Path(tmpdir) / "memory" / "state.json"

            with patch(
                "_session_persistence.get_project_state_file",
                return_value=fake_state_file,
            ):
                from _session_persistence import _ensure_memory_dir

                _ensure_memory_dir()
                assert fake_state_file.parent.exists()

    def test_succeeds_if_directory_exists(self):
        """Should succeed silently if directory already exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_state_file = Path(tmpdir) / "memory" / "state.json"
            fake_state_file.parent.mkdir(parents=True, exist_ok=True)

            with patch(
                "_session_persistence.get_project_state_file",
                return_value=fake_state_file,
            ):
                from _session_persistence import _ensure_memory_dir

                _ensure_memory_dir()  # Should not raise
                assert fake_state_file.parent.exists()


class TestLocking:
    """Tests for lock acquisition and release."""

    def test_acquire_and_release_exclusive_lock(self):
        """Should acquire and release exclusive lock."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_state_file = Path(tmpdir) / "memory" / "state.json"
            fake_lock_file = Path(tmpdir) / "memory" / "state.lock"

            with (
                patch(
                    "_session_persistence.get_project_state_file",
                    return_value=fake_state_file,
                ),
                patch(
                    "_session_persistence.get_project_lock_file",
                    return_value=fake_lock_file,
                ),
            ):
                from _session_persistence import (
                    _acquire_state_lock,
                    _release_state_lock,
                )

                lock_fd = _acquire_state_lock(shared=False)
                assert isinstance(lock_fd, int)
                assert lock_fd >= 0

                _release_state_lock(lock_fd)
                # Lock file should still exist (we don't delete it)
                assert fake_lock_file.exists()

    def test_acquire_shared_lock(self):
        """Should acquire shared lock when shared=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_state_file = Path(tmpdir) / "memory" / "state.json"
            fake_lock_file = Path(tmpdir) / "memory" / "state.lock"

            with (
                patch(
                    "_session_persistence.get_project_state_file",
                    return_value=fake_state_file,
                ),
                patch(
                    "_session_persistence.get_project_lock_file",
                    return_value=fake_lock_file,
                ),
            ):
                from _session_persistence import (
                    _acquire_state_lock,
                    _release_state_lock,
                )

                lock_fd = _acquire_state_lock(shared=True)
                assert isinstance(lock_fd, int)
                _release_state_lock(lock_fd)


class TestSaveStateUnlocked:
    """Tests for _save_state_unlocked function."""

    def test_saves_state_to_file(self):
        """Should save state as JSON to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_state_file = Path(tmpdir) / "state.json"

            # Create a mock SessionState
            mock_state = MagicMock()
            mock_state.files_read = ["a.py", "b.py"]
            mock_state.files_edited = ["c.py"]
            mock_state.commands_succeeded = []
            mock_state.commands_failed = []
            mock_state.errors_recent = []
            mock_state.domain_signals = []
            mock_state.gaps_detected = []
            mock_state.gaps_surfaced = []
            mock_state.last_5_tools = []
            mock_state.evidence_ledger = []
            mock_state.last_activity_time = 0

            with (
                patch(
                    "_session_persistence.get_project_state_file",
                    return_value=fake_state_file,
                ),
                patch(
                    "_session_persistence.asdict",
                    return_value={
                        "session_id": "test123",
                        "files_read": ["a.py", "b.py"],
                    },
                ),
            ):
                from _session_persistence import _save_state_unlocked

                _save_state_unlocked(mock_state)

                assert fake_state_file.exists()
                data = json.loads(fake_state_file.read_text())
                assert data["session_id"] == "test123"

    def test_trims_lists_to_prevent_growth(self):
        """Should trim lists to configured limits."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_state_file = Path(tmpdir) / "state.json"

            mock_state = MagicMock()
            # Create list longer than trim limit (50)
            mock_state.files_read = [f"file{i}.py" for i in range(100)]
            mock_state.files_edited = [f"edit{i}.py" for i in range(100)]
            mock_state.commands_succeeded = [f"cmd{i}" for i in range(50)]
            mock_state.commands_failed = [f"fail{i}" for i in range(50)]
            mock_state.errors_recent = [f"err{i}" for i in range(20)]
            mock_state.domain_signals = [f"sig{i}" for i in range(30)]
            mock_state.gaps_detected = [f"gap{i}" for i in range(20)]
            mock_state.gaps_surfaced = [f"surf{i}" for i in range(20)]
            mock_state.last_5_tools = [f"tool{i}" for i in range(10)]
            mock_state.evidence_ledger = [f"ev{i}" for i in range(30)]
            mock_state.last_activity_time = 0

            with (
                patch(
                    "_session_persistence.get_project_state_file",
                    return_value=fake_state_file,
                ),
                patch("_session_persistence.asdict", return_value={"test": "data"}),
            ):
                from _session_persistence import _save_state_unlocked

                _save_state_unlocked(mock_state)

                # Verify lists were trimmed
                assert len(mock_state.files_read) == 50
                assert len(mock_state.files_edited) == 50
                assert len(mock_state.commands_succeeded) == 20
                assert len(mock_state.last_5_tools) == 5


class TestUpdateState:
    """Tests for update_state function."""

    def test_calls_modifier_function(self):
        """Should call the modifier function with loaded state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_state_file = Path(tmpdir) / "state.json"
            fake_lock_file = Path(tmpdir) / "state.lock"

            # Pre-create state file
            fake_state_file.write_text(
                json.dumps(
                    {
                        "session_id": "test123",
                        "started_at": 0,
                        "turn_count": 5,
                    }
                )
            )

            modifier_called = []

            def modifier(state):
                modifier_called.append(state)
                state.turn_count = 10

            with (
                patch(
                    "_session_persistence.get_project_state_file",
                    return_value=fake_state_file,
                ),
                patch(
                    "_session_persistence.get_project_lock_file",
                    return_value=fake_lock_file,
                ),
                patch("_session_context._discover_ops_scripts", return_value=[]),
                patch("_session_persistence._save_state_unlocked"),
            ):
                from _session_persistence import update_state

                result = update_state(modifier)

                assert len(modifier_called) == 1
                assert result.turn_count == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
