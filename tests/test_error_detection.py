"""Tests for error detection in post_tool_use_runner."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from _hooks_state import _detect_error_in_result


class TestStringResults:
    """Tests for string result handling."""

    def test_string_with_error_keyword_detected(self):
        # Arrange
        result = "Error: file not found"

        # Act
        error = _detect_error_in_result(result)

        # Assert
        assert error != ""
        assert "Error" in error

    def test_string_without_error_returns_empty(self):
        # Arrange
        result = "Operation completed successfully"

        # Act
        error = _detect_error_in_result(result)

        # Assert
        assert error == ""

    def test_string_with_custom_keywords(self):
        # Arrange
        result = "Permission denied for /etc/passwd"

        # Act
        error = _detect_error_in_result(result, keywords=("permission denied",))

        # Assert
        assert error != ""


class TestDictResults:
    """Tests for dict result handling."""

    def test_dict_with_error_field(self):
        # Arrange
        result = {"error": "Connection timeout", "output": ""}

        # Act
        error = _detect_error_in_result(result)

        # Assert
        assert "timeout" in error.lower()

    def test_dict_with_error_in_output(self):
        # Arrange
        result = {"output": "FAILED: assertion error in test_main"}

        # Act
        error = _detect_error_in_result(result)

        # Assert
        assert error != ""

    def test_dict_success_returns_empty(self):
        # Arrange
        result = {"output": "All tests passed", "exit_code": 0}

        # Act
        error = _detect_error_in_result(result)

        # Assert
        assert error == ""


class TestEdgeCases:
    """Tests for edge cases."""

    def test_none_result_returns_empty(self):
        # Act
        error = _detect_error_in_result(None)

        # Assert
        assert error == ""

    def test_empty_dict_returns_empty(self):
        # Act
        error = _detect_error_in_result({})

        # Assert
        assert error == ""

    def test_long_error_truncated(self):
        # Arrange
        long_error = "Error: " + "x" * 500

        # Act
        error = _detect_error_in_result(long_error)

        # Assert
        assert len(error) <= 200
