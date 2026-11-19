from __future__ import annotations

import pytest

from app.config import Settings


def test_service_url_is_required(monkeypatch):
    monkeypatch.delenv("AFTERSALE_JAVA_BASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="AFTERSALE_JAVA_BASE_URL"):
        Settings.from_env()


@pytest.mark.parametrize("url", [
    "https://user:private-value@backend.example",
    "https://backend.example?key=private-value",
    "https://backend.example#private-value",
    "file:///tmp/backend", "https://backend.example.invalid",
])
def test_invalid_url_is_rejected_without_logging_its_credentials(monkeypatch, url):
    monkeypatch.setenv("AFTERSALE_JAVA_BASE_URL", url)
    with pytest.raises(RuntimeError, match="AFTERSALE_JAVA_BASE_URL") as error:
        Settings.from_env()
    assert "private-value" not in str(error.value)


def test_explicit_local_service_url_is_supported(monkeypatch):
    monkeypatch.setenv("AFTERSALE_JAVA_BASE_URL", "http://127.0.0.1:18080/")
    assert Settings.from_env().java_base_url == "http://127.0.0.1:18080"
