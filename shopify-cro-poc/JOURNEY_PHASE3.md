# Phase 3: Reasoning Module

Phase 3 adds hypothesis and experiment planning on top of Phase 2 observations.

## What Phase 3 Adds

- Structured hypothesis generation from bottleneck observations.
- Structured experiment proposals tied to hypotheses.
- Analytical insight text summarizing what to do next.
- New API endpoint: `GET /journey/reasoning`.

By default this uses a deterministic mock reasoner for reliability. Optional Gemini backend is supported via env.

## Endpoint

### `GET /journey/reasoning`

Generates:

- `insight`: concise analytical summary
- `hypotheses[]`: ranked possible root causes
- `experiments[]`: concrete tests linked to hypothesis IDs

Query params:

- Observation thresholds (same as Phase 2):
  - `min_stage_impressions`
  - `stage_drop_off_threshold`
  - `min_segment_impressions`
  - `segment_gap_threshold`
  - `trend_window`
  - `trend_decline_threshold`
- Reasoning controls:
  - `max_hypotheses` (default `3`)
  - `max_experiments` (default `3`)

Example:

```bash
curl -s "http://localhost:8000/journey/reasoning?min_stage_impressions=5&max_hypotheses=2&max_experiments=2"
```

## Fast Demo Flow

1. Run backend: `make run-backend`
2. Seed one journey sample: `make journey-demo`
3. Generate reasoning:

```bash
curl -s "http://localhost:8000/journey/reasoning?min_stage_impressions=1&min_segment_impressions=1"
```

## Optional Gemini Backend

Default backend is `mock`.

To enable Gemini:

```bash
export AGENT_REASONER_BACKEND=gemini
export GOOGLE_API_KEY=your_key
# optional
export AGENT_REASONER_MODEL=gemini-2.5-flash
```

If Gemini is unavailable, reasoning falls back to mock automatically.

## Testing

Run Phase 3 tests only:

```bash
make test-reasoning
```

Run full suite:

```bash
make test
```

## Implementation Map

- Prompt templates: `backend/app/agent/prompts.py`
- Reasoning backends: `backend/app/agent/reasoning.py`
- State integration: `backend/app/state.py` (`journey_reasoning`)
- API route: `backend/app/main.py` (`/journey/reasoning`)
- API models: `backend/app/models.py`
