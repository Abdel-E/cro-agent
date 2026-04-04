from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# /decide
# ---------------------------------------------------------------------------

class DecideRequest(BaseModel):
    surface_id: str = Field(default="hero_banner", min_length=1)
    context: Dict[str, Any] = Field(default_factory=dict)
    visitor_id: Optional[str] = None
    device_type: Optional[str] = None
    traffic_source: Optional[str] = None
    is_returning: bool = False
    segment_hint: Optional[str] = None


class VariantContentResponse(BaseModel):
    headline: str
    subtitle: str
    cta_text: str
    trust_signals: List[str] = Field(default_factory=list)
    style_class: str = "variant-a"


class DecideResponse(BaseModel):
    decision_id: str
    surface_id: str
    variant_id: str
    segment: str
    probability: float
    policy: str = "contextual_thompson_sampling"
    content: VariantContentResponse


# ---------------------------------------------------------------------------
# /feedback
# ---------------------------------------------------------------------------

class FeedbackRequest(BaseModel):
    decision_id: str = Field(min_length=1)
    variant_id: str
    reward: int = Field(ge=0, le=1)


class FeedbackResponse(BaseModel):
    accepted: bool
    idempotent: bool
    decision_id: str
    variant_id: str
    reward: int


# ---------------------------------------------------------------------------
# /journey/decide
# ---------------------------------------------------------------------------

class JourneyDecideRequest(BaseModel):
    stage: str = Field(default="landing", min_length=1)
    session_id: Optional[str] = None
    continue_from_decision_id: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)
    device_type: Optional[str] = None
    traffic_source: Optional[str] = None
    is_returning: Optional[bool] = None
    segment_hint: Optional[str] = None


class JourneyDecideResponse(BaseModel):
    session_id: str
    decision_id: str
    stage: str
    variant_id: str
    segment: str
    probability: float
    policy: str = "contextual_thompson_sampling_journey"
    content: VariantContentResponse


# ---------------------------------------------------------------------------
# /journey/event
# ---------------------------------------------------------------------------

JourneyEventType = Literal["advance", "drop_off", "convert"]


class JourneyEventRequest(BaseModel):
    decision_id: Optional[str] = None
    session_id: Optional[str] = None
    from_stage: Optional[str] = None
    event_type: JourneyEventType = "advance"
    to_stage: Optional[str] = None


class JourneyEventResponse(BaseModel):
    accepted: bool
    idempotent: bool
    event_id: Optional[str] = None
    decision_id: str
    session_id: str
    event_type: JourneyEventType
    from_stage: str
    to_stage: Optional[str] = None
    reward: int = Field(ge=0, le=1)


# ---------------------------------------------------------------------------
# /metrics
# ---------------------------------------------------------------------------

class VariantMetrics(BaseModel):
    impressions: int
    successes: int
    failures: int
    ctr: float


class HistoryPoint(BaseModel):
    step: int
    variant_id: str
    reward: int
    segment: str = "default"


class SegmentVariantMetrics(BaseModel):
    variants: Dict[str, VariantMetrics]
    totals: VariantMetrics


class MetricsResponse(BaseModel):
    surface_id: str
    policy: str
    variants: Dict[str, VariantMetrics]
    totals: VariantMetrics
    segments: Dict[str, SegmentVariantMetrics]
    history: List[HistoryPoint]


# ---------------------------------------------------------------------------
# /journey/metrics
# ---------------------------------------------------------------------------

class JourneyBreakdown(BaseModel):
    impressions: int
    conversions: int
    drop_offs: int
    conversion_rate: float


class JourneyStageMetrics(BaseModel):
    impressions: int
    conversions: int
    drop_offs: int
    conversion_rate: float
    variants: Dict[str, JourneyBreakdown]
    segments: Dict[str, JourneyBreakdown]
    transitions: Dict[str, int]


class JourneySessionMetrics(BaseModel):
    total: int
    active: int
    closed: int


class JourneyPathMetrics(BaseModel):
    path: str
    sessions: int


class JourneyMetricsResponse(BaseModel):
    policy: str
    stages: Dict[str, JourneyStageMetrics]
    sessions: JourneySessionMetrics
    top_paths: List[JourneyPathMetrics]


# ---------------------------------------------------------------------------
# /journey/observations
# ---------------------------------------------------------------------------

class JourneyObservationThresholds(BaseModel):
    min_stage_impressions: int
    stage_drop_off_threshold: float
    min_segment_impressions: int
    segment_gap_threshold: float
    trend_window: int
    trend_decline_threshold: float


class JourneyObservationTotals(BaseModel):
    total: int
    high: int
    medium: int
    low: int


class JourneyObservationSummary(BaseModel):
    bottleneck_stage: Optional[str] = None
    bottleneck_drop_off_rate: float


class JourneyObservation(BaseModel):
    kind: str
    severity: str
    stage: str
    segment: Optional[str] = None
    message: str
    evidence: Dict[str, Any] = Field(default_factory=dict)
    observed_at: str


class JourneyObservationsResponse(BaseModel):
    policy: str
    generated_at: str
    thresholds: JourneyObservationThresholds
    totals: JourneyObservationTotals
    summary: JourneyObservationSummary
    observations: List[JourneyObservation]


# ---------------------------------------------------------------------------
# /journey/reasoning
# ---------------------------------------------------------------------------

class JourneyReasoningHypothesis(BaseModel):
    hypothesis_id: str
    stage: str
    segment: Optional[str] = None
    confidence: float
    rationale: str
    proposed_angle: str
    expected_effect: str


class JourneyReasoningVariant(BaseModel):
    variant_id: str
    message_angle: str
    description: str


class JourneyReasoningExperiment(BaseModel):
    experiment_id: str
    hypothesis_id: str
    stage: str
    objective_metric: str
    allocation: Dict[str, float]
    success_criterion: str
    variants: List[JourneyReasoningVariant]


class JourneyReasoningResponse(BaseModel):
    policy: str
    backend: str
    generated_at: str
    source_observations: int
    thresholds: JourneyObservationThresholds
    observation_summary: JourneyObservationSummary
    insight: str
    hypotheses: List[JourneyReasoningHypothesis]
    experiments: List[JourneyReasoningExperiment]


# ---------------------------------------------------------------------------
# /agent/*
# ---------------------------------------------------------------------------

class AgentTickRequest(BaseModel):
    simulate_sessions: int = Field(default=0, ge=0, le=2000)
    min_stage_impressions: int = Field(default=25, ge=1, le=100000)
    stage_drop_off_threshold: float = Field(default=0.55, ge=0.0, le=1.0)
    min_segment_impressions: int = Field(default=12, ge=1, le=100000)
    segment_gap_threshold: float = Field(default=0.12, ge=0.0, le=1.0)
    trend_window: int = Field(default=20, ge=2, le=10000)
    trend_decline_threshold: float = Field(default=0.15, ge=0.0, le=1.0)
    max_hypotheses: int = Field(default=3, ge=1, le=10)
    max_experiments: int = Field(default=3, ge=1, le=10)


class AgentExperiment(BaseModel):
    experiment_id: str
    hypothesis_id: str
    stage: str
    objective_metric: str
    allocation: Dict[str, float]
    variants: List[JourneyReasoningVariant]
    success_criterion: str
    status: str
    launched_at: str
    completed_at: Optional[str] = None
    start_impressions: int
    minimum_impressions: int
    winner_variant: Optional[str] = None
    winner_rate: Optional[float] = None


class AgentLoopEvent(BaseModel):
    event_id: str
    tick: int
    event_type: str
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)
    created_at: str


class AgentStatusResponse(BaseModel):
    tick_count: int
    last_tick_at: Optional[str] = None
    latest_insight: str
    latest_observations: int
    active_experiments: List[AgentExperiment]
    completed_experiments: List[AgentExperiment]
    history_size: int
    journey_sessions: Dict[str, int]
    journey_metrics: JourneyMetricsResponse


class AgentTickResponse(BaseModel):
    tick: int
    generated_at: str
    observations: int
    insight: str
    launched: List[AgentExperiment]
    graduated: List[AgentExperiment]
    events: List[AgentLoopEvent]
    simulation: Dict[str, int]
    status: AgentStatusResponse


class AgentHistoryResponse(BaseModel):
    events: List[AgentLoopEvent]


# ---------------------------------------------------------------------------
# /segments
# ---------------------------------------------------------------------------

class SegmentInfo(BaseModel):
    segment_id: str
    description: str
    total_impressions: int


class SegmentsResponse(BaseModel):
    segments: List[SegmentInfo]


# ---------------------------------------------------------------------------
# /generate-copy
# ---------------------------------------------------------------------------

class GenerateCopyRequest(BaseModel):
    product: str = Field(min_length=1)
    reviews: List[str] = Field(default_factory=list)
    segment: str = "default"
    num_variants: int = Field(default=3, ge=1, le=10)


class GenerateCopyResponse(BaseModel):
    segment: str
    variants_generated: int


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

class ResetResponse(BaseModel):
    status: str


class HealthResponse(BaseModel):
    status: str
