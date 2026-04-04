# CRO Bandit PoC

Minimal proof of concept for CRO optimization using a multi-armed bandit.

This repo includes:

- `backend/`: FastAPI decision service using Thompson Sampling
- `frontend/`: Shopify-like hero banner demo page with 3 variants
- `simulator/`: Synthetic traffic runner to show learning behavior
- `shopify/`: **Theme section + Theme App Extension** to run the same API on a real storefront — see `shopify/README.md`

## Architecture

Browser or simulator calls `POST /decide` to get a variant for `hero_banner`.
On user action (or synthetic outcome), client calls `POST /feedback` with binary reward.
The bandit updates in-memory Beta posteriors and shifts allocation over time.

### Shopify storefront

Use the files under `shopify/` to add a **CRO contextual hero** to a live theme (manual section) or package it as a **Theme App Extension** with the Shopify CLI. You need a **public HTTPS** URL for the API (tunnel in dev). Details: **`shopify/README.md`**.

## Quick Start

### One-command flow (recommended)

From repo root:

```bash
make setup
make demo
```

In another terminal:

```bash
make reset
make simulate
make plot
```

Open **`http://localhost:5173`** for the storefront demo.

> **Important:** Port **8000** is the **API only** (JSON). The HTML UI is on **5173**. If you open `http://localhost:8000` you’ll see a small JSON message pointing you to the frontend.

### “404” lines in the backend log (`/.well-known/...`, `/mcp`)

If Uvicorn prints lines like:

- `GET /.well-known/oauth-authorization-server` → 404  
- `POST /mcp` / `GET /mcp` → 404  

those requests are **not** from this project. Editors and other local tools often probe `localhost:8000` for OAuth or MCP. **They are safe to ignore.** The access logger is configured to hide most of this noise.

If the **page** still looks broken, check the **browser devtools Console** for real errors (e.g. `Failed to fetch` = backend not running or wrong `API_BASE`).

### 1) Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 2) Frontend

In another terminal:

```bash
cd frontend
python3 -m http.server 5173
```

(On many Linux/WSL systems `python` is not installed; `make demo` uses `python3` by default. Override with `make demo PYTHON=python` if needed.)

Open `http://localhost:5173`.

### 3) Simulator

In another terminal:

```bash
cd simulator
pip install -r requirements.txt
python run_simulation.py --base-url http://localhost:8000 --sessions 5000 --ctrs "A=0.02,B=0.04,C=0.01" --uniform-baseline
```

This writes CSV logs to `simulator/output/`.

### 4) Generate charts from simulation output

From `simulator/`:

```bash
python plot_results.py
```

By default this reads the latest CSV in `simulator/output/` and writes:

- `demo_assets/allocation_share.png`
- `demo_assets/cumulative_reward.png`

## Tests

```bash
cd backend
pytest -q
```

Journey Phase 1 tests only:

```bash
make test-journey
```

Phase 2 perception tests only:

```bash
make test-perception
```

Phase 3 reasoning tests only:

```bash
make test-reasoning
```

Phase 4 execution/orchestration tests only:

```bash
make test-execution
```

Journey Phase 1 scripted demo flow (backend running):

```bash
make journey-demo
# or: make journey-demo OUTCOME=convert
```

## Demo Script (30 seconds)

1. Open storefront page and refresh a few times to show different hero variants.
2. Click CTA and show reward event accepted.
3. Run simulator with known true CTRs where B is best.
4. Keep storefront open and show live dashboard updating (CTR + allocation + recent rewards).
5. Show generated charts in `demo_assets/` to highlight learning trend over time.

## API

### `POST /decide`

Request:

```json
{
  "surface_id": "hero_banner",
  "context": {
    "device_type": "mobile",
    "traffic_source": "meta"
  }
}
```

Response:

```json
{
  "decision_id": "uuid",
  "surface_id": "hero_banner",
  "variant_id": "B",
  "probability": 0.6732,
  "policy": "thompson_sampling"
}
```

### `POST /feedback`

Request:

```json
{
  "decision_id": "uuid",
  "variant_id": "B",
  "reward": 1
}
```

### `GET /metrics`

Returns per-variant impressions/successes/failures/ctr plus totals and history.

## Journey API (Phase 1)

These endpoints add multi-page funnel tracking (`landing` -> `product_page` -> `cart`) while keeping existing `/decide` + `/feedback` endpoints intact.

Detailed usage + testing guide: `JOURNEY_PHASE1.md`.

Phase 2 perception guide: `JOURNEY_PHASE2.md`.

Phase 3 reasoning guide: `JOURNEY_PHASE3.md`.

Phase 4 execution + live loop guide: `JOURNEY_PHASE4.md`.

`/journey/decide` auto-creates missing `session_id` values.

Recommended simplified flow: use `decision_id` with `/journey/event`, and use `continue_from_decision_id` for next-stage `/journey/decide` calls.

### `POST /journey/decide`

Request:

```json
{
  "stage": "landing",
  "session_id": "optional-existing-session-id",
  "context": {
    "device_type": "mobile",
    "traffic_source": "meta"
  }
}
```

Response (shape):

```json
{
  "session_id": "uuid",
  "decision_id": "uuid",
  "stage": "landing",
  "variant_id": "A",
  "segment": "new_mobile_paid",
  "probability": 0.52,
  "policy": "contextual_thompson_sampling_journey",
  "content": {
    "headline": "...",
    "subtitle": "...",
    "cta_text": "...",
    "trust_signals": ["..."],
    "style_class": "variant-a"
  }
}
```

### `POST /journey/event`

Track what happened after a stage decision.

Recommended request shape (simplest):

- pass `decision_id` from `/journey/decide`
- omit `session_id` and `from_stage`

- `event_type="advance"` -> reward 1 for that stage decision (requires `to_stage`)
- `event_type="drop_off"` -> reward 0 for that stage decision
- `event_type="convert"` -> reward 1 and closes the session

Request:

```json
{
  "decision_id": "uuid",
  "event_type": "advance",
  "to_stage": "product_page"
}
```

### `GET /journey/metrics`

Returns funnel metrics per stage with:

- impressions, conversions, drop-offs, conversion rate
- per-variant and per-segment breakdowns
- stage transition counts (e.g. landing -> product_page)
- session totals and most common variant paths

### `GET /journey/observations` (Phase 2)

Returns analyzer-generated bottleneck observations (`stage_drop_off`, `segment_underperforming`, `stage_decline_trend`) with severity and evidence.

### `GET /journey/reasoning` (Phase 3)

Returns structured hypotheses, experiment plans, and an analytical insight summary generated from current observations.

### `POST /agent/tick` (Phase 4)

Runs one full observe -> reason -> launch -> graduate cycle. Supports optional demo traffic generation via `simulate_sessions`.

### `GET /agent/status` (Phase 4)

Returns live orchestrator status, active/completed experiments, and journey metrics snapshot.

### `GET /agent/history` (Phase 4)

Returns recent loop timeline events (`observe`, `reason`, `launch`, `graduate`, `noop`).

### `POST /reset`

Clears in-memory state for a fresh run.

## Notes

- PoC stores data in memory only; restart resets state.
- Contextual Thompson sampling + per-segment content; see `backend/app/` for details.

### LLM copy generation (Google Gemini)

**Option A — `.env` file (needs `python-dotenv` in the interpreter that runs Uvicorn)**

```bash
cp .env.example .env
# Edit .env: set GOOGLE_API_KEY=... (default model is gemini-2.5-flash)
```

The API loads **`shopify-cro-poc/.env`** first, then **`backend/.env`** (if present). If `python-dotenv` is not installed, `.env` files are skipped and only real process environment variables apply.

**Option B — externally managed Python (no `pip install` in this repo)**

If your environment is managed elsewhere (conda, system image, IDE, container, etc.):

1. Install **`fastapi`**, **`uvicorn`**, **`pydantic`**, **`google-generativeai`** (and optionally **`python-dotenv`**) using whatever your platform uses.
2. Set variables in that environment (shell, IDE Run Configuration, Kubernetes secrets, etc.):

   | Variable | Example |
   |----------|---------|
   | `GOOGLE_API_KEY` | from [Google AI Studio](https://aistudio.google.com/apikey) |
   | `COPY_GENERATOR_BACKEND` | `gemini` or `mock` |
   | `GEMINI_MODEL` | `gemini-2.5-flash` |

3. Start the API from `backend/` with your interpreter, e.g.  
   `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`

`POST /generate-copy` uses **Gemini** when `COPY_GENERATOR_BACKEND=gemini` and a key is set. If the key is missing or the SDK isn’t installed, the server still starts and uses the **mock** generator (with a log warning).

Reference lockfile for versions: `backend/requirements.txt` (you can mirror it in conda/poetry/etc.).
