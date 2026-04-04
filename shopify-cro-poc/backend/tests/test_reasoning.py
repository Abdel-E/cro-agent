from __future__ import annotations

from app.agent.reasoning import MockJourneyReasoner


def test_mock_reasoner_generates_hypotheses_and_experiments() -> None:
    reasoner = MockJourneyReasoner()
    observations = [
        {
            "kind": "stage_drop_off",
            "severity": "high",
            "stage": "product_page",
            "segment": None,
            "message": "product_page drop-off is 68%",
            "evidence": {"drop_off_rate": 0.68},
        },
        {
            "kind": "segment_underperforming",
            "severity": "medium",
            "stage": "landing",
            "segment": "new_mobile_paid",
            "message": "segment underperforming",
            "evidence": {"performance_gap": 0.13},
        },
    ]
    metrics_summary = {
        "summary": {
            "bottleneck_stage": "product_page",
            "bottleneck_drop_off_rate": 0.68,
        },
        "sessions": {"total": 120, "active": 30, "closed": 90},
        "stages": {},
    }

    payload = reasoner.reason(
        observations=observations,
        metrics_summary=metrics_summary,
        max_hypotheses=2,
        max_experiments=2,
    )

    assert payload["policy"] == "journey_reasoning_v1"
    assert payload["backend"] == "mock"
    assert payload["source_observations"] == 2
    assert len(payload["hypotheses"]) == 2
    assert len(payload["experiments"]) == 2
    assert payload["hypotheses"][0]["hypothesis_id"] == "H-001"
    assert payload["experiments"][0]["hypothesis_id"] == "H-001"


def test_mock_reasoner_handles_empty_observations() -> None:
    reasoner = MockJourneyReasoner()
    payload = reasoner.reason(
        observations=[],
        metrics_summary={"summary": {"bottleneck_stage": None, "bottleneck_drop_off_rate": 0.0}},
        max_hypotheses=3,
        max_experiments=3,
    )

    assert payload["hypotheses"] == []
    assert payload["experiments"] == []
    assert "No high-confidence bottlenecks" in payload["insight"]
