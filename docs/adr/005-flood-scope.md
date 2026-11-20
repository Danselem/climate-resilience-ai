# ADR-005 — Flood hazard is riverine and coastal only; pluvial is excluded

**Status:** proposed (not implemented; Phase 5)

## Context

Flood analysis is a required capability. Open, metro-scale flood hazard data
exists for riverine and coastal flooding (WRI Aqueduct Floods v2, ~1 km,
multiple return periods and scenarios, CC BY 4.0). It does not exist for
pluvial (surface-water) flooding at this scale.

The April 2022 KwaZulu-Natal floods were substantially pluvial. A platform that
silently presents riverine exposure as general flood risk would be most wrong
exactly where it matters most.

## Decision

Model riverine and coastal flood only. Encode the constraint in the data
model: `mechanism` is required on every flood envelope, `pluvial` is not a
permitted value, and the indicator registry contains no pluvial indicator.
State the limitation on every flood surface, in the report header, and in the
benchmark as questions that must be refused.

## Consequences

- Users get an honest, defensible riverine/coastal exposure figure rather than
  a misleading composite.
- The demo cannot claim general flood risk. This is a presentation cost
  accepted in exchange for not misleading a municipality.
- Validation must compare against a mapped riverine event (Copernicus EMS
  extent), not against pluvial damage reports, which would produce a false
  failure.
- If eThekwini's own floodline studies become available and licensed, a new ADR
  can introduce pluvial with its own mechanism value.
