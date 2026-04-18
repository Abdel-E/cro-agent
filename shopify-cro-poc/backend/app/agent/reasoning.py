from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List

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
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise ImportError(
                "pip install google-genai to use GeminiJourneyReasoner"
            ) from exc

        api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("Set GOOGLE_API_KEY or GEMINI_API_KEY for Gemini reasoning")

        self._client = genai.Client(api_key=api_key)
        self._model_name = model or os.environ.get("AGENT_REASONER_MODEL", "gemini-2.5-flash")
        self._insight_config = types.GenerateContentConfig(
            temperature=0.2,
            maxOutputTokens=160,
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
        fallback_payload = self._fallback.reason(
            observations=observations,
            metrics_summary=metrics_summary,
            max_hypotheses=max_hypotheses,
            max_experiments=max_experiments,
        )
        return self._with_optional_gemini_insight(
            fallback_payload=fallback_payload,
            observations=observations,
            metrics_summary=metrics_summary,
        )

    def _with_optional_gemini_insight(
        self,
        *,
        fallback_payload: Dict[str, Any],
        observations: List[Dict[str, Any]],
        metrics_summary: Dict[str, Any],
    ) -> Dict[str, Any]:
        summary = metrics_summary.get("summary", {})
        base_insight = str(fallback_payload.get("insight") or "").strip()
        insight_prompt = (
            "You are polishing a CRO sandbox insight for display in a dashboard.\n"
            "Rewrite the draft into 1-2 crisp sentences, under 45 words.\n"
            "Keep stage names and percentages accurate. Use plain text only.\n"
            "If there is not enough signal, say exactly: "
            "\"No data available to generate insights, hypotheses, or experiments.\"\n\n"
            f"Draft insight: {base_insight}\n"
            f"Observation count: {len(observations)}\n"
            f"Bottleneck stage: {summary.get('bottleneck_stage')}\n"
            f"Bottleneck drop-off rate: {summary.get('bottleneck_drop_off_rate', 0.0):.1%}\n"
            f"Top observations: {json.dumps(observations[:2])}\n"
        )
        try:
            response = self._client.models.generate_content(
                model=self._model_name,
                contents=insight_prompt,
                config=self._insight_config,
            )
            insight = (response.text or "").strip()
        except Exception:
            logger.exception("Gemini insight generation failed; returning mock insight")
            return fallback_payload

        if insight:
            if insight[-1] not in ".!?":
                insight = f"{insight}."
            fallback_payload["insight"] = insight
            fallback_payload["backend"] = self.backend_name
        return fallback_payload


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
