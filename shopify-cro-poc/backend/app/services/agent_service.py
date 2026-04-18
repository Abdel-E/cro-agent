from __future__ import annotations

from threading import Lock
from typing import Any, Dict

from app.agent.config import build_analyzer_config
from app.agent.orchestrator import AgentOrchestrator
from app.agent.perception import FunnelAnalyzer
from app.agent.reasoning import JourneyReasoner
from app.services.journey_service import JourneyService


class AgentService:
    """Experimental sandbox for observing, reasoning, and launching journey experiments.

    The core PoC remains the `/decide` -> `/feedback` -> `/metrics` loop. This
    service is kept as a secondary orchestration layer for simulated traffic and
    lightweight experiment reporting.
    """

    def __init__(
        self,
        *,
        rng: Any,
        journey: JourneyService,
        reasoner: JourneyReasoner,
    ) -> None:
        self._lock = Lock()
        self._rng = rng
        self._journey = journey
        self._reasoner = reasoner
        self._orchestrator = AgentOrchestrator()

    def reset(self) -> None:
        with self._lock:
            self._orchestrator = AgentOrchestrator()

    def journey_observations(
        self,
        *,
        min_stage_impressions: int | None = None,
        stage_drop_off_threshold: float | None = None,
        min_segment_impressions: int | None = None,
        segment_gap_threshold: float | None = None,
        trend_window: int | None = None,
        trend_decline_threshold: float | None = None,
    ) -> Dict[str, Any]:
        config = build_analyzer_config(
            min_stage_impressions=min_stage_impressions,
            stage_drop_off_threshold=stage_drop_off_threshold,
            min_segment_impressions=min_segment_impressions,
            segment_gap_threshold=segment_gap_threshold,
            trend_window=trend_window,
            trend_decline_threshold=trend_decline_threshold,
        )
        analyzer = FunnelAnalyzer(config)

        metrics, decisions = self._journey.metrics_and_decisions()
        return analyzer.analyze(metrics=metrics, decisions=decisions)

    def journey_reasoning(
        self,
        *,
        min_stage_impressions: int | None = None,
        stage_drop_off_threshold: float | None = None,
        min_segment_impressions: int | None = None,
        segment_gap_threshold: float | None = None,
        trend_window: int | None = None,
        trend_decline_threshold: float | None = None,
        max_hypotheses: int = 3,
        max_experiments: int = 3,
    ) -> Dict[str, Any]:
        if max_hypotheses < 1:
            raise ValueError("max_hypotheses must be >= 1")
        if max_experiments < 1:
            raise ValueError("max_experiments must be >= 1")

        config = build_analyzer_config(
            min_stage_impressions=min_stage_impressions,
            stage_drop_off_threshold=stage_drop_off_threshold,
            min_segment_impressions=min_segment_impressions,
            segment_gap_threshold=segment_gap_threshold,
            trend_window=trend_window,
            trend_decline_threshold=trend_decline_threshold,
        )
        analyzer = FunnelAnalyzer(config)

        metrics, decisions = self._journey.metrics_and_decisions()
        observations_payload = analyzer.analyze(metrics=metrics, decisions=decisions)

        reasoning = self._reasoner.reason(
            observations=list(observations_payload.get("observations", [])),
            metrics_summary={
                "summary": observations_payload.get("summary", {}),
                "sessions": metrics.get("sessions", {}),
                "stages": {
                    stage: {
                        "impressions": bucket.get("impressions", 0),
                        "conversions": bucket.get("conversions", 0),
                        "drop_offs": bucket.get("drop_offs", 0),
                        "conversion_rate": bucket.get("conversion_rate", 0.0),
                    }
                    for stage, bucket in metrics.get("stages", {}).items()
                },
            },
            max_hypotheses=max_hypotheses,
            max_experiments=max_experiments,
        )

        reasoning["observation_summary"] = observations_payload.get("summary", {})
        reasoning["thresholds"] = observations_payload.get("thresholds", config.to_dict())
        return reasoning

    def _sample_demo_context(self) -> Dict[str, Any]:
        profiles = [
            {"device_type": "mobile", "traffic_source": "meta", "is_returning": False},
            {"device_type": "mobile", "traffic_source": "google", "is_returning": False},
            {"device_type": "desktop", "traffic_source": "direct", "is_returning": False},
            {"device_type": "desktop", "traffic_source": "direct", "is_returning": True},
        ]
        return dict(self._rng.choice(profiles))

    @staticmethod
    def _landing_advance_probability(variant_id: str, segment: str) -> float:
        by_variant = {"A": 0.58, "B": 0.52, "C": 0.47}
        bonus = 0.0
        if segment == "returning_any":
            bonus += 0.07
        if segment == "new_mobile_paid":
            bonus -= 0.04
        return max(0.05, min(0.95, by_variant.get(variant_id, 0.5) + bonus))

    @staticmethod
    def _product_convert_probability(variant_id: str, segment: str) -> float:
        by_variant = {"A": 0.24, "B": 0.36, "C": 0.29}
        bonus = 0.0
        if segment == "returning_any":
            bonus += 0.06
        if segment == "new_mobile_paid":
            bonus -= 0.03
        return max(0.03, min(0.85, by_variant.get(variant_id, 0.25) + bonus))

    def simulate_journey_traffic(self, sessions: int = 25) -> Dict[str, int]:
        if sessions < 0:
            raise ValueError("sessions must be >= 0")

        summary = {
            "sessions": sessions,
            "landing_drop_offs": 0,
            "landing_advances": 0,
            "product_drop_offs": 0,
            "product_conversions": 0,
        }

        for _ in range(sessions):
            context = self._sample_demo_context()
            landing = self._journey.journey_decide(stage="landing", context=context)
            landing_p = self._landing_advance_probability(
                variant_id=landing["variant_id"],
                segment=landing["segment"],
            )

            if self._rng.random() < landing_p:
                summary["landing_advances"] += 1
                self._journey.journey_event(
                    event_type="advance",
                    decision_id=landing["decision_id"],
                    to_stage="product_page",
                )

                product = self._journey.journey_decide(
                    stage="product_page",
                    continue_from_decision_id=landing["decision_id"],
                )
                product_p = self._product_convert_probability(
                    variant_id=product["variant_id"],
                    segment=product["segment"],
                )

                if self._rng.random() < product_p:
                    summary["product_conversions"] += 1
                    self._journey.journey_event(
                        event_type="convert",
                        decision_id=product["decision_id"],
                    )
                else:
                    summary["product_drop_offs"] += 1
                    self._journey.journey_event(
                        event_type="drop_off",
                        decision_id=product["decision_id"],
                    )
            else:
                summary["landing_drop_offs"] += 1
                self._journey.journey_event(
                    event_type="drop_off",
                    decision_id=landing["decision_id"],
                )

        return summary

    def agent_tick(
        self,
        *,
        simulate_sessions: int = 0,
        min_stage_impressions: int | None = None,
        stage_drop_off_threshold: float | None = None,
        min_segment_impressions: int | None = None,
        segment_gap_threshold: float | None = None,
        trend_window: int | None = None,
        trend_decline_threshold: float | None = None,
        max_hypotheses: int = 3,
        max_experiments: int = 3,
    ) -> Dict[str, Any]:
        simulation = None
        if simulate_sessions > 0:
            simulation = self.simulate_journey_traffic(simulate_sessions)

        reasoning_payload = self.journey_reasoning(
            min_stage_impressions=min_stage_impressions,
            stage_drop_off_threshold=stage_drop_off_threshold,
            min_segment_impressions=min_segment_impressions,
            segment_gap_threshold=segment_gap_threshold,
            trend_window=trend_window,
            trend_decline_threshold=trend_decline_threshold,
            max_hypotheses=max_hypotheses,
            max_experiments=max_experiments,
        )

        with self._lock:
            metrics = self._journey.metrics()
            cycle = self._orchestrator.run_cycle(
                reasoning_payload=reasoning_payload,
                journey_metrics=metrics,
            )
            self._journey.apply_experiment_templates(cycle.get("launched", []))
            cycle_status = cycle.get("status", {})
            cycle_status["journey_sessions"] = self._journey.session_counts()
            cycle_status["journey_metrics"] = metrics
            cycle["status"] = cycle_status

        cycle["simulation"] = simulation or {
            "sessions": 0,
            "landing_drop_offs": 0,
            "landing_advances": 0,
            "product_drop_offs": 0,
            "product_conversions": 0,
        }
        return cycle

    def agent_status(self) -> Dict[str, Any]:
        with self._lock:
            status = self._orchestrator.status()
            status["journey_sessions"] = self._journey.session_counts()
            status["journey_metrics"] = self._journey.metrics()
            return status

    def agent_history(self, limit: int = 100) -> Dict[str, Any]:
        with self._lock:
            return {"events": self._orchestrator.history(limit=limit)}

