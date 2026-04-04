from __future__ import annotations

from app.agent.execution import AgentExperiment, ExperimentExecutor


def _metrics(stage_impressions: int, a_rate: float, b_rate: float, c_rate: float) -> dict:
    return {
        "stages": {
            "product_page": {
                "impressions": stage_impressions,
                "conversions": 0,
                "drop_offs": 0,
                "conversion_rate": 0.0,
                "variants": {
                    "A": {"conversion_rate": a_rate},
                    "B": {"conversion_rate": b_rate},
                    "C": {"conversion_rate": c_rate},
                },
            }
        }
    }


def test_executor_launches_and_deduplicates() -> None:
    executor = ExperimentExecutor(minimum_eval_impressions=20)
    active: dict[str, AgentExperiment] = {}
    launched_keys: set[str] = set()
    reasoning = {
        "experiments": [
            {
                "experiment_id": "EXP-001",
                "hypothesis_id": "H-001",
                "stage": "product_page",
                "objective_metric": "product_page_conversion_rate",
                "allocation": {"control": 0.34, "variant_b": 0.33, "variant_c": 0.33},
                "success_criterion": "criterion",
                "variants": [
                    {"variant_id": "control", "message_angle": "current", "description": "baseline"},
                ],
            }
        ]
    }

    launched_first = executor.launch(
        reasoning_payload=reasoning,
        journey_metrics=_metrics(100, 0.2, 0.3, 0.25),
        active_experiments=active,
        launched_keys=launched_keys,
    )
    launched_second = executor.launch(
        reasoning_payload=reasoning,
        journey_metrics=_metrics(105, 0.2, 0.3, 0.25),
        active_experiments=active,
        launched_keys=launched_keys,
    )

    assert len(launched_first) == 1
    assert len(launched_second) == 0
    assert len(active) == 1


def test_executor_graduates_after_minimum_impressions() -> None:
    executor = ExperimentExecutor(minimum_eval_impressions=20)
    active = {
        "EXP-001": AgentExperiment(
            experiment_id="EXP-001",
            hypothesis_id="H-001",
            stage="product_page",
            objective_metric="product_page_conversion_rate",
            allocation={"control": 0.34, "variant_b": 0.33, "variant_c": 0.33},
            variants=[],
            success_criterion="criterion",
            start_impressions=100,
            minimum_impressions=20,
        )
    }

    graduated = executor.evaluate(
        journey_metrics=_metrics(130, 0.22, 0.41, 0.33),
        active_experiments=active,
    )

    assert len(graduated) == 1
    assert graduated[0].status == "graduated"
    assert graduated[0].winner_variant == "B"
    assert graduated[0].winner_rate == 0.41
    assert "EXP-001" not in active
