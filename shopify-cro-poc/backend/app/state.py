from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass
from threading import Lock
from typing import Any, Dict, List
from uuid import uuid4

from app.agent.orchestrator import AgentOrchestrator
from app.agent.perception import AnalyzerConfig, FunnelAnalyzer
from app.agent.reasoning import JourneyReasoner, create_reasoner
from app.bandit import ArmStats, SegmentedThompsonSampler
from app.content import VARIANTS, ContentRegistry, VariantContent, build_default_registry
from app.copy_generator import CopyGenerator, create_generator
from app.funnel import (
    FunnelSurface,
    JourneyDecisionRecord,
    JourneyEventRecord,
    JourneyEventType,
    JourneySession,
)
from app.segments import ALL_SEGMENTS, SEGMENT_DEFAULT, SEGMENT_DESCRIPTIONS, classify


class UnknownDecisionError(Exception):
    pass


class VariantMismatchError(Exception):
    pass


class ConflictingFeedbackError(Exception):
    pass


class UnknownSessionError(Exception):
    pass


class InvalidJourneyEventError(Exception):
    pass


class ConflictingJourneyOutcomeError(Exception):
    pass


@dataclass
class DecisionRecord:
    surface_id: str
    variant_id: str
    segment: str
    probability: float
    reward: int | None = None


class JourneyState:
    """Manages the contextual bandit lifecycle: decide → feedback → metrics.

    Integrates the segmented Thompson sampler, content registry, and
    optional LLM copy generator into a single thread-safe stateful object.
    """

    def __init__(self, seed: int | None = None) -> None:
        self._lock = Lock()
        self._rng = random.Random(seed)
        self.surface_id = "hero_banner"
        self.variants = list(VARIANTS)
        self.journey_stages = [stage.value for stage in FunnelSurface.ordered()]
        self._copy_gen: CopyGenerator = create_generator()
        self._reasoner: JourneyReasoner = create_reasoner()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._sampler = SegmentedThompsonSampler(
                self.variants, min_samples=20, rng=self._rng,
            )
            self._registry: ContentRegistry = build_default_registry()
            self.decisions: Dict[str, DecisionRecord] = {}
            self.history: List[Dict[str, Any]] = []
            self.step = 0

            self._journey_samplers: Dict[FunnelSurface, SegmentedThompsonSampler] = {
                stage: SegmentedThompsonSampler(
                    self.variants, min_samples=20, rng=self._rng,
                )
                for stage in FunnelSurface
            }
            self._journey_sessions: Dict[str, JourneySession] = {}
            self._journey_decisions: Dict[str, JourneyDecisionRecord] = {}
            self._journey_events: Dict[str, JourneyEventRecord] = {}
            self._journey_stage_templates = self._default_stage_templates()
            self._orchestrator = AgentOrchestrator()

    @staticmethod
    def _default_stage_templates() -> Dict[FunnelSurface, Dict[str, VariantContent]]:
        return {
            FunnelSurface.PRODUCT_PAGE: {
                "A": VariantContent(
                    headline="Compare fit, materials, and reviews",
                    subtitle="Everything you need to pick the right bundle in minutes.",
                    cta_text="Add to Cart",
                    trust_signals=["4.8 average rating", "Fast shipping"],
                    style_class="variant-a",
                ),
                "B": VariantContent(
                    headline="Most-loved setup for focused work",
                    subtitle="See why creators choose this bundle first.",
                    cta_text="Choose This",
                    trust_signals=["12,000+ customers", "Easy returns"],
                    style_class="variant-b",
                ),
                "C": VariantContent(
                    headline="Low stock on top bundles this week",
                    subtitle="Order now to lock in current pricing and availability.",
                    cta_text="Reserve Now",
                    trust_signals=["Limited inventory", "Ships tomorrow"],
                    style_class="variant-c",
                ),
            },
            FunnelSurface.CART: {
                "A": VariantContent(
                    headline="You are one step from checkout",
                    subtitle="Review your items and confirm your order details.",
                    cta_text="Proceed",
                    trust_signals=["Secure checkout", "30-day returns"],
                    style_class="variant-a",
                ),
                "B": VariantContent(
                    headline="Customers pair this with fast-delivery add-ons",
                    subtitle="Optional extras that ship together at no extra cost.",
                    cta_text="Continue",
                    trust_signals=["Bundle savings", "Trusted support"],
                    style_class="variant-b",
                ),
                "C": VariantContent(
                    headline="Checkout now before this cart expires",
                    subtitle="Current pricing and stock are reserved for a short time.",
                    cta_text="Checkout",
                    trust_signals=["Time-limited hold", "Secure payment"],
                    style_class="variant-c",
                ),
            },
        }

    # -- journey helpers ----------------------------------------------------

    @staticmethod
    def _coerce_stage(stage: str | FunnelSurface) -> FunnelSurface:
        if isinstance(stage, FunnelSurface):
            return stage
        try:
            return FunnelSurface(stage)
        except ValueError as exc:
            raise ValueError(f"Unsupported stage: {stage}") from exc

    @staticmethod
    def _coerce_event_type(event_type: str | JourneyEventType) -> JourneyEventType:
        if isinstance(event_type, JourneyEventType):
            return event_type
        try:
            return JourneyEventType(event_type)
        except ValueError as exc:
            raise ValueError(f"Unsupported event_type: {event_type}") from exc

    @staticmethod
    def _safe_rate(numerator: int, denominator: int) -> float:
        return numerator / denominator if denominator else 0.0

    @staticmethod
    def _empty_breakdown() -> Dict[str, Any]:
        return {
            "impressions": 0,
            "conversions": 0,
            "drop_offs": 0,
            "conversion_rate": 0.0,
        }

    def _resolve_session(
        self,
        session_id: str | None,
        context: Dict[str, Any],
    ) -> JourneySession:
        if session_id:
            session = self._journey_sessions.get(session_id)
            if session is None:
                session = JourneySession(session_id=session_id, context=dict(context))
                self._journey_sessions[session_id] = session
                return session
            if context:
                merged = dict(session.context)
                merged.update(context)
                session.context = merged
            return session

        new_session_id = str(uuid4())
        session = JourneySession(session_id=new_session_id, context=dict(context))
        self._journey_sessions[new_session_id] = session
        return session

    def _build_journey_content(
        self,
        stage: FunnelSurface,
        variant_id: str,
        segment: str,
    ) -> VariantContent:
        if stage == FunnelSurface.LANDING:
            content = self._registry.get(variant_id, segment)
            if content is not None:
                return content

        style_lookup = {
            "A": "variant-a",
            "B": "variant-b",
            "C": "variant-c",
        }
        by_stage = self._journey_stage_templates.get(stage, {})
        fallback = by_stage.get(variant_id)
        if fallback is not None:
            return fallback

        return VariantContent(
            headline="Personalized content",
            subtitle=f"Optimized for segment '{segment}'.",
            cta_text="Continue",
            trust_signals=["Adaptive optimization"],
            style_class=style_lookup.get(variant_id, "variant-a"),
        )

    # -- decide ------------------------------------------------------------

    def decide(self, surface_id: str, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        ctx = context or {}
        if surface_id != self.surface_id:
            raise ValueError(f"Unsupported surface_id: {surface_id}")

        with self._lock:
            segment = classify(ctx)
            variant_id, probability = self._sampler.choose(segment)

            content = self._registry.get(variant_id, segment)
            if content is None:
                content = VariantContent(
                    headline="Default headline",
                    subtitle="",
                    cta_text="Shop Now",
                    style_class="variant-a",
                )

            decision_id = str(uuid4())
            self.decisions[decision_id] = DecisionRecord(
                surface_id=surface_id,
                variant_id=variant_id,
                segment=segment,
                probability=probability,
            )

            return {
                "decision_id": decision_id,
                "surface_id": surface_id,
                "variant_id": variant_id,
                "segment": segment,
                "probability": probability,
                "policy": "contextual_thompson_sampling",
                "content": content.to_dict(),
            }

    # -- feedback ----------------------------------------------------------

    def feedback(
        self, decision_id: str, variant_id: str, reward: int,
    ) -> Dict[str, Any]:
        with self._lock:
            record = self.decisions.get(decision_id)
            if record is None:
                raise UnknownDecisionError(f"Unknown decision_id: {decision_id}")
            if record.variant_id != variant_id:
                raise VariantMismatchError(
                    f"decision_id {decision_id} belongs to variant "
                    f"{record.variant_id}, got {variant_id}"
                )

            if record.reward is not None:
                if record.reward != reward:
                    raise ConflictingFeedbackError(
                        f"Conflicting reward for decision_id {decision_id}"
                    )
                return {
                    "accepted": False,
                    "idempotent": True,
                    "decision_id": decision_id,
                    "variant_id": variant_id,
                    "reward": reward,
                }

            record.reward = reward
            self._sampler.update(record.segment, variant_id, reward)

            self.step += 1
            self.history.append({
                "step": self.step,
                "variant_id": variant_id,
                "reward": reward,
                "segment": record.segment,
            })

            return {
                "accepted": True,
                "idempotent": False,
                "decision_id": decision_id,
                "variant_id": variant_id,
                "reward": reward,
            }

    # -- journey decide/event/metrics --------------------------------------

    def journey_decide(
        self,
        stage: str,
        context: Dict[str, Any] | None = None,
        session_id: str | None = None,
        continue_from_decision_id: str | None = None,
    ) -> Dict[str, Any]:
        stage_id = self._coerce_stage(stage)
        ctx = dict(context or {})

        with self._lock:
            resolved_session_id = session_id
            if continue_from_decision_id:
                parent = self._journey_decisions.get(continue_from_decision_id)
                if parent is None:
                    raise UnknownDecisionError(
                        f"Unknown decision_id: {continue_from_decision_id}"
                    )
                if session_id and session_id != parent.session_id:
                    raise ValueError(
                        "session_id does not match continue_from_decision_id session"
                    )
                resolved_session_id = parent.session_id

            session = self._resolve_session(session_id=resolved_session_id, context=ctx)
            ctx = dict(session.context)

            segment = classify(ctx)
            variant_id, probability = self._journey_samplers[stage_id].choose(segment)
            content = self._build_journey_content(stage_id, variant_id, segment)

            decision_id = str(uuid4())
            self._journey_decisions[decision_id] = JourneyDecisionRecord(
                decision_id=decision_id,
                session_id=session.session_id,
                stage=stage_id,
                segment=segment,
                variant_id=variant_id,
                probability=probability,
                context=dict(ctx),
            )
            session.register_decision(stage_id, decision_id)

            return {
                "session_id": session.session_id,
                "decision_id": decision_id,
                "stage": stage_id.value,
                "variant_id": variant_id,
                "segment": segment,
                "probability": probability,
                "policy": "contextual_thompson_sampling_journey",
                "content": content.to_dict(),
            }

    def journey_event(
        self,
        event_type: str,
        *,
        decision_id: str | None = None,
        session_id: str | None = None,
        from_stage: str | None = None,
        to_stage: str | None = None,
    ) -> Dict[str, Any]:
        event_id = self._coerce_event_type(event_type)
        next_stage = self._coerce_stage(to_stage) if to_stage is not None else None

        if event_id == JourneyEventType.ADVANCE and next_stage is None:
            raise InvalidJourneyEventError("to_stage is required for advance events")
        if event_id in (JourneyEventType.DROP_OFF, JourneyEventType.CONVERT) and next_stage is not None:
            raise InvalidJourneyEventError(
                "to_stage must be omitted for drop_off and convert events"
            )

        reward = 1 if event_id in (JourneyEventType.ADVANCE, JourneyEventType.CONVERT) else 0

        with self._lock:
            resolved_session_id = session_id
            resolved_stage: FunnelSurface
            resolved_decision_id: str

            if decision_id:
                record = self._journey_decisions.get(decision_id)
                if record is None:
                    raise UnknownDecisionError(f"Unknown decision_id: {decision_id}")

                resolved_decision_id = decision_id
                resolved_session_id = record.session_id
                resolved_stage = record.stage

                if session_id and session_id != resolved_session_id:
                    raise InvalidJourneyEventError(
                        "session_id does not match decision_id session"
                    )
                if from_stage and self._coerce_stage(from_stage) != resolved_stage:
                    raise InvalidJourneyEventError(
                        "from_stage does not match decision_id stage"
                    )

                session = self._journey_sessions.get(resolved_session_id)
                if session is None:
                    session = JourneySession(session_id=resolved_session_id)
                    self._journey_sessions[resolved_session_id] = session
                if session.decisions_by_stage.get(resolved_stage) != resolved_decision_id:
                    session.register_decision(resolved_stage, resolved_decision_id)
            else:
                if not resolved_session_id or not from_stage:
                    raise InvalidJourneyEventError(
                        "Provide decision_id, or both session_id and from_stage"
                    )

                resolved_stage = self._coerce_stage(from_stage)
                session = self._journey_sessions.get(resolved_session_id)
                if session is None:
                    raise UnknownSessionError(
                        f"Unknown session_id: {resolved_session_id}. Call /journey/decide first."
                    )

                stage_decision = session.decisions_by_stage.get(resolved_stage)
                if stage_decision is None:
                    raise InvalidJourneyEventError(
                        f"No decision found for stage '{resolved_stage.value}' in session {resolved_session_id}"
                    )
                resolved_decision_id = stage_decision
                record = self._journey_decisions[resolved_decision_id]

            if record.reward is not None:
                if record.reward != reward:
                    raise ConflictingJourneyOutcomeError(
                        f"Conflicting event outcome for decision_id {resolved_decision_id}"
                    )
                return {
                    "accepted": False,
                    "idempotent": True,
                    "event_id": None,
                    "decision_id": resolved_decision_id,
                    "session_id": resolved_session_id,
                    "event_type": event_id.value,
                    "from_stage": resolved_stage.value,
                    "to_stage": next_stage.value if next_stage else None,
                    "reward": reward,
                }

            record.reward = reward
            self._journey_samplers[resolved_stage].update(record.segment, record.variant_id, reward)

            event_uuid = str(uuid4())
            self._journey_events[event_uuid] = JourneyEventRecord(
                event_id=event_uuid,
                session_id=resolved_session_id,
                event_type=event_id,
                from_stage=resolved_stage,
                to_stage=next_stage,
                reward=reward,
            )
            session.register_event(event_uuid, next_stage)
            if event_id in (JourneyEventType.DROP_OFF, JourneyEventType.CONVERT):
                session.closed = True

            return {
                "accepted": True,
                "idempotent": False,
                "event_id": event_uuid,
                "decision_id": resolved_decision_id,
                "session_id": resolved_session_id,
                "event_type": event_id.value,
                "from_stage": resolved_stage.value,
                "to_stage": next_stage.value if next_stage else None,
                "reward": reward,
            }

    def _journey_metrics_unlocked(self) -> Dict[str, Any]:
        stages_payload: Dict[str, Dict[str, Any]] = {}
        for stage in FunnelSurface.ordered():
            stages_payload[stage.value] = {
                "impressions": 0,
                "conversions": 0,
                "drop_offs": 0,
                "conversion_rate": 0.0,
                "variants": {variant: self._empty_breakdown() for variant in self.variants},
                "segments": {},
                "transitions": {},
            }

        for record in self._journey_decisions.values():
            stage_bucket = stages_payload[record.stage.value]
            stage_bucket["impressions"] += 1

            variant_bucket = stage_bucket["variants"].setdefault(
                record.variant_id, self._empty_breakdown(),
            )
            variant_bucket["impressions"] += 1

            segment_bucket = stage_bucket["segments"].setdefault(
                record.segment, self._empty_breakdown(),
            )
            segment_bucket["impressions"] += 1

            if record.reward == 1:
                stage_bucket["conversions"] += 1
                variant_bucket["conversions"] += 1
                segment_bucket["conversions"] += 1
            elif record.reward == 0:
                stage_bucket["drop_offs"] += 1
                variant_bucket["drop_offs"] += 1
                segment_bucket["drop_offs"] += 1

        for event in self._journey_events.values():
            if event.event_type != JourneyEventType.ADVANCE or event.to_stage is None:
                continue
            transition_bucket = stages_payload[event.from_stage.value]["transitions"]
            next_stage = event.to_stage.value
            transition_bucket[next_stage] = transition_bucket.get(next_stage, 0) + 1

        for stage_bucket in stages_payload.values():
            stage_bucket["conversion_rate"] = self._safe_rate(
                stage_bucket["conversions"], stage_bucket["impressions"],
            )
            for variant_bucket in stage_bucket["variants"].values():
                variant_bucket["conversion_rate"] = self._safe_rate(
                    variant_bucket["conversions"], variant_bucket["impressions"],
                )
            for segment_bucket in stage_bucket["segments"].values():
                segment_bucket["conversion_rate"] = self._safe_rate(
                    segment_bucket["conversions"], segment_bucket["impressions"],
                )

        path_counts: Dict[str, int] = defaultdict(int)
        for session in self._journey_sessions.values():
            path_parts: List[str] = []
            for stage in FunnelSurface.ordered():
                decision_id = session.decisions_by_stage.get(stage)
                if decision_id is None:
                    continue
                decision = self._journey_decisions.get(decision_id)
                if decision is None:
                    continue
                path_parts.append(f"{stage.value}:{decision.variant_id}")
            if path_parts:
                path_counts[" -> ".join(path_parts)] += 1

        top_paths = [
            {"path": path, "sessions": count}
            for path, count in sorted(
                path_counts.items(),
                key=lambda item: item[1],
                reverse=True,
            )[:10]
        ]

        total_sessions = len(self._journey_sessions)
        active_sessions = sum(1 for session in self._journey_sessions.values() if not session.closed)

        return {
            "policy": "contextual_thompson_sampling_journey",
            "stages": stages_payload,
            "sessions": {
                "total": total_sessions,
                "active": active_sessions,
                "closed": total_sessions - active_sessions,
            },
            "top_paths": top_paths,
        }

    def journey_metrics(self) -> Dict[str, Any]:
        with self._lock:
            return self._journey_metrics_unlocked()

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
        base = AnalyzerConfig()
        config = AnalyzerConfig(
            min_stage_impressions=(
                base.min_stage_impressions
                if min_stage_impressions is None
                else min_stage_impressions
            ),
            stage_drop_off_threshold=(
                base.stage_drop_off_threshold
                if stage_drop_off_threshold is None
                else stage_drop_off_threshold
            ),
            min_segment_impressions=(
                base.min_segment_impressions
                if min_segment_impressions is None
                else min_segment_impressions
            ),
            segment_gap_threshold=(
                base.segment_gap_threshold
                if segment_gap_threshold is None
                else segment_gap_threshold
            ),
            trend_window=(
                base.trend_window
                if trend_window is None
                else trend_window
            ),
            trend_decline_threshold=(
                base.trend_decline_threshold
                if trend_decline_threshold is None
                else trend_decline_threshold
            ),
        )
        analyzer = FunnelAnalyzer(config)

        with self._lock:
            metrics = self._journey_metrics_unlocked()
            decisions = list(self._journey_decisions.values())

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

        base = AnalyzerConfig()
        config = AnalyzerConfig(
            min_stage_impressions=(
                base.min_stage_impressions
                if min_stage_impressions is None
                else min_stage_impressions
            ),
            stage_drop_off_threshold=(
                base.stage_drop_off_threshold
                if stage_drop_off_threshold is None
                else stage_drop_off_threshold
            ),
            min_segment_impressions=(
                base.min_segment_impressions
                if min_segment_impressions is None
                else min_segment_impressions
            ),
            segment_gap_threshold=(
                base.segment_gap_threshold
                if segment_gap_threshold is None
                else segment_gap_threshold
            ),
            trend_window=(
                base.trend_window
                if trend_window is None
                else trend_window
            ),
            trend_decline_threshold=(
                base.trend_decline_threshold
                if trend_decline_threshold is None
                else trend_decline_threshold
            ),
        )
        analyzer = FunnelAnalyzer(config)

        with self._lock:
            metrics = self._journey_metrics_unlocked()
            decisions = list(self._journey_decisions.values())

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

    # -- phase 4: execution/orchestration ---------------------------------

    def _apply_experiment_templates(self, experiments: List[Dict[str, Any]]) -> None:
        variant_map = {
            0: "A",
            1: "B",
            2: "C",
            "control": "A",
            "variant_b": "B",
            "variant_c": "C",
            "A": "A",
            "B": "B",
            "C": "C",
        }

        for experiment in experiments:
            stage_raw = str(experiment.get("stage", ""))
            try:
                stage = self._coerce_stage(stage_raw)
            except ValueError:
                continue

            if stage == FunnelSurface.LANDING:
                continue

            variants = experiment.get("variants")
            if not isinstance(variants, list):
                continue

            stage_templates = self._journey_stage_templates.setdefault(stage, {})
            for idx, variant in enumerate(variants):
                if not isinstance(variant, dict):
                    continue

                variant_key = variant.get("variant_id")
                canonical_variant = variant_map.get(variant_key)
                if canonical_variant is None:
                    canonical_variant = variant_map.get(idx)
                if canonical_variant is None:
                    continue

                message_angle = str(variant.get("message_angle") or "Personalized messaging")
                description = str(variant.get("description") or "")
                style_class = {
                    "A": "variant-a",
                    "B": "variant-b",
                    "C": "variant-c",
                }.get(canonical_variant, "variant-a")

                stage_templates[canonical_variant] = VariantContent(
                    headline=message_angle,
                    subtitle=description,
                    cta_text=(
                        "Add to Cart"
                        if stage == FunnelSurface.PRODUCT_PAGE
                        else "Continue"
                    ),
                    trust_signals=[
                        "Agent-optimized",
                        f"Experiment {experiment.get('experiment_id', 'N/A')}",
                    ],
                    style_class=style_class,
                )

    def _sample_demo_context(self) -> Dict[str, Any]:
        profiles = [
            {"device_type": "mobile", "traffic_source": "meta", "is_returning": False},
            {"device_type": "mobile", "traffic_source": "google", "is_returning": False},
            {"device_type": "desktop", "traffic_source": "direct", "is_returning": False},
            {"device_type": "desktop", "traffic_source": "direct", "is_returning": True},
        ]
        return dict(self._rng.choice(profiles))

    def _landing_advance_probability(self, variant_id: str, segment: str) -> float:
        by_variant = {"A": 0.58, "B": 0.52, "C": 0.47}
        bonus = 0.0
        if segment == "returning_any":
            bonus += 0.07
        if segment == "new_mobile_paid":
            bonus -= 0.04
        return max(0.05, min(0.95, by_variant.get(variant_id, 0.5) + bonus))

    def _product_convert_probability(self, variant_id: str, segment: str) -> float:
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
            landing = self.journey_decide(stage="landing", context=context)
            landing_p = self._landing_advance_probability(
                variant_id=landing["variant_id"],
                segment=landing["segment"],
            )

            if self._rng.random() < landing_p:
                summary["landing_advances"] += 1
                self.journey_event(
                    event_type="advance",
                    decision_id=landing["decision_id"],
                    to_stage="product_page",
                )

                product = self.journey_decide(
                    stage="product_page",
                    continue_from_decision_id=landing["decision_id"],
                )
                product_p = self._product_convert_probability(
                    variant_id=product["variant_id"],
                    segment=product["segment"],
                )

                if self._rng.random() < product_p:
                    summary["product_conversions"] += 1
                    self.journey_event(
                        event_type="convert",
                        decision_id=product["decision_id"],
                    )
                else:
                    summary["product_drop_offs"] += 1
                    self.journey_event(
                        event_type="drop_off",
                        decision_id=product["decision_id"],
                    )
            else:
                summary["landing_drop_offs"] += 1
                self.journey_event(
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
            metrics = self._journey_metrics_unlocked()
            cycle = self._orchestrator.run_cycle(
                reasoning_payload=reasoning_payload,
                journey_metrics=metrics,
            )
            self._apply_experiment_templates(cycle.get("launched", []))
            cycle_status = cycle.get("status", {})
            cycle_status["journey_sessions"] = {
                "total": len(self._journey_sessions),
                "closed": sum(1 for s in self._journey_sessions.values() if s.closed),
            }
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
            status["journey_sessions"] = {
                "total": len(self._journey_sessions),
                "closed": sum(1 for s in self._journey_sessions.values() if s.closed),
            }
            status["journey_metrics"] = self._journey_metrics_unlocked()
            return status

    def agent_history(self, limit: int = 100) -> Dict[str, Any]:
        with self._lock:
            return {"events": self._orchestrator.history(limit=limit)}

    # -- metrics -----------------------------------------------------------

    def metrics(self) -> Dict[str, Any]:
        with self._lock:
            global_stats = self._sampler.global_stats()
            variants_payload: Dict[str, Any] = {}
            total_impressions = 0
            total_successes = 0
            total_failures = 0

            for vid in self.variants:
                arm = global_stats.get(vid, ArmStats())
                ctr = arm.successes / arm.impressions if arm.impressions else 0.0
                variants_payload[vid] = {
                    "impressions": arm.impressions,
                    "successes": arm.successes,
                    "failures": arm.failures,
                    "ctr": ctr,
                }
                total_impressions += arm.impressions
                total_successes += arm.successes
                total_failures += arm.failures

            total_ctr = total_successes / total_impressions if total_impressions else 0.0

            segments_payload: Dict[str, Any] = {}
            for seg in self._sampler.all_segments():
                seg_stats = self._sampler.segment_stats(seg)
                seg_vars: Dict[str, Any] = {}
                seg_imp = seg_suc = seg_fail = 0
                for vid in self.variants:
                    arm = seg_stats.get(vid, ArmStats())
                    seg_vars[vid] = {
                        "impressions": arm.impressions,
                        "successes": arm.successes,
                        "failures": arm.failures,
                        "ctr": arm.successes / arm.impressions if arm.impressions else 0.0,
                    }
                    seg_imp += arm.impressions
                    seg_suc += arm.successes
                    seg_fail += arm.failures

                segments_payload[seg] = {
                    "variants": seg_vars,
                    "totals": {
                        "impressions": seg_imp,
                        "successes": seg_suc,
                        "failures": seg_fail,
                        "ctr": seg_suc / seg_imp if seg_imp else 0.0,
                    },
                }

            return {
                "surface_id": self.surface_id,
                "policy": "contextual_thompson_sampling",
                "variants": variants_payload,
                "totals": {
                    "impressions": total_impressions,
                    "successes": total_successes,
                    "failures": total_failures,
                    "ctr": total_ctr,
                },
                "segments": segments_payload,
                "history": self.history[-1000:],
            }

    # -- segments ----------------------------------------------------------

    def segment_list(self) -> List[Dict[str, Any]]:
        with self._lock:
            result = []
            for seg in ALL_SEGMENTS:
                stats = self._sampler.segment_stats(seg)
                total = sum(a.impressions for a in stats.values())
                result.append({
                    "segment_id": seg,
                    "description": SEGMENT_DESCRIPTIONS.get(seg, seg),
                    "total_impressions": total,
                })
            return result

    # -- copy generation ---------------------------------------------------

    def generate_copy(
        self,
        product: str,
        reviews: List[str],
        segment: str,
        num_variants: int = 3,
    ) -> int:
        copies = self._copy_gen.generate(
            product, reviews, segment, num_variants=num_variants,
        )
        with self._lock:
            for i, vc in enumerate(copies):
                vid = self.variants[i] if i < len(self.variants) else f"gen_{i}"
                self._registry.register(vid, segment, vc)
        return len(copies)


# Backward-compatible alias used by existing imports/tests.
BanditState = JourneyState
