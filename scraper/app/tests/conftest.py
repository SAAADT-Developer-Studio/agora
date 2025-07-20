"""
Test configuration and fixtures for the scraper application.
"""

import pytest
import os
import sys
from pathlib import Path

# Add the app directory to the Python path for test imports
app_dir = Path(__file__).parent.parent
sys.path.insert(0, str(app_dir))

# TODO: Add database test fixtures when needed
# TODO: Add HTTP client mocking fixtures when needed
# TODO: Add environment variable fixtures for testing different configs


@pytest.fixture(scope="session")
def test_data_dir():
    """Return the path to test data directory."""
    return Path(__file__).parent / "data"


# TODO: Add more fixtures as the test suite grows:
# - database_session
# - mock_http_client
# - test_config
# - sample_articles
