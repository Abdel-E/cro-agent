from __future__ import annotations

import random
from typing import Any, Dict, List

from app.agent.reasoning import create_reasoner
from app.content import VARIANTS
from app.funnel import FunnelSurface
from app.services.agent_service import AgentService
from app.services.decision_service import (
    ConflictingFeedbackError,
    DecisionService,
    UnknownDecisionError,
    VariantMismatchError,
)
from app.services.journey_service import (
    ConflictingJourneyOutcomeError,
    InvalidJourneyEventError,
    JourneyService,
    UnknownSessionError,
)


class JourneyState:
    """Application state orchestrating core bandit, journey, and agent subsystems."""

    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)
        self.surface_id = "hero_banner"
        self.variants = list(VARIANTS)

        self._decision = DecisionService(rng=self._rng, surface_id=self.surface_id)
        self._journey = JourneyService(
            rng=self._rng,
            variants=self.variants,
            landing_content_getter=self._decision.content_for,
        )
        self._agent = AgentService(
            rng=self._rng,
            journey=self._journey,
            reasoner=create_reasoner(),
        )
        self.journey_stages = [stage.value for stage in FunnelSurface.ordered()]
        self.reset()

    def reset(self) -> None:
        self._decision.reset()
        self._journey.reset()
        self._agent.reset()
        self.journey_stages = [stage.value for stage in FunnelSurface.ordered()]

    # -- core bandit -------------------------------------------------------

    def decide(self, surface_id: str, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        return self._decision.decide(surface_id, context)

    def feedback(
        self, decision_id: str, variant_id: str, reward: int,
    ) -> Dict[str, Any]:
        return self._decision.feedback(decision_id, variant_id, reward)

    def metrics(self) -> Dict[str, Any]:
        return self._decision.metrics()

    def segment_list(self) -> List[Dict[str, Any]]:
        return self._decision.segment_list()

    def generate_copy(
        self,
        product: str,
        reviews: List[str],
        segment: str,
        num_variants: int = 3,
    ) -> int:
        return self._decision.generate_copy(
            product=product,
            reviews=reviews,
            segment=segment,
            num_variants=num_variants,
        )

    # -- journey -----------------------------------------------------------

    def journey_decide(
        self,
        stage: str,
        context: Dict[str, Any] | None = None,
        session_id: str | None = None,
        continue_from_decision_id: str | None = None,
    ) -> Dict[str, Any]:
        return self._journey.journey_decide(
            stage=stage,
            context=context,
            session_id=session_id,
            continue_from_decision_id=continue_from_decision_id,
        )

    def journey_event(
        self,
        event_type: str,
        *,
        decision_id: str | None = None,
        session_id: str | None = None,
        from_stage: str | None = None,
        to_stage: str | None = None,
    ) -> Dict[str, Any]:
        return self._journey.journey_event(
            event_type=event_type,
            decision_id=decision_id,
            session_id=session_id,
            from_stage=from_stage,
            to_stage=to_stage,
        )

    def journey_metrics(self) -> Dict[str, Any]:
        return self._journey.metrics()

    # -- agent/perception/reasoning ---------------------------------------

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
        return self._agent.journey_observations(
            min_stage_impressions=min_stage_impressions,
            stage_drop_off_threshold=stage_drop_off_threshold,
            min_segment_impressions=min_segment_impressions,
            segment_gap_threshold=segment_gap_threshold,
            trend_window=trend_window,
            trend_decline_threshold=trend_decline_threshold,
        )

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
        return self._agent.journey_reasoning(
            min_stage_impressions=min_stage_impressions,
            stage_drop_off_threshold=stage_drop_off_threshold,
            min_segment_impressions=min_segment_impressions,
            segment_gap_threshold=segment_gap_threshold,
            trend_window=trend_window,
            trend_decline_threshold=trend_decline_threshold,
            max_hypotheses=max_hypotheses,
            max_experiments=max_experiments,
        )

    def simulate_journey_traffic(self, sessions: int = 25) -> Dict[str, int]:
        return self._agent.simulate_journey_traffic(sessions=sessions)

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
        return self._agent.agent_tick(
            simulate_sessions=simulate_sessions,
            min_stage_impressions=min_stage_impressions,
            stage_drop_off_threshold=stage_drop_off_threshold,
            min_segment_impressions=min_segment_impressions,
            segment_gap_threshold=segment_gap_threshold,
            trend_window=trend_window,
            trend_decline_threshold=trend_decline_threshold,
            max_hypotheses=max_hypotheses,
            max_experiments=max_experiments,
        )

    def agent_status(self) -> Dict[str, Any]:
        return self._agent.agent_status()

    def agent_history(self, limit: int = 100) -> Dict[str, Any]:
        return self._agent.agent_history(limit=limit)


# Backward-compatible alias used by existing imports/tests.
BanditState = JourneyState

