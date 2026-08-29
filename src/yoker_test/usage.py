"""Usage metrics for yoker-test: normalized snapshots from the backend's usage API.

Transport lives in yoker's ``OllamaBackend.fetch_usage()`` — injected backends are
shared across the whole run, so this module is deliberately transport-free.

Security invariants (see analysis/security-credit-usage.md):
  - The raw API payload is never persisted or logged. Only the normalized
    snapshot below may reach schema fields. The raw payload also contains
    per-model counts for *all* models the account used — persisting the raw
    body would leak unrelated account activity into saved reports.
  - Snapshots are account-level, low-sensitivity footprint data.
  - A failed / non-Ollama usage fetch degrades silently to None (never raises).
"""

from typing import Any


def extract_usage_metrics(payload: dict) -> dict:
  """Normalize yoker's OllamaBackend.fetch_usage() payload into a snapshot.

  Tolerates missing keys (partial windows / shape changes). The session and
  weekly fractions are 0–1 shares of the 5-hour (session) / 7-day (weekly)
  quota window upstream.
    {"session": fraction 0-1 from limits.session.usage,
     "weekly":  fraction from limits.weekly.usage,
     "requests": {model: count} from limits.<w>.models[].request_count,
     "extra_usage_cost": float from activity.cost (USD string) or None}
  """
  limits = payload.get("limits", {})
  session = limits.get("session", {})
  weekly = limits.get("weekly", {})
  activity = payload.get("activity", {})
  return {
    "session": session.get("usage", 0.0),
    "weekly": weekly.get("usage", 0.0),
    "requests": {
      m["name"]: m["request_count"]
      for m in weekly.get("models", [])
      if isinstance(m, dict) and "name" in m and "request_count" in m
    },
    "extra_usage_cost": _parse_cost(activity.get("cost")),
  }


async def fetch_usage_metrics(backend: Any) -> dict | None:
  """One normalized usage snapshot from a yoker backend, or None.

  Works only on backends that expose ``fetch_usage()`` (OllamaBackend);
  ``fetch_usage()`` never raises, but a wrapper-level blanket exception keeps
  this degradation contract unconditional at the call site.
  """
  if not hasattr(backend, "fetch_usage"):
    return None
  try:
    payload = await backend.fetch_usage()
  except Exception:
    return None
  if not payload:
    return None
  return extract_usage_metrics(payload)


def _parse_cost(value: Any) -> float | None:
  """Parse activity.cost (USD string) to float; None when missing/malformed."""
  if value is None:
    return None
  try:
    return float(value)
  except (TypeError, ValueError):
    return None
