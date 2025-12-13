"""Tests for function definition detection in session_state."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from session_state import extract_function_def_lines


class TestPythonFunctions:
    """Tests for Python function detection."""

    def test_detects_simple_function(self):
        # Arrange
        code = "def hello():\n    pass"

        # Act
        result = extract_function_def_lines(code)

        # Assert
        assert "hello" in result

    def test_detects_function_with_params(self):
        # Arrange
        code = "def process(data: str, count: int = 0) -> str:\n    return data"

        # Act
        result = extract_function_def_lines(code)

        # Assert
        assert "process" in result

    def test_detects_multiple_functions(self):
        # Arrange
        code = """
def first():
    pass

def second(x):
    return x
"""

        # Act
        result = extract_function_def_lines(code)

        # Assert
        assert "first" in result
        assert "second" in result


class TestJavaScriptFunctions:
    """Tests for JavaScript function detection."""

    def test_detects_function_keyword(self):
        # Arrange
        code = "function calculate(x, y) {\n    return x + y;\n}"

        # Act
        result = extract_function_def_lines(code)

        # Assert
        assert "calculate" in result

    def test_detects_async_function(self):
        # Arrange
        code = "async function fetchData(url) {\n    return await fetch(url);\n}"

        # Act
        result = extract_function_def_lines(code)

        # Assert
        assert "fetchData" in result


class TestSignatureChangeDetection:
    """Tests for detecting signature changes."""

    def test_same_signature_matches(self):
        # Arrange
        old_code = "def process(x: int) -> int:\n    return x"
        new_code = "def process(x: int) -> int:\n    return x * 2"

        # Act
        old_funcs = extract_function_def_lines(old_code)
        new_funcs = extract_function_def_lines(new_code)

        # Assert
        assert old_funcs["process"] == new_funcs["process"]

    def test_changed_signature_differs(self):
        # Arrange
        old_code = "def process(x: int) -> int:\n    return x"
        new_code = "def process(x: int, y: int = 0) -> int:\n    return x + y"

        # Act
        old_funcs = extract_function_def_lines(old_code)
        new_funcs = extract_function_def_lines(new_code)

        # Assert
        assert old_funcs["process"] != new_funcs["process"]

    def test_removed_function_not_in_new(self):
        # Arrange
        old_code = "def approve():\n    pass\n\ndef deny():\n    pass"
        new_code = "from module import approve, deny"

        # Act
        old_funcs = extract_function_def_lines(old_code)
        new_funcs = extract_function_def_lines(new_code)

        # Assert
        assert "approve" in old_funcs
        assert "approve" not in new_funcs
