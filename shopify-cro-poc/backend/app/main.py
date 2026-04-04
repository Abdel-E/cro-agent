from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware


def _load_dotenv_files() -> None:
    """Load `.env` if `python-dotenv` is installed; otherwise no-op.

    Externally managed environments often inject vars (IDE, container, systemd)
    and may not install `python-dotenv` in the project interpreter.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    backend_dir = Path(__file__).resolve().parent.parent
    repo_dir = backend_dir.parent
    load_dotenv(repo_dir / ".env")
    load_dotenv(backend_dir / ".env", override=True)


# Load env before JourneyState (and copy generator) is constructed.
_load_dotenv_files()

from app.models import (
    AgentHistoryResponse,
    AgentStatusResponse,
    AgentTickRequest,
    AgentTickResponse,
    DecideRequest,
    DecideResponse,
    FeedbackRequest,
    FeedbackResponse,
    GenerateCopyRequest,
    GenerateCopyResponse,
    HealthResponse,
    JourneyDecideRequest,
    JourneyDecideResponse,
    JourneyEventRequest,
    JourneyEventResponse,
    JourneyMetricsResponse,
    JourneyObservationsResponse,
    JourneyReasoningResponse,
    MetricsResponse,
    ResetResponse,
    SegmentsResponse,
)
from app.state import (
    ConflictingFeedbackError,
    ConflictingJourneyOutcomeError,
    InvalidJourneyEventError,
    JourneyState,
    UnknownDecisionError,
    UnknownSessionError,
    VariantMismatchError,
)


app = FastAPI(title="CRO Contextual Personalization Agent", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

state = JourneyState(seed=42)


def _merge_context(
    context: dict[str, object],
    *,
    device_type: str | None,
    traffic_source: str | None,
    is_returning: bool | None,
    segment_hint: str | None,
) -> dict[str, object]:
    merged = dict(context)
    if device_type:
        merged.setdefault("device_type", device_type)
    if traffic_source:
        merged.setdefault("traffic_source", traffic_source)
    if is_returning is True:
        merged.setdefault("is_returning", is_returning)
    if segment_hint:
        merged.setdefault("segment_hint", segment_hint)
    return merged


class _QuietProbePathsFilter(logging.Filter):
    """Hide noisy 404s from IDEs/tools probing dev servers (not our app)."""

    _NOISE = ("/.well-known/", "/mcp")

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(n in msg for n in self._NOISE)


logging.getLogger("uvicorn.access").addFilter(_QuietProbePathsFilter())


@app.get("/")
def root() -> dict[str, str]:
    """If you open port 8000 in a browser, this explains where the UI lives."""
    return {
        "service": "CRO Contextual Personalization API",
        "docs": "/docs",
        "health": "/health",
        "frontend": "http://localhost:5173 (run: cd frontend && python -m http.server 5173)",
        "note": "404s for /.well-known/* or /mcp are from other tools (e.g. IDE), not this app.",
    }


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/decide", response_model=DecideResponse)
def decide(payload: DecideRequest) -> DecideResponse:
    merged_context = _merge_context(
        payload.context,
        device_type=payload.device_type,
        traffic_source=payload.traffic_source,
        is_returning=payload.is_returning,
        segment_hint=payload.segment_hint,
    )

    try:
        response = state.decide(payload.surface_id, merged_context)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DecideResponse(**response)


@app.post("/feedback", response_model=FeedbackResponse)
def feedback(payload: FeedbackRequest) -> FeedbackResponse:
    try:
        response = state.feedback(
            decision_id=payload.decision_id,
            variant_id=payload.variant_id,
            reward=payload.reward,
        )
    except UnknownDecisionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VariantMismatchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ConflictingFeedbackError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return FeedbackResponse(**response)


@app.post("/journey/decide", response_model=JourneyDecideResponse)
def journey_decide(payload: JourneyDecideRequest) -> JourneyDecideResponse:
    merged_context = _merge_context(
        payload.context,
        device_type=payload.device_type,
        traffic_source=payload.traffic_source,
        is_returning=payload.is_returning,
        segment_hint=payload.segment_hint,
    )
    try:
        response = state.journey_decide(
            stage=payload.stage,
            context=merged_context,
            session_id=payload.session_id,
            continue_from_decision_id=payload.continue_from_decision_id,
        )
    except UnknownDecisionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UnknownSessionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JourneyDecideResponse(**response)


@app.post("/journey/event", response_model=JourneyEventResponse)
def journey_event(payload: JourneyEventRequest) -> JourneyEventResponse:
    try:
        response = state.journey_event(
            event_type=payload.event_type,
            decision_id=payload.decision_id,
            session_id=payload.session_id,
            from_stage=payload.from_stage,
            to_stage=payload.to_stage,
        )
    except UnknownSessionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UnknownDecisionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidJourneyEventError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ConflictingJourneyOutcomeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JourneyEventResponse(**response)


@app.get("/journey/metrics", response_model=JourneyMetricsResponse)
def journey_metrics() -> JourneyMetricsResponse:
    return JourneyMetricsResponse(**state.journey_metrics())


@app.get("/journey/observations", response_model=JourneyObservationsResponse)
def journey_observations(
    min_stage_impressions: int = Query(default=25, ge=1, le=100000),
    stage_drop_off_threshold: float = Query(default=0.55, ge=0.0, le=1.0),
    min_segment_impressions: int = Query(default=12, ge=1, le=100000),
    segment_gap_threshold: float = Query(default=0.12, ge=0.0, le=1.0),
    trend_window: int = Query(default=20, ge=2, le=10000),
    trend_decline_threshold: float = Query(default=0.15, ge=0.0, le=1.0),
) -> JourneyObservationsResponse:
    try:
        payload = state.journey_observations(
            min_stage_impressions=min_stage_impressions,
            stage_drop_off_threshold=stage_drop_off_threshold,
            min_segment_impressions=min_segment_impressions,
            segment_gap_threshold=segment_gap_threshold,
            trend_window=trend_window,
            trend_decline_threshold=trend_decline_threshold,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JourneyObservationsResponse(**payload)


@app.get("/journey/reasoning", response_model=JourneyReasoningResponse)
def journey_reasoning(
    min_stage_impressions: int = Query(default=25, ge=1, le=100000),
    stage_drop_off_threshold: float = Query(default=0.55, ge=0.0, le=1.0),
    min_segment_impressions: int = Query(default=12, ge=1, le=100000),
    segment_gap_threshold: float = Query(default=0.12, ge=0.0, le=1.0),
    trend_window: int = Query(default=20, ge=2, le=10000),
    trend_decline_threshold: float = Query(default=0.15, ge=0.0, le=1.0),
    max_hypotheses: int = Query(default=3, ge=1, le=10),
    max_experiments: int = Query(default=3, ge=1, le=10),
) -> JourneyReasoningResponse:
    try:
        payload = state.journey_reasoning(
            min_stage_impressions=min_stage_impressions,
            stage_drop_off_threshold=stage_drop_off_threshold,
            min_segment_impressions=min_segment_impressions,
            segment_gap_threshold=segment_gap_threshold,
            trend_window=trend_window,
            trend_decline_threshold=trend_decline_threshold,
            max_hypotheses=max_hypotheses,
            max_experiments=max_experiments,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JourneyReasoningResponse(**payload)


@app.post("/agent/tick", response_model=AgentTickResponse)
def agent_tick(payload: AgentTickRequest) -> AgentTickResponse:
    try:
        result = state.agent_tick(
            simulate_sessions=payload.simulate_sessions,
            min_stage_impressions=payload.min_stage_impressions,
            stage_drop_off_threshold=payload.stage_drop_off_threshold,
            min_segment_impressions=payload.min_segment_impressions,
            segment_gap_threshold=payload.segment_gap_threshold,
            trend_window=payload.trend_window,
            trend_decline_threshold=payload.trend_decline_threshold,
            max_hypotheses=payload.max_hypotheses,
            max_experiments=payload.max_experiments,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AgentTickResponse(**result)


@app.get("/agent/status", response_model=AgentStatusResponse)
def agent_status() -> AgentStatusResponse:
    return AgentStatusResponse(**state.agent_status())


@app.get("/agent/history", response_model=AgentHistoryResponse)
def agent_history(limit: int = Query(default=80, ge=1, le=300)) -> AgentHistoryResponse:
    return AgentHistoryResponse(**state.agent_history(limit=limit))


@app.get("/metrics", response_model=MetricsResponse)
def metrics() -> MetricsResponse:
    return MetricsResponse(**state.metrics())


@app.get("/segments", response_model=SegmentsResponse)
def segments() -> SegmentsResponse:
    return SegmentsResponse(segments=state.segment_list())


@app.post("/generate-copy", response_model=GenerateCopyResponse)
def generate_copy(payload: GenerateCopyRequest) -> GenerateCopyResponse:
    count = state.generate_copy(
        product=payload.product,
        reviews=payload.reviews,
        segment=payload.segment,
        num_variants=payload.num_variants,
    )
    return GenerateCopyResponse(segment=payload.segment, variants_generated=count)


@app.post("/reset", response_model=ResetResponse)
def reset() -> ResetResponse:
    state.reset()
    return ResetResponse(status="reset")
