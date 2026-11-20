"""Model pricing, for an honest cost estimate.

Cost is computed from the tokens the provider reports, priced from OpenRouter's
published table at run time. A hand-maintained price table drifts silently, and
a cost claim that is wrong is worse than no cost claim.

A free model prices at zero here because it *is* zero. The estimate says what
was spent, not what it would have cost on a paid model.
"""

from __future__ import annotations

from functools import lru_cache

import httpx

MODELS_URL = "https://openrouter.ai/api/v1/models"
TIMEOUT = 10.0


@lru_cache(maxsize=1)
def _prices() -> dict[str, tuple[float, float]]:
    """Price per token, keyed by model id. Empty if the catalogue is unreachable."""
    try:
        response = httpx.get(MODELS_URL, timeout=TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except Exception:  # noqa: BLE001 - a missing price is reported, not raised
        return {}

    prices: dict[str, tuple[float, float]] = {}
    for entry in payload.get("data", []):
        try:
            pricing = entry.get("pricing") or {}
            prices[str(entry["id"])] = (
                float(pricing.get("prompt") or 0.0),
                float(pricing.get("completion") or 0.0),
            )
        except (KeyError, TypeError, ValueError):
            continue
    return prices


def normalise(model_name: str | None) -> str | None:
    """Strip a provider prefix so a response's model name matches a price key."""
    if not model_name:
        return None
    return model_name[len("openrouter:") :] if model_name.startswith("openrouter:") else model_name


def estimate_cost(
    model_name: str | None, input_tokens: int, output_tokens: int
) -> float | None:
    """USD for one run, or None when the model is not in the price table."""
    key = normalise(model_name)
    if key is None:
        return None
    price = _prices().get(key)
    if price is None:
        return None
    return input_tokens * price[0] + output_tokens * price[1]
