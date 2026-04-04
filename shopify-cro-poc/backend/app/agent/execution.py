from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from app.funnel import utcnow_iso


@dataclass
class AgentExperiment:
    experiment_id: str
    hypothesis_id: str
    stage: str
    objective_metric: str
    allocation: Dict[str, float]
    variants: List[Dict[str, str]]
    success_criterion: str
    status: str = "active"
    launched_at: str = field(default_factory=utcnow_iso)
    completed_at: str | None = None
    start_impressions: int = 0
    minimum_impressions: int = 40
    winner_variant: str | None = None
    winner_rate: float | None = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "hypothesis_id": self.hypothesis_id,
            "stage": self.stage,
            "objective_metric": self.objective_metric,
            "allocation": dict(self.allocation),
            "variants": list(self.variants),
            "success_criterion": self.success_criterion,
            "status": self.status,
            "launched_at": self.launched_at,
            "completed_at": self.completed_at,
            "start_impressions": self.start_impressions,
            "minimum_impressions": self.minimum_impressions,
            "winner_variant": self.winner_variant,
            "winner_rate": self.winner_rate,
        }


class ExperimentExecutor:
    def __init__(self, minimum_eval_impressions: int = 40) -> None:
        self.minimum_eval_impressions = minimum_eval_impressions

    @staticmethod
    def _stage_impressions(metrics: Dict[str, Any], stage: str) -> int:
        return int(metrics.get("stages", {}).get(stage, {}).get("impressions", 0))

    @staticmethod
    def _variant_rates(metrics: Dict[str, Any], stage: str) -> Dict[str, float]:
        variants = metrics.get("stages", {}).get(stage, {}).get("variants", {})
        return {
            variant_id: float(payload.get("conversion_rate", 0.0))
            for variant_id, payload in variants.items()
        }

    @staticmethod
    def _experiment_key(experiment: Dict[str, Any]) -> str:
        stage = str(experiment.get("stage", ""))
        hypothesis = str(experiment.get("hypothesis_id", ""))
        return f"{stage}|{hypothesis}"

    def launch(
        self,
        *,
        reasoning_payload: Dict[str, Any],
        journey_metrics: Dict[str, Any],
        active_experiments: Dict[str, AgentExperiment],
        launched_keys: set[str],
    ) -> List[AgentExperiment]:
        launched: List[AgentExperiment] = []
        for candidate in reasoning_payload.get("experiments", []):
            if not isinstance(candidate, dict):
                continue

            key = self._experiment_key(candidate)
            if key in launched_keys:
                continue

            stage = str(candidate.get("stage", "landing"))
            experiment = AgentExperiment(
                experiment_id=str(candidate.get("experiment_id") or f"EXP-{len(launched_keys)+1:03d}"),
                hypothesis_id=str(candidate.get("hypothesis_id") or "H-000"),
                stage=stage,
                objective_metric=str(candidate.get("objective_metric") or "stage_conversion_rate"),
                allocation={
                    k: float(v)
                    for k, v in dict(candidate.get("allocation") or {}).items()
                }
                or {"control": 0.34, "variant_b": 0.33, "variant_c": 0.33},
                variants=list(candidate.get("variants") or []),
                success_criterion=str(
                    candidate.get("success_criterion")
                    or "Promote winner with sustained lift and adequate sample size."
                ),
                start_impressions=self._stage_impressions(journey_metrics, stage),
                minimum_impressions=self.minimum_eval_impressions,
            )

            active_experiments[experiment.experiment_id] = experiment
            launched_keys.add(key)
            launched.append(experiment)

        return launched

    def evaluate(
        self,
        *,
        journey_metrics: Dict[str, Any],
        active_experiments: Dict[str, AgentExperiment],
    ) -> List[AgentExperiment]:
        graduated: List[AgentExperiment] = []
        to_remove: List[str] = []

        for experiment_id, experiment in active_experiments.items():
            current_impressions = self._stage_impressions(journey_metrics, experiment.stage)
            delta = current_impressions - experiment.start_impressions
            if delta < experiment.minimum_impressions:
                continue

            rates = self._variant_rates(journey_metrics, experiment.stage)
            winner_variant = None
            winner_rate = -1.0
            for variant_id in ("A", "B", "C"):
                score = float(rates.get(variant_id, 0.0))
                if score > winner_rate:
                    winner_rate = score
                    winner_variant = variant_id

            experiment.status = "graduated"
            experiment.completed_at = utcnow_iso()
            experiment.winner_variant = winner_variant
            experiment.winner_rate = max(winner_rate, 0.0)

            graduated.append(experiment)
            to_remove.append(experiment_id)

        for experiment_id in to_remove:
            active_experiments.pop(experiment_id, None)

        return graduated
