"""Pins settings for the suite.

Settings read `.env`, so without this the tests pass or fail depending on what a
developer happens to have configured locally. Env vars take precedence over the
file, so setting them here isolates the suite from it.
"""

import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def isolate_settings(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("VAPI_SECRET", "")
    monkeypatch.setenv("VAPI_SECRET_HEADER", "x-vapi-secret")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://test.example.com")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
