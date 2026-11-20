# ADR-012 — Agent budget, grounding contract and pre-flight refusal

**Status:** accepted

## Context

The assistant selects tools and explains their results. Three properties had to
survive contact with an agent framework, which is not where they usually live:
a hard cost ceiling, a citation on every number, and a refusal that cannot be
talked out of.

Pydantic AI's default is a tool loop. The specification allows two model calls
and three tool calls per question, with a p95 target of 6 s and $0.004. Those
are enforced by the runtime, not requested in a prompt.

## Decision

- **`UsageLimits(request_limit=2, tool_calls_limit=3)`.** Two requests is the
  design: the first selects tools, the second synthesises. A third round is
  stopped by the runtime and the run is reported as incomplete.
- **One model per run.** Model tiering (small model for intent, capable model
  for synthesis) is not expressible in a single Pydantic AI run, because the
  two requests belong to one agent execution. It is deferred, and the
  configuration reads a single `LLM_MODEL_SYNTHESIS`.
- **`output_type=Answer` with a validator.** A non-abstained answer without a
  citation is not constructible; an abstention without a named gap is not
  constructible. This moves grounding from an instruction into a type.
- **Citations name the key.** `row_key` for measurements, `chunk_id` for
  documents. Tools return those keys alongside envelopes, because a citation
  that cannot be resolved is decoration.
- **Pre-flight refusal before any token is spent.** Pluvial measurement
  requests and requests for datasets that do not exist are refused from the
  text. The distinction that keeps this sound is *measurement intent*: "what
  does the plan say about pluvial flooding" is a document question and passes;
  "how many people are exposed to pluvial flooding" is refused.
- **Tool results are trimmed to ten rows.** An unbounded `rank_scopes` result
  would put the whole mart in the prompt. The trim is stated to the model, so a
  truncated ranking is never mistaken for a complete one.
- **The flood caveat is post-checked.** If any flood measurement entered the
  run and the answer does not mention pluvial flooding, the caveat is appended.
  The prompt requires it; the post-check guarantees it.
- **A missing key is an abstention, not an exception.** Without
  `OPENROUTER_API_KEY` the assistant says so and makes zero requests, which is
  a more useful failure than a stack trace at the CLI.

## Measured

Run against `particle-ai/particle-1:free`, twenty questions in: the budget
holds, the citation contract holds, and the 6 s p95 target does **not**. Two
sequential calls over ~8.4k tokens cost 10-18 s on the free tier and 16.6 s on
a cheap paid model.

Two findings changed the configuration:

- The two-request budget is not a property of model quality but of model
  behaviour. `mistral-nemo` and `nova-micro` both call tools correctly and both
  still need a third round to emit the structured answer; `gpt-oss-20b` refused
  to call a tool at all. Both defaults are now models that were *observed* to
  finish in two requests.
- Input tokens dominate. Per-row licences and warning lists are repeated on
  every measurement, which is most of the 8.4k. Trimming the payload is the
  first latency lever, ahead of changing models.

## Consequences

- Offline tests exercise the whole orchestration with `FunctionModel`: tool
  selection, budget exhaustion, the citation contract and the caveat. Only the
  model's own judgement needs a key, and only that part is unmeasured.
- A model that fails answer validation can consume the second request and leave
  the run incomplete. That is the intended trade: an invalid answer costs an
  abstention, not an unsourced number.
- The guard is keyword-based and deliberately narrow. A question it misses
  still reaches tools that cannot answer it, so the failure mode is a slower
  refusal, not a wrong answer.
- No response cache yet. Repeated questions cost the same as first ones, which
  is visible in the cost measurement that has not run.

## Revisit triggers

- A measured p95 above 6 s or cost above $0.004: add the canonicalised-question
  cache and revisit tiering with a two-agent split.
- The guard mis-refusing answerable questions: replace keyword detection with a
  cheap classifier and measure the change against the gold set.
- Retrieval evaluation shows documents carrying too much prompt weight: reduce
  the document cap or move to a summarise-then-synthesise split, at the cost of
  a third request.
