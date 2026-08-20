"""Tests for yoker_test.usage."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from yoker_test.usage import fetch_ollama_usage


def make_config(api_key: str | None = "test-key") -> SimpleNamespace:
  """Create a config object with an ollama backend section."""
  ollama = SimpleNamespace(api_key=api_key) if api_key else None
  backend = SimpleNamespace(ollama=ollama)
  return SimpleNamespace(backend=backend)


def make_response(data: dict, status: int = 200) -> MagicMock:
  """Create a mock httpx response."""
  resp = MagicMock()
  resp.status_code = status
  resp.json.return_value = data
  if status >= 400:
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
      "error", request=MagicMock(), response=resp
    )
  else:
    resp.raise_for_status.return_value = None
  return resp


class TestFetchOllamaUsageNoApiKey:
  """Tests for missing API key / ollama config."""

  async def test_no_ollama_config(self):
    config = SimpleNamespace(backend=SimpleNamespace(ollama=None))
    result = await fetch_ollama_usage(config)
    assert result is None

  async def test_no_api_key(self):
    config = make_config(api_key=None)
    result = await fetch_ollama_usage(config)
    assert result is None

  async def test_empty_api_key(self):
    ollama = SimpleNamespace(api_key="")
    config = SimpleNamespace(backend=SimpleNamespace(ollama=ollama))
    result = await fetch_ollama_usage(config)
    assert result is None


class TestFetchOllamaUsageSuccess:
  """Tests for successful API response parsing."""

  async def test_parses_usage_data(self):
    data = {
      "limits": {
        "session": {"usage": 0.15},
        "weekly": {"usage": 0.42},
      }
    }
    resp = make_response(data)
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get.return_value = resp

    with patch("yoker_test.usage.httpx.AsyncClient", return_value=client):
      result = await fetch_ollama_usage(make_config())

    assert result == {"session": 0.15, "weekly": 0.42}

  async def test_defaults_to_zero_when_missing_fields(self):
    data = {"limits": {}}
    resp = make_response(data)
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get.return_value = resp

    with patch("yoker_test.usage.httpx.AsyncClient", return_value=client):
      result = await fetch_ollama_usage(make_config())

    assert result == {"session": 0.0, "weekly": 0.0}

  async def test_defaults_to_zero_when_limits_missing(self):
    data = {}
    resp = make_response(data)
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get.return_value = resp

    with patch("yoker_test.usage.httpx.AsyncClient", return_value=client):
      result = await fetch_ollama_usage(make_config())

    assert result == {"session": 0.0, "weekly": 0.0}

  async def test_partial_limits(self):
    data = {"limits": {"session": {"usage": 0.5}}}
    resp = make_response(data)
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get.return_value = resp

    with patch("yoker_test.usage.httpx.AsyncClient", return_value=client):
      result = await fetch_ollama_usage(make_config())

    assert result == {"session": 0.5, "weekly": 0.0}

  async def test_sends_authorization_header(self):
    data = {"limits": {"session": {"usage": 0.1}, "weekly": {"usage": 0.2}}}
    resp = make_response(data)
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get.return_value = resp

    with patch("yoker_test.usage.httpx.AsyncClient", return_value=client):
      await fetch_ollama_usage(make_config(api_key="my-secret-key"))

    client.get.assert_called_once()
    _, kwargs = client.get.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer my-secret-key"


class TestFetchOllamaUsageErrors:
  """Tests for error handling."""

  async def test_http_error_returns_none(self):
    resp = make_response({}, status=403)
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get.return_value = resp

    with patch("yoker_test.usage.httpx.AsyncClient", return_value=client):
      result = await fetch_ollama_usage(make_config())

    assert result is None

  async def test_network_error_returns_none(self):
    client = AsyncMock()
    client.__aenter__.side_effect = httpx.ConnectError("connection refused")

    with patch("yoker_test.usage.httpx.AsyncClient", return_value=client):
      result = await fetch_ollama_usage(make_config())

    assert result is None

  async def test_timeout_error_returns_none(self):
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get.side_effect = httpx.ReadTimeout("timed out")

    with patch("yoker_test.usage.httpx.AsyncClient", return_value=client):
      result = await fetch_ollama_usage(make_config())

    assert result is None

  async def test_json_decode_error_returns_none(self):
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status.return_value = None
    resp.json.side_effect = ValueError("invalid json")
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get.return_value = resp

    with patch("yoker_test.usage.httpx.AsyncClient", return_value=client):
      result = await fetch_ollama_usage(make_config())

    assert result is None
