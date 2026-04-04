# Phase 1: Journey Bandit API

Phase 1 adds a multi-stage journey layer on top of the existing single-surface bandit.

- Existing APIs (`/decide`, `/feedback`, `/metrics`) still work.
- New APIs track a top-of-funnel journey: `landing -> product_page -> cart`.
- Each stage has its own contextual Thompson sampler and reward updates.
- A `session_id` ties decisions and events together across stages.

## What This Phase Does

1. Returns a variant decision per stage (`/journey/decide`).
2. Records stage outcomes (`/journey/event`) as conversion (`reward=1`) or drop-off (`reward=0`).
3. Exposes funnel metrics by stage, segment, and variant (`/journey/metrics`).
4. Tracks common variant paths across sessions (for attribution and analysis).

## Core Concepts

- `stage`: one of `landing`, `product_page`, `cart`.
- `session_id`: visitor journey key. Create on first decide; reuse on later stages.
- If you pass a `session_id` to `/journey/decide` that does not exist yet, it is auto-created.
- `decision_id`: unique decision for one stage in one session.
- Recommended: call `/journey/event` with `decision_id` (no stage/session lookup needed).
- `continue_from_decision_id` on `/journey/decide` keeps the same session automatically.
- `event_type`:
  - `advance` -> user moved to next stage (`reward=1`, requires `to_stage`)
  - `drop_off` -> user left at this stage (`reward=0`)
  - `convert` -> user completed desired step (`reward=1`, terminal)

## API Usage (Happy Path)

Assumes backend is running on `http://localhost:8000`.

### 1) Decide for landing stage

```bash
curl -s -X POST http://localhost:8000/journey/decide \
  -H "Content-Type: application/json" \
  -d '{
    "stage": "landing",
    "context": {
      "device_type": "mobile",
      "traffic_source": "meta",
      "is_returning": false
    }
  }'
```

Save `session_id` from the response.

### 2) Mark that user advanced to product page

```bash
curl -s -X POST http://localhost:8000/journey/event \
  -H "Content-Type: application/json" \
  -d '{
    "decision_id": "<LANDING_DECISION_ID>",
    "event_type": "advance",
    "to_stage": "product_page"
  }'
```

### 3) Decide for product stage in same journey

```bash
curl -s -X POST http://localhost:8000/journey/decide \
  -H "Content-Type: application/json" \
  -d '{
    "continue_from_decision_id": "<LANDING_DECISION_ID>",
    "stage": "product_page"
  }'
```

### 4) Mark product-stage outcome

Drop-off example:

```bash
curl -s -X POST http://localhost:8000/journey/event \
  -H "Content-Type: application/json" \
  -d '{
    "decision_id": "<PRODUCT_DECISION_ID>",
    "event_type": "drop_off"
  }'
```

Conversion example:

```bash
curl -s -X POST http://localhost:8000/journey/event \
  -H "Content-Type: application/json" \
  -d '{
    "decision_id": "<PRODUCT_DECISION_ID>",
    "event_type": "convert"
  }'
```

### 5) Read funnel metrics

```bash
curl -s http://localhost:8000/journey/metrics
```

Key response sections:

- `stages.<stage>.impressions`
- `stages.<stage>.conversions`
- `stages.<stage>.drop_offs`
- `stages.<stage>.variants.<variant>.conversion_rate`
- `stages.<stage>.segments.<segment>.conversion_rate`
- `stages.<stage>.transitions`
- `top_paths`

## Error Rules

- `advance` without `to_stage` -> `400`
- `drop_off` or `convert` with `to_stage` -> `400`
- `/journey/event` without identifiers (`decision_id`, or `session_id` + `from_stage`) -> `400`
- unknown `decision_id` on `/journey/event` -> `404`
- unknown `session_id` on `/journey/event` (legacy mode) -> `404`
- unknown `continue_from_decision_id` on `/journey/decide` -> `404`
- conflicting second outcome for same stage decision -> `409`
- same exact repeated outcome -> idempotent `200` (`accepted=false`, `idempotent=true`)

## Troubleshooting: "Unknown session_id"

Prefer using `decision_id` with `/journey/event` to avoid session/stage lookup issues.

If you still use legacy mode (`session_id` + `from_stage`), this usually means `/journey/event` is being called before a matching `/journey/decide` for that session and stage.

Checklist:

1. Call `/journey/decide` first and keep the returned `decision_id`.
2. Send that `decision_id` to `/journey/event`.
3. For next-stage decide calls, pass `continue_from_decision_id` instead of manually copying `session_id`.
4. If you restart backend or call `/reset`, in-memory decisions/sessions are cleared; start from a new decide.

## Testing This Phase

### One-command demo flow

From repo root (backend must be running):

```bash
make journey-demo
```

Run conversion variant instead of drop-off:

```bash
make journey-demo OUTCOME=convert
```

The script executes:

1. `/reset` (unless disabled)
2. landing `/journey/decide`
3. landing `/journey/event` advance to `product_page`
4. product `/journey/decide` via `continue_from_decision_id`
5. product `/journey/event` with `drop_off` or `convert`
6. `/journey/metrics` summary printout

### Automated tests

From `backend/`:

```bash
PYTHONPATH=. pytest -q tests/test_api.py -k journey
```

Full suite:

```bash
PYTHONPATH=. pytest -q
```

### Manual smoke flow

1. `POST /reset`
2. `POST /journey/decide` for `landing`
3. `POST /journey/event` (`advance` to `product_page`)
4. `POST /journey/decide` for `product_page`
5. `POST /journey/event` (`drop_off` or `convert`)
6. `GET /journey/metrics` and confirm stage counts increased

## Where To Edit

- Stage list and order: `backend/app/funnel.py`
- Journey state machine and reward mapping: `backend/app/state.py`
- Stage-specific content templates: `backend/app/state.py` (`_build_journey_content`)
- Request/response contracts: `backend/app/models.py`
- Route wiring and status mapping: `backend/app/main.py`

## Current Scope Limits

- In-memory storage only (restart clears journey data).
- One decision per stage per session (new decision for same stage overwrites stage pointer in session).
- No persistence or async agent loop yet (comes in later phases).
