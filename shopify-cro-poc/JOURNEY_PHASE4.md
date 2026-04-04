# Phase 4: Execution + Orchestration Loop

Phase 4 adds a live agent loop that closes the cycle:

1. Observe funnel bottlenecks
2. Reason into hypotheses + experiments
3. Launch experiments
4. Graduate experiments after enough traffic

## What Was Added

- `AgentOrchestrator` loop manager.
- `ExperimentExecutor` for launch + graduation lifecycle.
- Agent endpoints:
  - `POST /agent/tick`
  - `GET /agent/status`
  - `GET /agent/history`
- Demo traffic generation integrated into `POST /agent/tick` via `simulate_sessions`.
- Frontend live panel for real-time visualization.

## Endpoints

### `POST /agent/tick`

Runs one full cycle and optionally simulates traffic first.

Request example:

```json
{
  "simulate_sessions": 40,
  "min_stage_impressions": 15,
  "stage_drop_off_threshold": 0.5,
  "min_segment_impressions": 8,
  "segment_gap_threshold": 0.08,
  "trend_window": 20,
  "trend_decline_threshold": 0.15,
  "max_hypotheses": 3,
  "max_experiments": 3
}
```

Response includes launched/graduated experiments, recent loop events, and full status snapshot.

### `GET /agent/status`

Returns current loop status:

- tick count
- latest insight
- active/completed experiments
- current journey metrics snapshot

### `GET /agent/history?limit=80`

Returns loop timeline events (`observe`, `reason`, `launch`, `graduate`, `noop`).

## Live Visual Demo

1. Start backend + frontend:

```bash
make demo
```

2. Open: `http://localhost:5173`
3. In the **Autonomous Journey Agent Loop** panel:
   - click **Run 1 Tick** for manual cycle
   - click **Start Auto Loop** for continuous live action
   - adjust **Simulated sessions / tick** to speed up learning

You will see in real time:

- observation counts and bottleneck stage behavior
- reasoning hypotheses and insight text
- experiment launches and graduations in timeline

## Backend Testing

```bash
make test-execution
make test-journey
make test
```

## Implementation Map

- Execution engine: `backend/app/agent/execution.py`
- Loop orchestrator: `backend/app/agent/orchestrator.py`
- State integration: `backend/app/state.py` (`agent_tick`, `agent_status`, `agent_history`)
- Agent routes: `backend/app/main.py`
- Agent models: `backend/app/models.py`
- Live UI: `frontend/index.html`, `frontend/app.js`, `frontend/styles.css`
