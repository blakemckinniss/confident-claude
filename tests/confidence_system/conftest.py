"""Shared fixtures for confidence tests."""

import sys
from pathlib import Path

# Add this directory to path for _fixtures import
sys.path.insert(0, str(Path(__file__).parent))

import pytest  # noqa: E402

from _fixtures import MockSessionState  # noqa: E402


@pytest.fixture
def state():
    """Provide a fresh MockSessionState for each test."""
    return MockSessionState()
