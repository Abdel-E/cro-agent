from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

from app.agent.models import Observation
from app.funnel import JourneyDecisionRecord, utcnow_iso


@dataclass(frozen=True)
class AnalyzerConfig:
    min_stage_impressions: int = 25
    stage_drop_off_threshold: float = 0.55
    min_segment_impressions: int = 12
    segment_gap_threshold: float = 0.12
    trend_window: int = 20
    trend_decline_threshold: float = 0.15

    def __post_init__(self) -> None:
        if self.min_stage_impressions < 1:
            raise ValueError("min_stage_impressions must be >= 1")
        if self.min_segment_impressions < 1:
            raise ValueError("min_segment_impressions must be >= 1")
        if self.trend_window < 2:
            raise ValueError("trend_window must be >= 2")
        for attr in (
            "stage_drop_off_threshold",
            "segment_gap_threshold",
            "trend_decline_threshold",
        ):
            value = getattr(self, attr)
            if not 0 <= value <= 1:
                raise ValueError(f"{attr} must be within [0, 1]")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "min_stage_impressions": self.min_stage_impressions,
            "stage_drop_off_threshold": self.stage_drop_off_threshold,
            "min_segment_impressions": self.min_segment_impressions,
            "segment_gap_threshold": self.segment_gap_threshold,
            "trend_window": self.trend_window,
            "trend_decline_threshold": self.trend_decline_threshold,
        }


class FunnelAnalyzer:
    """Perception-only analyzer for detecting CRO journey bottlenecks."""

    _SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1}

    def __init__(self, config: AnalyzerConfig | None = None) -> None:
        self.config = config or AnalyzerConfig()

    @staticmethod
    def _safe_rate(numerator: int, denominator: int) -> float:
        return numerator / denominator if denominator else 0.0

    def analyze(
        self,
        *,
        metrics: Dict[str, Any],
        decisions: Iterable[JourneyDecisionRecord],
    ) -> Dict[str, Any]:
        observations: List[Observation] = []
        observations.extend(self._detect_stage_drop_offs(metrics))
        observations.extend(self._detect_segment_underperformance(metrics))
        observations.extend(self._detect_declining_trends(decisions))

        observations.sort(
            key=lambda obs: (
                -self._SEVERITY_RANK.get(obs.severity, 0),
                obs.stage,
                obs.kind,
            )
        )

        severity_counts = Counter(obs.severity for obs in observations)
        bottleneck_stage, bottleneck_drop_off_rate = self._find_bottleneck_stage(metrics)

        return {
            "policy": "journey_perception_v1",
            "generated_at": utcnow_iso(),
            "thresholds": self.config.to_dict(),
            "totals": {
                "total": len(observations),
                "high": severity_counts.get("high", 0),
                "medium": severity_counts.get("medium", 0),
                "low": severity_counts.get("low", 0),
            },
            "summary": {
                "bottleneck_stage": bottleneck_stage,
                "bottleneck_drop_off_rate": bottleneck_drop_off_rate,
            },
            "observations": [obs.to_dict() for obs in observations],
        }

    def _find_bottleneck_stage(self, metrics: Dict[str, Any]) -> tuple[str | None, float]:
        stages = metrics.get("stages", {})
        best_stage: str | None = None
        best_drop = -1.0

        for stage, stage_bucket in stages.items():
            impressions = int(stage_bucket.get("impressions", 0))
            drop_offs = int(stage_bucket.get("drop_offs", 0))
            if impressions <= 0:
                continue
            drop_rate = self._safe_rate(drop_offs, impressions)
            if drop_rate > best_drop:
                best_drop = drop_rate
                best_stage = stage

        if best_stage is None:
            return None, 0.0
        return best_stage, best_drop

    def _detect_stage_drop_offs(self, metrics: Dict[str, Any]) -> List[Observation]:
        observations: List[Observation] = []
        for stage, stage_bucket in metrics.get("stages", {}).items():
            impressions = int(stage_bucket.get("impressions", 0))
            conversions = int(stage_bucket.get("conversions", 0))
            drop_offs = int(stage_bucket.get("drop_offs", 0))
            if impressions < self.config.min_stage_impressions:
                continue

            drop_rate = self._safe_rate(drop_offs, impressions)
            if drop_rate < self.config.stage_drop_off_threshold:
                continue

            severity = "high" if drop_rate >= self.config.stage_drop_off_threshold + 0.2 else "medium"
            observations.append(
                Observation(
                    kind="stage_drop_off",
                    severity=severity,
                    stage=stage,
                    message=(
                        f"{stage} drop-off is {drop_rate:.1%} "
                        f"({drop_offs}/{impressions} sessions)."
                    ),
                    evidence={
                        "impressions": impressions,
                        "conversions": conversions,
                        "drop_offs": drop_offs,
                        "conversion_rate": self._safe_rate(conversions, impressions),
                        "drop_off_rate": drop_rate,
                        "threshold": self.config.stage_drop_off_threshold,
                    },
                )
            )

        return observations

    def _detect_segment_underperformance(self, metrics: Dict[str, Any]) -> List[Observation]:
        observations: List[Observation] = []
        for stage, stage_bucket in metrics.get("stages", {}).items():
            stage_impressions = int(stage_bucket.get("impressions", 0))
            stage_conversions = int(stage_bucket.get("conversions", 0))
            if stage_impressions <= 0:
                continue

            stage_rate = self._safe_rate(stage_conversions, stage_impressions)
            segments = stage_bucket.get("segments", {})
            for segment_id, segment_bucket in segments.items():
                seg_impressions = int(segment_bucket.get("impressions", 0))
                seg_conversions = int(segment_bucket.get("conversions", 0))
                if seg_impressions < self.config.min_segment_impressions:
                    continue

                seg_rate = self._safe_rate(seg_conversions, seg_impressions)
                gap = stage_rate - seg_rate
                if gap < self.config.segment_gap_threshold:
                    continue

                severity = "high" if gap >= self.config.segment_gap_threshold * 2 else "medium"
                observations.append(
                    Observation(
                        kind="segment_underperforming",
                        severity=severity,
                        stage=stage,
                        segment=segment_id,
                        message=(
                            f"Segment '{segment_id}' underperforms on {stage}: "
                            f"{seg_rate:.1%} vs stage average {stage_rate:.1%}."
                        ),
                        evidence={
                            "stage_conversion_rate": stage_rate,
                            "segment_conversion_rate": seg_rate,
                            "performance_gap": gap,
                            "segment_impressions": seg_impressions,
                            "threshold": self.config.segment_gap_threshold,
                        },
                    )
                )

        return observations

    def _detect_declining_trends(
        self,
        decisions: Iterable[JourneyDecisionRecord],
    ) -> List[Observation]:
        grouped: Dict[str, List[JourneyDecisionRecord]] = defaultdict(list)
        for record in decisions:
            if record.reward not in (0, 1):
                continue
            stage = record.stage.value if hasattr(record.stage, "value") else str(record.stage)
            grouped[stage].append(record)

        observations: List[Observation] = []
        window = self.config.trend_window
        for stage, records in grouped.items():
            if len(records) < window * 2:
                continue

            records.sort(key=self._decision_sort_key)
            older = records[-2 * window:-window]
            recent = records[-window:]

            older_rate = self._safe_rate(
                sum(int(rec.reward or 0) for rec in older),
                len(older),
            )
            recent_rate = self._safe_rate(
                sum(int(rec.reward or 0) for rec in recent),
                len(recent),
            )
            decline = older_rate - recent_rate
            if decline < self.config.trend_decline_threshold:
                continue

            severity = "high" if decline >= self.config.trend_decline_threshold * 1.5 else "medium"
            observations.append(
                Observation(
                    kind="stage_decline_trend",
                    severity=severity,
                    stage=stage,
                    message=(
                        f"{stage} conversion trend declined from {older_rate:.1%} "
                        f"to {recent_rate:.1%} over the last {window * 2} resolved decisions."
                    ),
                    evidence={
                        "trend_window": window,
                        "older_window_rate": older_rate,
                        "recent_window_rate": recent_rate,
                        "decline": decline,
                        "threshold": self.config.trend_decline_threshold,
                    },
                )
            )

        return observations

    @staticmethod
    def _decision_sort_key(record: JourneyDecisionRecord) -> datetime:
        try:
            return datetime.fromisoformat(record.created_at)
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)
