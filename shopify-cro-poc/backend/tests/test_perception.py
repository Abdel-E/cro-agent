from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.agent.perception import AnalyzerConfig, FunnelAnalyzer
from app.funnel import FunnelSurface, JourneyDecisionRecord


def test_detects_stage_and_segment_bottlenecks() -> None:
    metrics = {
        "stages": {
            "landing": {
                "impressions": 100,
                "conversions": 40,
                "drop_offs": 60,
                "conversion_rate": 0.4,
                "variants": {},
                "segments": {
                    "new_mobile_paid": {
                        "impressions": 30,
                        "conversions": 6,
                        "drop_offs": 24,
                        "conversion_rate": 0.2,
                    },
                    "default": {
                        "impressions": 70,
                        "conversions": 34,
                        "drop_offs": 36,
                        "conversion_rate": 34 / 70,
                    },
                },
                "transitions": {"product_page": 40},
            },
        },
    }

    analyzer = FunnelAnalyzer(
        AnalyzerConfig(
            min_stage_impressions=10,
            stage_drop_off_threshold=0.5,
            min_segment_impressions=10,
            segment_gap_threshold=0.1,
            trend_window=5,
            trend_decline_threshold=0.2,
        )
    )

    result = analyzer.analyze(metrics=metrics, decisions=[])
    kinds = {obs["kind"] for obs in result["observations"]}

    assert "stage_drop_off" in kinds
    assert "segment_underperforming" in kinds
    assert result["summary"]["bottleneck_stage"] == "landing"


def test_detects_declining_stage_trend() -> None:
    metrics = {
        "stages": {
            "landing": {
                "impressions": 0,
                "conversions": 0,
                "drop_offs": 0,
                "conversion_rate": 0.0,
                "variants": {},
                "segments": {},
                "transitions": {},
            },
        },
    }

    decisions = []
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(20):
        reward = 1 if i < 10 else 0
        decisions.append(
            JourneyDecisionRecord(
                decision_id=f"d-{i}",
                session_id="s1",
                stage=FunnelSurface.LANDING,
                segment="default",
                variant_id="A",
                probability=0.5,
                reward=reward,
                created_at=(base_time + timedelta(seconds=i)).isoformat(),
            )
        )

    analyzer = FunnelAnalyzer(
        AnalyzerConfig(
            min_stage_impressions=1000,
            stage_drop_off_threshold=0.95,
            min_segment_impressions=1000,
            segment_gap_threshold=0.9,
            trend_window=10,
            trend_decline_threshold=0.4,
        )
    )
    result = analyzer.analyze(metrics=metrics, decisions=decisions)
    kinds = [obs["kind"] for obs in result["observations"]]

    assert kinds == ["stage_decline_trend"]
    assert result["totals"]["total"] == 1
