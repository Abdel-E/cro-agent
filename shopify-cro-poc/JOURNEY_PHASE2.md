# Phase 2: Perception Module

Phase 2 adds an analyzer layer that turns raw funnel metrics into structured observations.

## What Phase 2 Adds

- `FunnelAnalyzer` for automated bottleneck detection.
- Stage-level drop-off detection.
- Segment underperformance detection.
- Conversion-trend decline detection from recent resolved decisions.
- New API endpoint: `GET /journey/observations`.

## Endpoint

### `GET /journey/observations`

Returns machine-readable observations that later phases can use for reasoning and autonomous actions.

Query params (all optional):

- `min_stage_impressions` (default `25`)
- `stage_drop_off_threshold` (default `0.55`)
- `min_segment_impressions` (default `12`)
- `segment_gap_threshold` (default `0.12`)
- `trend_window` (default `20`)
- `trend_decline_threshold` (default `0.15`)

Example:

```bash
curl -s "http://localhost:8000/journey/observations?min_stage_impressions=5&stage_drop_off_threshold=0.5"
```

Response includes:

- `totals`: count by severity (`high`, `medium`, `low`)
- `summary`: current bottleneck stage and drop-off rate
- `observations[]`: list of detected issues with evidence

Observation kinds:

- `stage_drop_off`
- `segment_underperforming`
- `stage_decline_trend`

## Fast Demo Flow

1. Run backend: `make run-backend`
2. Generate a short journey sample: `make journey-demo`
3. Pull observations:

```bash
curl -s "http://localhost:8000/journey/observations?min_stage_impressions=1&min_segment_impressions=1"
```

## Testing

Run Phase 2 tests only:

```bash
make test-perception
```

Run full backend suite:

```bash
make test
```

## Implementation Map

- Analyzer models: `backend/app/agent/models.py`
- Analyzer logic: `backend/app/agent/perception.py`
- State integration: `backend/app/state.py` (`journey_observations`)
- API route: `backend/app/main.py` (`/journey/observations`)
- API response models: `backend/app/models.py`
