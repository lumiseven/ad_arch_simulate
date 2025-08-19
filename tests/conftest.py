"""
Pytest configuration and shared fixtures.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def test_client():
    """Create a test client fixture."""
    # This will be used by individual service tests
    pass