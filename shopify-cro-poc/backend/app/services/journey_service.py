from __future__ import annotations

from collections import defaultdict
from threading import Lock
from typing import Any, Callable, Dict, List
from uuid import uuid4

from app.bandit import SegmentedThompsonSampler
from app.content import VariantContent
from app.funnel import (
    FunnelSurface,
    JourneyDecisionRecord,
    JourneyEventRecord,
    JourneyEventType,
    JourneySession,
)
from app.services.journey_content import (
    EXPERIMENT_VARIANT_KEY_MAP,
    build_default_stage_templates,
    fallback_journey_content,
    style_class_for_variant,
)
from app.services.decision_service import UnknownDecisionError
from app.segments import classify


class UnknownSessionError(Exception):
    pass


class InvalidJourneyEventError(Exception):
    pass


class ConflictingJourneyOutcomeError(Exception):
    pass


class JourneyService:
    def __init__(
        self,
        *,
        rng: Any,
        variants: List[str],
        landing_content_getter: Callable[[str, str], VariantContent | None],
    ) -> None:
        self._lock = Lock()
        self._rng = rng
        self._variants = list(variants)
        self._landing_content_getter = landing_content_getter
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._samplers: Dict[FunnelSurface, SegmentedThompsonSampler] = {
                stage: SegmentedThompsonSampler(
                    self._variants, min_samples=20, rng=self._rng,
                )
                for stage in FunnelSurface
            }
            self._sessions: Dict[str, JourneySession] = {}
            self._decisions: Dict[str, JourneyDecisionRecord] = {}
            self._events: Dict[str, JourneyEventRecord] = {}
            self._stage_templates = build_default_stage_templates()

    @staticmethod
    def coerce_stage(stage: str | FunnelSurface) -> FunnelSurface:
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
            session = self._sessions.get(session_id)
            if session is None:
                session = JourneySession(session_id=session_id, context=dict(context))
                self._sessions[session_id] = session
                return session
            if context:
                merged = dict(session.context)
                merged.update(context)
                session.context = merged
            return session

        new_session_id = str(uuid4())
        session = JourneySession(session_id=new_session_id, context=dict(context))
        self._sessions[new_session_id] = session
        return session

    def _build_journey_content(
        self,
        stage: FunnelSurface,
        variant_id: str,
        segment: str,
    ) -> VariantContent:
        if stage == FunnelSurface.LANDING:
            content = self._landing_content_getter(variant_id, segment)
            if content is not None:
                return content

        by_stage = self._stage_templates.get(stage, {})
        fallback = by_stage.get(variant_id)
        if fallback is not None:
            return fallback

        return fallback_journey_content(variant_id, segment)

    def journey_decide(
        self,
        stage: str,
        context: Dict[str, Any] | None = None,
        session_id: str | None = None,
        continue_from_decision_id: str | None = None,
    ) -> Dict[str, Any]:
        stage_id = self.coerce_stage(stage)
        ctx = dict(context or {})

        with self._lock:
            resolved_session_id = session_id
            if continue_from_decision_id:
                parent = self._decisions.get(continue_from_decision_id)
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
            variant_id, probability = self._samplers[stage_id].choose(segment)
            content = self._build_journey_content(stage_id, variant_id, segment)

            decision_id = str(uuid4())
            self._decisions[decision_id] = JourneyDecisionRecord(
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
        next_stage = self.coerce_stage(to_stage) if to_stage is not None else None

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
                record = self._decisions.get(decision_id)
                if record is None:
                    raise UnknownDecisionError(f"Unknown decision_id: {decision_id}")

                resolved_decision_id = decision_id
                resolved_session_id = record.session_id
                resolved_stage = record.stage

                if session_id and session_id != resolved_session_id:
                    raise InvalidJourneyEventError(
                        "session_id does not match decision_id session"
                    )
                if from_stage and self.coerce_stage(from_stage) != resolved_stage:
                    raise InvalidJourneyEventError(
                        "from_stage does not match decision_id stage"
                    )

                session = self._sessions.get(resolved_session_id)
                if session is None:
                    session = JourneySession(session_id=resolved_session_id)
                    self._sessions[resolved_session_id] = session
                if session.decisions_by_stage.get(resolved_stage) != resolved_decision_id:
                    session.register_decision(resolved_stage, resolved_decision_id)
            else:
                if not resolved_session_id or not from_stage:
                    raise InvalidJourneyEventError(
                        "Provide decision_id, or both session_id and from_stage"
                    )

                resolved_stage = self.coerce_stage(from_stage)
                session = self._sessions.get(resolved_session_id)
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
                record = self._decisions[resolved_decision_id]

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
            self._samplers[resolved_stage].update(record.segment, record.variant_id, reward)

            event_uuid = str(uuid4())
            self._events[event_uuid] = JourneyEventRecord(
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

    def _metrics_unlocked(self) -> Dict[str, Any]:
        stages_payload: Dict[str, Dict[str, Any]] = {}
        for stage in FunnelSurface.ordered():
            stages_payload[stage.value] = {
                "impressions": 0,
                "conversions": 0,
                "drop_offs": 0,
                "conversion_rate": 0.0,
                "variants": {variant: self._empty_breakdown() for variant in self._variants},
                "segments": {},
                "transitions": {},
            }

        for record in self._decisions.values():
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

        for event in self._events.values():
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
        for session in self._sessions.values():
            path_parts: List[str] = []
            for stage in FunnelSurface.ordered():
                decision_id = session.decisions_by_stage.get(stage)
                if decision_id is None:
                    continue
                decision = self._decisions.get(decision_id)
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

        total_sessions = len(self._sessions)
        active_sessions = sum(1 for session in self._sessions.values() if not session.closed)

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

    def metrics(self) -> Dict[str, Any]:
        with self._lock:
            return self._metrics_unlocked()

    def metrics_and_decisions(self) -> tuple[Dict[str, Any], List[JourneyDecisionRecord]]:
        with self._lock:
            return self._metrics_unlocked(), list(self._decisions.values())

    def session_counts(self) -> Dict[str, int]:
        with self._lock:
            total = len(self._sessions)
            closed = sum(1 for s in self._sessions.values() if s.closed)
            return {"total": total, "closed": closed}

    def apply_experiment_templates(self, experiments: List[Dict[str, Any]]) -> None:
        with self._lock:
            for experiment in experiments:
                stage_raw = str(experiment.get("stage", ""))
                try:
                    stage = self.coerce_stage(stage_raw)
                except ValueError:
                    continue

                if stage == FunnelSurface.LANDING:
                    continue

                variants = experiment.get("variants")
                if not isinstance(variants, list):
                    continue

                stage_templates = self._stage_templates.setdefault(stage, {})
                for idx, variant in enumerate(variants):
                    if not isinstance(variant, dict):
                        continue

                    variant_key = variant.get("variant_id")
                    canonical_variant = EXPERIMENT_VARIANT_KEY_MAP.get(variant_key)
                    if canonical_variant is None:
                        canonical_variant = EXPERIMENT_VARIANT_KEY_MAP.get(idx)
                    if canonical_variant is None:
                        continue

                    message_angle = str(variant.get("message_angle") or "Personalized messaging")
                    description = str(variant.get("description") or "")
                    style_class = style_class_for_variant(canonical_variant)

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

