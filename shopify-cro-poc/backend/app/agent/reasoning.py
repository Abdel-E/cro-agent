from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List

from app.agent.prompts import build_reasoning_prompt
from app.funnel import utcnow_iso
from app.llm_utils import strip_markdown_code_fences

logger = logging.getLogger(__name__)


def _clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_stage(value: Any) -> str:
    stage = str(value or "").strip()
    if stage in {"landing", "product_page", "cart"}:
        return stage
    return "landing"


class JourneyReasoner(ABC):
    @property
    @abstractmethod
    def backend_name(self) -> str:
        ...

    @abstractmethod
    def reason(
        self,
        *,
        observations: List[Dict[str, Any]],
        metrics_summary: Dict[str, Any],
        max_hypotheses: int,
        max_experiments: int,
    ) -> Dict[str, Any]:
        ...


class MockJourneyReasoner(JourneyReasoner):
    _SEVERITY_SCORE = {"high": 3, "medium": 2, "low": 1}
    _CONFIDENCE_BY_SEVERITY = {"high": 0.82, "medium": 0.68, "low": 0.55}

    @property
    def backend_name(self) -> str:
        return "mock"

    def reason(
        self,
        *,
        observations: List[Dict[str, Any]],
        metrics_summary: Dict[str, Any],
        max_hypotheses: int,
        max_experiments: int,
    ) -> Dict[str, Any]:
        prioritized = sorted(
            observations,
            key=lambda obs: -self._SEVERITY_SCORE.get(str(obs.get("severity", "low")), 1),
        )

        hypotheses: List[Dict[str, Any]] = []
        for index, obs in enumerate(prioritized[:max_hypotheses], start=1):
            kind = str(obs.get("kind", ""))
            stage = _coerce_stage(obs.get("stage"))
            segment = obs.get("segment")
            severity = str(obs.get("severity", "medium"))
            confidence = self._CONFIDENCE_BY_SEVERITY.get(severity, 0.6)

            if kind == "stage_drop_off":
                rationale = (
                    f"High drop-off at {stage} suggests friction or weak value communication "
                    "at this point in the journey."
                )
                angle = "Strengthen clarity and trust on core value proposition"
                effect = "Improve stage conversion rate by 8-15%"
            elif kind == "segment_underperforming":
                seg_name = segment or "target segment"
                rationale = (
                    f"Segment '{seg_name}' underperforms versus stage baseline, indicating "
                    "message-market mismatch for this audience."
                )
                angle = "Personalize messaging and CTA for the underperforming segment"
                effect = "Close segment conversion gap by 5-10 points"
            elif kind == "stage_decline_trend":
                rationale = (
                    f"Recent conversion decline at {stage} indicates possible creative fatigue "
                    "or changing traffic intent."
                )
                angle = "Refresh creative framing and urgency/trust balance"
                effect = "Recover recent conversion decline trend"
            else:
                rationale = "Observed performance pattern warrants targeted experimentation."
                angle = "Test alternative value framing"
                effect = "Increase conversion consistency"

            hypotheses.append(
                {
                    "hypothesis_id": f"H-{index:03d}",
                    "stage": stage,
                    "segment": segment,
                    "confidence": confidence,
                    "rationale": rationale,
                    "proposed_angle": angle,
                    "expected_effect": effect,
                }
            )

        experiments: List[Dict[str, Any]] = []
        for index, hypothesis in enumerate(hypotheses[:max_experiments], start=1):
            stage = hypothesis["stage"]
            base_angle = hypothesis["proposed_angle"]
            objective_metric = f"{stage}_conversion_rate"
            experiments.append(
                {
                    "experiment_id": f"EXP-{index:03d}",
                    "hypothesis_id": hypothesis["hypothesis_id"],
                    "stage": stage,
                    "objective_metric": objective_metric,
                    "allocation": {
                        "control": 0.34,
                        "variant_b": 0.33,
                        "variant_c": 0.33,
                    },
                    "success_criterion": (
                        "Promote winner when posterior win probability exceeds 0.9 "
                        "after at least 150 resolved stage decisions."
                    ),
                    "variants": [
                        {
                            "variant_id": "control",
                            "message_angle": "Current experience",
                            "description": "Keep current copy and layout as baseline.",
                        },
                        {
                            "variant_id": "variant_b",
                            "message_angle": base_angle,
                            "description": (
                                "Emphasize trust and outcome clarity in headline and CTA."
                            ),
                        },
                        {
                            "variant_id": "variant_c",
                            "message_angle": "Urgency + social proof blend",
                            "description": (
                                "Test scarcity language paired with concrete social proof."
                            ),
                        },
                    ],
                }
            )

        summary = metrics_summary.get("summary", {})
        bottleneck = summary.get("bottleneck_stage")
        drop_rate = summary.get("bottleneck_drop_off_rate", 0.0)
        if hypotheses:
            insight = (
                f"Detected {len(hypotheses)} prioritized optimization opportunities. "
                f"Current bottleneck is '{bottleneck}' with drop-off rate {drop_rate:.1%}. "
                "Proposed experiments focus on message clarity, trust, and segment alignment."
            )
        else:
            insight = (
                "No high-confidence bottlenecks detected with current thresholds. "
                "Keep collecting data or lower thresholds for exploratory hypotheses."
            )

        return {
            "policy": "journey_reasoning_v1",
            "backend": self.backend_name,
            "generated_at": utcnow_iso(),
            "source_observations": len(observations),
            "insight": insight,
            "hypotheses": hypotheses,
            "experiments": experiments,
        }


class GeminiJourneyReasoner(JourneyReasoner):
    def __init__(self, model: str | None = None) -> None:
        try:
            import google.generativeai as genai
        except ImportError as exc:
            raise ImportError(
                "pip install google-generativeai to use GeminiJourneyReasoner"
            ) from exc

        api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("Set GOOGLE_API_KEY or GEMINI_API_KEY for Gemini reasoning")

        genai.configure(api_key=api_key)
        self._model_name = model or os.environ.get("AGENT_REASONER_MODEL", "gemini-2.5-flash")

        try:
            gen_cfg = genai.GenerationConfig(
                temperature=0.6,
                max_output_tokens=2048,
                response_mime_type="application/json",
            )
        except TypeError:
            gen_cfg = genai.GenerationConfig(temperature=0.6, max_output_tokens=2048)

        self._model = genai.GenerativeModel(
            model_name=self._model_name,
            generation_config=gen_cfg,
        )
        self._fallback = MockJourneyReasoner()

    @property
    def backend_name(self) -> str:
        return "gemini"

    def reason(
        self,
        *,
        observations: List[Dict[str, Any]],
        metrics_summary: Dict[str, Any],
        max_hypotheses: int,
        max_experiments: int,
    ) -> Dict[str, Any]:
        prompt = build_reasoning_prompt(
            observations=observations,
            metrics_summary=metrics_summary,
            max_hypotheses=max_hypotheses,
            max_experiments=max_experiments,
        )
        try:
            response = self._model.generate_content(prompt)
            raw = (response.text or "").strip()
        except Exception:
            logger.exception("Gemini reasoning generation failed; falling back to mock")
            return self._fallback.reason(
                observations=observations,
                metrics_summary=metrics_summary,
                max_hypotheses=max_hypotheses,
                max_experiments=max_experiments,
            )

        parsed = self._parse_reasoning_json(
            raw=raw,
            max_hypotheses=max_hypotheses,
            max_experiments=max_experiments,
        )
        if parsed is None:
            logger.warning("Gemini reasoning payload invalid; falling back to mock")
            return self._fallback.reason(
                observations=observations,
                metrics_summary=metrics_summary,
                max_hypotheses=max_hypotheses,
                max_experiments=max_experiments,
            )

        parsed["policy"] = "journey_reasoning_v1"
        parsed["backend"] = self.backend_name
        parsed["generated_at"] = utcnow_iso()
        parsed["source_observations"] = len(observations)
        return parsed

    def _parse_reasoning_json(
        self,
        *,
        raw: str,
        max_hypotheses: int,
        max_experiments: int,
    ) -> Dict[str, Any] | None:
        if not raw:
            return None
        try:
            payload = json.loads(strip_markdown_code_fences(raw))
        except json.JSONDecodeError:
            return None

        if not isinstance(payload, dict):
            return None

        hypotheses_in = payload.get("hypotheses", [])
        experiments_in = payload.get("experiments", [])
        insight = str(payload.get("insight", "")).strip()

        if not isinstance(hypotheses_in, list) or not isinstance(experiments_in, list):
            return None

        hypotheses: List[Dict[str, Any]] = []
        for idx, item in enumerate(hypotheses_in[:max_hypotheses], start=1):
            if not isinstance(item, dict):
                continue
            hypotheses.append(
                {
                    "hypothesis_id": str(item.get("hypothesis_id") or f"H-{idx:03d}"),
                    "stage": _coerce_stage(item.get("stage")),
                    "segment": item.get("segment") if item.get("segment") not in ("", None) else None,
                    "confidence": _clamp01(_safe_float(item.get("confidence"), 0.6)),
                    "rationale": str(item.get("rationale") or ""),
                    "proposed_angle": str(item.get("proposed_angle") or ""),
                    "expected_effect": str(item.get("expected_effect") or ""),
                }
            )

        hypothesis_ids = {h["hypothesis_id"] for h in hypotheses}
        default_hypothesis_id = hypotheses[0]["hypothesis_id"] if hypotheses else "H-001"

        experiments: List[Dict[str, Any]] = []
        for idx, item in enumerate(experiments_in[:max_experiments], start=1):
            if not isinstance(item, dict):
                continue

            allocation_in = item.get("allocation")
            allocation = {
                "control": 0.34,
                "variant_b": 0.33,
                "variant_c": 0.33,
            }
            if isinstance(allocation_in, dict):
                for key in ("control", "variant_b", "variant_c"):
                    if key in allocation_in:
                        allocation[key] = _clamp01(_safe_float(allocation_in.get(key), allocation[key]))

            variants_in = item.get("variants", [])
            variants: List[Dict[str, str]] = []
            if isinstance(variants_in, list):
                for variant in variants_in[:3]:
                    if not isinstance(variant, dict):
                        continue
                    variants.append(
                        {
                            "variant_id": str(variant.get("variant_id") or "variant"),
                            "message_angle": str(variant.get("message_angle") or ""),
                            "description": str(variant.get("description") or ""),
                        }
                    )
            if not variants:
                variants = [
                    {
                        "variant_id": "control",
                        "message_angle": "Current experience",
                        "description": "Keep current baseline.",
                    },
                    {
                        "variant_id": "variant_b",
                        "message_angle": "Alternative framing",
                        "description": "Test stronger trust/value framing.",
                    },
                    {
                        "variant_id": "variant_c",
                        "message_angle": "Urgency framing",
                        "description": "Test urgency and social proof blend.",
                    },
                ]

            hypothesis_id = str(item.get("hypothesis_id") or default_hypothesis_id)
            if hypothesis_id not in hypothesis_ids:
                hypothesis_id = default_hypothesis_id

            experiments.append(
                {
                    "experiment_id": str(item.get("experiment_id") or f"EXP-{idx:03d}"),
                    "hypothesis_id": hypothesis_id,
                    "stage": _coerce_stage(item.get("stage")),
                    "objective_metric": str(item.get("objective_metric") or "stage_conversion_rate"),
                    "allocation": allocation,
                    "success_criterion": str(
                        item.get("success_criterion")
                        or "Promote winner when posterior win probability > 0.9 with sufficient traffic."
                    ),
                    "variants": variants,
                }
            )

        if not insight:
            insight = "Reasoning generated from journey observations."

        return {
            "insight": insight,
            "hypotheses": hypotheses,
            "experiments": experiments,
        }


def create_reasoner() -> JourneyReasoner:
    backend = os.environ.get("AGENT_REASONER_BACKEND", "mock").lower()
    if backend == "gemini":
        try:
            return GeminiJourneyReasoner()
        except (ValueError, ImportError) as exc:
            logger.warning(
                "AGENT_REASONER_BACKEND=gemini but unavailable (%s); using mock",
                exc,
            )
            return MockJourneyReasoner()
    return MockJourneyReasoner()
