from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Any, Dict, List
from uuid import uuid4

from app.bandit import ArmStats, SegmentedThompsonSampler
from app.content import VARIANTS, ContentRegistry, VariantContent, build_default_registry
from app.copy_generator import CopyGenerator, create_generator
from app.segments import ALL_SEGMENTS, SEGMENT_DESCRIPTIONS, classify


class UnknownDecisionError(Exception):
    pass


class VariantMismatchError(Exception):
    pass


class ConflictingFeedbackError(Exception):
    pass


@dataclass
class DecisionRecord:
    surface_id: str
    variant_id: str
    segment: str
    probability: float
    reward: int | None = None


class DecisionService:
    def __init__(self, *, rng: Any, surface_id: str = "hero_banner") -> None:
        self._lock = Lock()
        self._rng = rng
        self.surface_id = surface_id
        self.variants = list(VARIANTS)
        self._copy_gen: CopyGenerator = create_generator()
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

    def content_for(self, variant_id: str, segment: str) -> VariantContent | None:
        with self._lock:
            return self._registry.get(variant_id, segment)

    def feedback(self, decision_id: str, variant_id: str, reward: int) -> Dict[str, Any]:
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

