"""Tests for inline server background detection in pre_tool_use_runner."""

import re
import sys
from pathlib import Path

# Add hooks to path
sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))


def has_backgrounded_server(cmd: str, server_pattern: str) -> bool:
    """
    Check if command has a server pattern followed by backgrounding &.

    Extracted from check_inline_server_background hook for testing.
    Must distinguish backgrounding & from redirect syntax (2>&1, >&, &>, &&).
    """
    match = re.search(server_pattern, cmd, re.IGNORECASE)
    if not match:
        return False
    after_match = cmd[match.end():]
    # Look for standalone & (backgrounding), not redirect syntax
    return bool(re.search(r"(?<![>&])&(?![>&0-9])", after_match))


# Common server pattern for npm
NPM_PATTERN = r"\bnpm\s+(run\s+)?(dev|start|serve)\b"


class TestBackgroundingDetection:
    """Tests for distinguishing backgrounding & from redirect syntax."""

    def test_redirect_2_stdout_should_pass(self):
        # Arrange
        cmd = "npm run dev 2>&1 | head -20"

        # Act
        result = has_backgrounded_server(cmd, NPM_PATTERN)

        # Assert
        assert result is False

    def test_standalone_ampersand_should_detect(self):
        # Arrange
        cmd = "npm run dev &"

        # Act
        result = has_backgrounded_server(cmd, NPM_PATTERN)

        # Assert
        assert result is True

    def test_background_with_curl_should_detect(self):
        # Arrange
        cmd = "npm run dev & curl localhost:3000"

        # Act
        result = has_backgrounded_server(cmd, NPM_PATTERN)

        # Assert
        assert result is True

    def test_redirect_to_file_should_pass(self):
        # Arrange
        cmd = "npm run dev > log.txt 2>&1"

        # Act
        result = has_backgrounded_server(cmd, NPM_PATTERN)

        # Assert
        assert result is False

    def test_double_ampersand_chaining_should_pass(self):
        # Arrange
        cmd = "npm run dev && echo done"

        # Act
        result = has_backgrounded_server(cmd, NPM_PATTERN)

        # Assert
        assert result is False

    def test_ampersand_redirect_should_pass(self):
        # Arrange
        cmd = "npm run dev &> /dev/null"

        # Act
        result = has_backgrounded_server(cmd, NPM_PATTERN)

        # Assert
        assert result is False

    def test_pkill_then_dev_with_redirect_should_pass(self):
        # Arrange - the original failing case
        cmd = "pkill -f npm; npm run dev 2>&1 | head -20"

        # Act
        result = has_backgrounded_server(cmd, NPM_PATTERN)

        # Assert
        assert result is False

    def test_background_with_sleep_should_detect(self):
        # Arrange
        cmd = "npm run dev & sleep 5"

        # Act
        result = has_backgrounded_server(cmd, NPM_PATTERN)

        # Assert
        assert result is True

    def test_timeout_with_redirect_should_pass(self):
        # Arrange - real diagnostic pattern
        cmd = "timeout 8 npm run dev 2>&1 | head -20"

        # Act
        result = has_backgrounded_server(cmd, NPM_PATTERN)

        # Assert
        assert result is False

    def test_no_server_pattern_should_pass(self):
        # Arrange
        cmd = "echo hello & echo world"

        # Act
        result = has_backgrounded_server(cmd, NPM_PATTERN)

        # Assert
        assert result is False
