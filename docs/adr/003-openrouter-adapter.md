# ADR-003 — OpenRouter behind a thin adapter, with tiered models

**Status:** proposed (not implemented; Phase 9)

## Context

The assistant needs a hosted model. Direct provider SDKs couple the codebase to
one vendor's request shape; a single large model for both intent parsing and
answer synthesis wastes money on a task that is mostly classification.

## Decision

All model access goes through one adapter module exposing `complete(messages,
tools, model) -> response`. Model IDs come from configuration
(`LLM_MODEL_INTENT`, `LLM_MODEL_SYNTHESIS`). Orchestration is two calls maximum:
a small model selects the tool and extracts parameters, a capable model
synthesises from the returned envelopes.

## Consequences

- Swapping providers is an adapter change, not a refactor.
- Two model IDs and their pricing must be benchmarked, not guessed.
- Two calls cap both latency and cost; complex multi-step questions are
  answered by asking the user, not by looping.
- A provider outage degrades the assistant but never the analytics: the mart
  and tools remain usable directly through the API.
