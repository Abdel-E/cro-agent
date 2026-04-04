from __future__ import annotations

import json
from typing import Any, Dict, List


def build_reasoning_prompt(
    *,
    observations: List[Dict[str, Any]],
    metrics_summary: Dict[str, Any],
    max_hypotheses: int,
    max_experiments: int,
) -> str:
    """Build an LLM prompt for journey hypothesis and experiment generation."""
    observations_json = json.dumps(observations, ensure_ascii=True)
    metrics_summary_json = json.dumps(metrics_summary, ensure_ascii=True)

    return (
        "You are a CRO strategist for a Shopify growth team.\n"
        "You receive journey observations and must produce clear hypotheses and experiments.\n\n"
        f"Input observations:\n{observations_json}\n\n"
        f"Journey summary:\n{metrics_summary_json}\n\n"
        "Output strict JSON only. No prose outside JSON.\n"
        "Return an object with these keys:\n"
        "- insight: short analytical paragraph\n"
        "- hypotheses: array\n"
        "- experiments: array\n\n"
        f"Generate at most {max_hypotheses} hypotheses and {max_experiments} experiments.\n"
        "Schema:\n"
        "{\n"
        "  \"insight\": \"string\",\n"
        "  \"hypotheses\": [\n"
        "    {\n"
        "      \"hypothesis_id\": \"H-001\",\n"
        "      \"stage\": \"landing|product_page|cart\",\n"
        "      \"segment\": \"string|null\",\n"
        "      \"confidence\": 0.0,\n"
        "      \"rationale\": \"string\",\n"
        "      \"proposed_angle\": \"string\",\n"
        "      \"expected_effect\": \"string\"\n"
        "    }\n"
        "  ],\n"
        "  \"experiments\": [\n"
        "    {\n"
        "      \"experiment_id\": \"EXP-001\",\n"
        "      \"hypothesis_id\": \"H-001\",\n"
        "      \"stage\": \"landing|product_page|cart\",\n"
        "      \"objective_metric\": \"stage_conversion_rate\",\n"
        "      \"allocation\": {\"control\": 0.34, \"variant_b\": 0.33, \"variant_c\": 0.33},\n"
        "      \"success_criterion\": \"string\",\n"
        "      \"variants\": [\n"
        "        {\"variant_id\": \"control\", \"message_angle\": \"string\", \"description\": \"string\"},\n"
        "        {\"variant_id\": \"variant_b\", \"message_angle\": \"string\", \"description\": \"string\"},\n"
        "        {\"variant_id\": \"variant_c\", \"message_angle\": \"string\", \"description\": \"string\"}\n"
        "      ]\n"
        "    }\n"
        "  ]\n"
        "}\n"
    )
