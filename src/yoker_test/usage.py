"""Usage tracking for yoker-test: fetch Ollama API usage percentages."""

from typing import Any

import httpx


async def fetch_ollama_usage(config: Any) -> dict[str, float] | None:
  """Fetch current Ollama API usage percentages.

  Returns dict with 'session' and 'weekly' usage fractions,
  or None if not available (no API key, not Ollama, etc.).
  """
  ollama_cfg = getattr(config.backend, "ollama", None)
  if not ollama_cfg or not ollama_cfg.api_key:
    return None
  try:
    async with httpx.AsyncClient(timeout=10) as client:
      resp = await client.get(
        "https://ollama.com/api/usage",
        headers={"Authorization": f"Bearer {ollama_cfg.api_key}"},
      )
      resp.raise_for_status()
      data = resp.json()
  except Exception:
    return None

  limits = data.get("limits", {})
  return {
    "session": limits.get("session", {}).get("usage", 0.0),
    "weekly": limits.get("weekly", {}).get("usage", 0.0),
  }
