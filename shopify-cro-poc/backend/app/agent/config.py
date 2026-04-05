from __future__ import annotations

from dataclasses import dataclass

from app.agent.perception import AnalyzerConfig


@dataclass(frozen=True)
class AgentTuningDefaults:
    min_stage_impressions: int = 25
    stage_drop_off_threshold: float = 0.55
    min_segment_impressions: int = 12
    segment_gap_threshold: float = 0.12
    trend_window: int = 20
    trend_decline_threshold: float = 0.15
    max_hypotheses: int = 3
    max_experiments: int = 3


DEFAULT_AGENT_TUNING = AgentTuningDefaults()


def build_analyzer_config(
    *,
    min_stage_impressions: int | None = None,
    stage_drop_off_threshold: float | None = None,
    min_segment_impressions: int | None = None,
    segment_gap_threshold: float | None = None,
    trend_window: int | None = None,
    trend_decline_threshold: float | None = None,
) -> AnalyzerConfig:
    defaults = DEFAULT_AGENT_TUNING
    return AnalyzerConfig(
        min_stage_impressions=(
            defaults.min_stage_impressions
            if min_stage_impressions is None
            else min_stage_impressions
        ),
        stage_drop_off_threshold=(
            defaults.stage_drop_off_threshold
            if stage_drop_off_threshold is None
            else stage_drop_off_threshold
        ),
        min_segment_impressions=(
            defaults.min_segment_impressions
            if min_segment_impressions is None
            else min_segment_impressions
        ),
        segment_gap_threshold=(
            defaults.segment_gap_threshold
            if segment_gap_threshold is None
            else segment_gap_threshold
        ),
        trend_window=(
            defaults.trend_window
            if trend_window is None
            else trend_window
        ),
        trend_decline_threshold=(
            defaults.trend_decline_threshold
            if trend_decline_threshold is None
            else trend_decline_threshold
        ),
    )
