"""Tests for yoker_test.usage — normalized extraction from backend usage payloads."""

from yoker_test.usage import extract_usage_metrics, fetch_usage_metrics


class FakeUsageBackend:
  """Minimal backend exposing fetch_usage() with a canned payload."""

  def __init__(self, payload, fail=False):
    self._payload = payload
    self._fail = fail
    self.calls = 0

  async def fetch_usage(self):
    self.calls += 1
    if self._fail:
      raise RuntimeError("network down")
    return self._payload


FULL_PAYLOAD = {
  "activity": {"cost": "0.04600", "period": {"type": "last_4_weeks"}},
  "limits": {
    "session": {
      "usage": 0.046,
      "models": [
        {"name": "glm-5.2", "request_count": 34},
        {"name": "minimax-m3", "request_count": 2},
      ],
    },
    "weekly": {
      "usage": 0.051,
      "models": [
        {"name": "glm-5.2", "request_count": 254},
        {"name": "minimax-m3", "request_count": 107},
      ],
    },
  },
}


class TestExtractUsageMetrics:
  """Tests for extract_usage_metrics (pure payload normalization)."""

  def test_full_payload(self):
    snap = extract_usage_metrics(FULL_PAYLOAD)
    assert snap["session"] == 0.046
    assert snap["weekly"] == 0.051
    assert snap["requests"] == {"glm-5.2": 254, "minimax-m3": 107}
    assert snap["extra_usage_cost"] == 0.046

  def test_missing_keys_tolerated(self):
    snap = extract_usage_metrics({})
    assert snap == {"session": 0.0, "weekly": 0.0, "requests": {}, "extra_usage_cost": None}

  def test_partial_windows(self):
    snap = extract_usage_metrics({"limits": {"session": {"usage": 0.5}}})
    assert snap["session"] == 0.5
    assert snap["weekly"] == 0.0
    assert snap["requests"] == {}

  def test_malformed_cost_returns_none(self):
    snap = extract_usage_metrics({"activity": {"cost": "not-a-number"}})
    assert snap["extra_usage_cost"] is None

  def test_none_cost_stays_none(self):
    snap = extract_usage_metrics({"activity": {}})
    assert snap["extra_usage_cost"] is None

  def test_malformed_model_entries_skipped(self):
    payload = {
      "limits": {
        "weekly": {
          "usage": 0.1,
          "models": [
            {"name": "m1"},
            {"request_count": 3},
            "garbage",
            {"name": "m2", "request_count": 7},
          ],
        }
      }
    }
    snap = extract_usage_metrics(payload)
    assert snap["requests"] == {"m2": 7}

  def test_normalized_fields_only(self):
    """Security invariant: only the documented normalized keys exist."""
    snap = extract_usage_metrics(FULL_PAYLOAD)
    assert set(snap.keys()) == {"session", "weekly", "requests", "extra_usage_cost"}


class TestFetchUsageMetrics:
  """Tests for fetch_usage_metrics (backend wrapper)."""

  async def test_backend_without_fetch_usage_returns_none(self):
    assert await fetch_usage_metrics(object()) is None

  async def test_backend_none_payload_returns_none(self):
    backend = FakeUsageBackend(payload=None)
    assert await fetch_usage_metrics(backend) is None
    assert backend.calls == 1

  async def test_happy_path_extracts_normalized(self):
    backend = FakeUsageBackend(FULL_PAYLOAD)
    snap = await fetch_usage_metrics(backend)
    assert snap["session"] == 0.046
    assert snap["requests"] == {"glm-5.2": 254, "minimax-m3": 107}
    assert set(snap.keys()) == {"session", "weekly", "requests", "extra_usage_cost"}

  async def test_backend_failure_degrades_to_none(self):
    backend = FakeUsageBackend(None, fail=True)
    assert await fetch_usage_metrics(backend) is None
