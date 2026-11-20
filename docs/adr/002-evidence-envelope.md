# ADR-002 — The evidence envelope is the system's core interface

**Status:** accepted

## Context

"Every metric must be traceable" is a project value, but values are not
enforceable. If traceability lives in a document or a prompt, it will be
dropped under time pressure — most likely by the language model, which is the
component least able to know what it does not know.

## Decision

Every published number is produced as an `EvidenceEnvelope`
(`src/climate_resilience/envelope.py`) carrying value, unit, indicator and
method identity, scope, period and basis, hazard parameters, dataset versions
and checksums, uncertainty, quality and run provenance. Envelopes are validated
at construction, and the mart row is a flattened envelope. The assistant may
restate envelope fields and nothing else.

## Consequences

- Citation, attribution and abstention become mechanical rather than
  aspirational: a null field must be reported as null.
- Every tool output is verbose. Prompts grow and token cost rises; addressed by
  sending only the fields a question needs.
- Hazard-specific constraints are enforced in one place: a flood envelope
  without a mechanism cannot be constructed, and a projection without a
  scenario cannot be constructed.
- Changing the envelope is a schema change for the mart, the tools, the
  assistant and the reports. That coupling is deliberate.
