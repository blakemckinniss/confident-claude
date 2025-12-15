---
name: testing
description: |
  Run tests, write tests, pytest, jest, test coverage, TDD, test-driven,
  unit tests, integration tests, test failures, test debugging, assertions,
  mocking, fixtures, test patterns, test automation.

  Trigger phrases: run tests, write tests, test this, pytest, jest,
  test coverage, TDD, test-driven, unit test, integration test,
  test failing, fix test, mock, fixture, assertion, expect,
  test pattern, test automation, test suite, test runner,
  coverage report, untested code, add tests, test cases.
---

# Testing

Tools for running and writing tests.

## Running Tests

### Python (pytest)
```bash
# Run all tests
pytest

# Specific file/directory
pytest tests/test_module.py
pytest tests/

# Verbose with output
pytest -v --tb=short

# Stop on first failure
pytest -x

# Run matching pattern
pytest -k "test_name_pattern"

# With coverage
pytest --cov=src --cov-report=term-missing
```

### JavaScript (Jest/Vitest)
```bash
# Run all
npm test

# Watch mode
npm test -- --watch

# Specific file
npm test -- path/to/test.ts

# Coverage
npm test -- --coverage
```

## Test Patterns

### Arrange-Act-Assert
```python
def test_example():
    # Arrange
    user = User(name="test")

    # Act
    result = user.greet()

    # Assert
    assert result == "Hello, test"
```

### Fixtures (pytest)
```python
@pytest.fixture
def sample_data():
    return {"key": "value"}

def test_with_fixture(sample_data):
    assert sample_data["key"] == "value"
```

### Mocking
```python
from unittest.mock import patch, MagicMock

@patch("module.external_api")
def test_with_mock(mock_api):
    mock_api.return_value = {"data": "mocked"}
    result = function_under_test()
    assert result == "mocked"
```

## Test-Driven Development

1. **Red**: Write failing test
2. **Green**: Minimal code to pass
3. **Refactor**: Clean up

```bash
# Write test first
pytest tests/test_new_feature.py  # FAIL

# Implement feature
# ... code ...

pytest tests/test_new_feature.py  # PASS
```

## Coverage Commands

```bash
# Python
pytest --cov=src --cov-report=html
open htmlcov/index.html

# JavaScript
npm test -- --coverage
```

## Debugging Test Failures

```bash
# Verbose output
pytest -v --tb=long

# Drop into debugger on failure
pytest --pdb

# Print statements visible
pytest -s

# Last failed only
pytest --lf
```

## Confidence Integration

- `test_pass` → +5 confidence
- `test_ignored` → -5 confidence (modified test files without running)
- `change_without_test` → -3 confidence

Always run tests after changes to maintain confidence.
