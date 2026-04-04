from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List
from uuid import uuid4

from app.agent.execution import AgentExperiment, ExperimentExecutor
from app.funnel import utcnow_iso


@dataclass
class AgentLoopEvent:
    event_id: str
    tick: int
    event_type: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utcnow_iso)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "tick": self.tick,
            "event_type": self.event_type,
            "message": self.message,
            "details": dict(self.details),
            "created_at": self.created_at,
        }


class AgentOrchestrator:
    def __init__(self, executor: ExperimentExecutor | None = None) -> None:
        self._executor = executor or ExperimentExecutor()
        self.tick_count = 0
        self.last_tick_at: str | None = None
        self.latest_insight = ""
        self.latest_observations = 0
        self._history: List[AgentLoopEvent] = []
        self._active_experiments: Dict[str, AgentExperiment] = {}
        self._completed_experiments: List[AgentExperiment] = []
        self._launched_keys: set[str] = set()

    def _add_event(
        self,
        *,
        tick: int,
        event_type: str,
        message: str,
        details: Dict[str, Any] | None = None,
    ) -> None:
        self._history.append(
            AgentLoopEvent(
                event_id=str(uuid4()),
                tick=tick,
                event_type=event_type,
                message=message,
                details=details or {},
            )
        )
        self._history = self._history[-300:]

    def run_cycle(
        self,
        *,
        reasoning_payload: Dict[str, Any],
        journey_metrics: Dict[str, Any],
    ) -> Dict[str, Any]:
        self.tick_count += 1
        tick = self.tick_count

        observation_count = int(reasoning_payload.get("source_observations", 0))
        self.latest_observations = observation_count
        self.latest_insight = str(reasoning_payload.get("insight", "")).strip()
        self.last_tick_at = utcnow_iso()

        self._add_event(
            tick=tick,
            event_type="observe",
            message=f"Observed {observation_count} bottleneck signals.",
            details={
                "observations": observation_count,
                "bottleneck_stage": reasoning_payload.get("observation_summary", {}).get("bottleneck_stage"),
            },
        )
        self._add_event(
            tick=tick,
            event_type="reason",
            message=(
                self.latest_insight
                or "Reasoning generated no actionable insight for this cycle."
            ),
            details={
                "hypotheses": len(reasoning_payload.get("hypotheses", [])),
                "experiments": len(reasoning_payload.get("experiments", [])),
            },
        )

        launched = self._executor.launch(
            reasoning_payload=reasoning_payload,
            journey_metrics=journey_metrics,
            active_experiments=self._active_experiments,
            launched_keys=self._launched_keys,
        )
        for experiment in launched:
            self._add_event(
                tick=tick,
                event_type="launch",
                message=(
                    f"Launched {experiment.experiment_id} on {experiment.stage} "
                    f"for hypothesis {experiment.hypothesis_id}."
                ),
                details={
                    "experiment_id": experiment.experiment_id,
                    "stage": experiment.stage,
                    "hypothesis_id": experiment.hypothesis_id,
                },
            )

        graduated = self._executor.evaluate(
            journey_metrics=journey_metrics,
            active_experiments=self._active_experiments,
        )
        for experiment in graduated:
            self._completed_experiments.append(experiment)
            self._add_event(
                tick=tick,
                event_type="graduate",
                message=(
                    f"Graduated {experiment.experiment_id}; winner {experiment.winner_variant} "
                    f"at {experiment.winner_rate or 0.0:.1%} conversion."
                ),
                details={
                    "experiment_id": experiment.experiment_id,
                    "winner_variant": experiment.winner_variant,
                    "winner_rate": experiment.winner_rate,
                },
            )

        if not launched and not graduated:
            self._add_event(
                tick=tick,
                event_type="noop",
                message="No new launches or graduations in this cycle.",
            )

        return {
            "tick": tick,
            "generated_at": self.last_tick_at,
            "observations": observation_count,
            "insight": self.latest_insight,
            "launched": [exp.to_dict() for exp in launched],
            "graduated": [exp.to_dict() for exp in graduated],
            "status": self.status(),
            "events": self.history(limit=6),
        }

    def status(self) -> Dict[str, Any]:
        return {
            "tick_count": self.tick_count,
            "last_tick_at": self.last_tick_at,
            "latest_insight": self.latest_insight,
            "latest_observations": self.latest_observations,
            "active_experiments": [
                exp.to_dict() for exp in self._active_experiments.values()
            ],
            "completed_experiments": [
                exp.to_dict() for exp in self._completed_experiments[-20:]
            ],
            "history_size": len(self._history),
        }

    def history(self, limit: int = 100) -> List[Dict[str, Any]]:
        if limit < 1:
            return []
        return [event.to_dict() for event in self._history[-limit:]][::-1]
