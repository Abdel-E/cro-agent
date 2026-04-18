"""LLM-powered copy generator with Google Gemini and mock backends.

Generates headline / subtitle / CTA variants for a given product, review
corpus, and target segment.  Results are cached in-memory to avoid redundant
API calls during a single server lifetime.

Environment:
  ``COPY_GENERATOR_BACKEND`` — ``"mock"`` (default) or ``"gemini"``
  ``GOOGLE_API_KEY`` or ``GEMINI_API_KEY`` — required when using Gemini
  ``GEMINI_MODEL`` — optional, default ``gemini-2.0-flash`` (override e.g. ``gemini-1.5-flash``)
"""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Tuple

from app.content import VariantContent
from app.llm_utils import strip_markdown_code_fences
from app.segments import SEGMENT_DESCRIPTIONS

logger = logging.getLogger(__name__)


def parse_llm_variant_json(raw: str, expected: int) -> List[VariantContent]:
    """Parse a JSON array of variant objects from an LLM response.

    Strips optional ```json fences.  Returns at most *expected* items.
    """
    raw = strip_markdown_code_fences(raw)
    try:
        items: List[Dict[str, Any]] = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Failed to parse LLM response as JSON, returning empty list")
        return []

    results: List[VariantContent] = []
    for i, item in enumerate(items[:expected]):
        results.append(
            VariantContent(
                headline=str(item.get("headline", "")).strip() or "Untitled",
                subtitle=str(item.get("subtitle", "")).strip(),
                cta_text=str(item.get("cta_text", "Shop Now")).strip(),
                trust_signals=[str(s) for s in item.get("trust_signals", [])],
                style_class=f"variant-{'abc'[i % 3]}",
            )
        )
    return results


class CopyGenerator(ABC):
    """Protocol every backend must implement."""

    @abstractmethod
    def generate(
        self,
        product: str,
        reviews: List[str],
        segment: str,
        *,
        num_variants: int = 3,
    ) -> List[VariantContent]:
        ...


class MockCopyGenerator(CopyGenerator):
    """Deterministic stub that returns canned copy keyed by segment.

    Useful for tests, offline demos, and CI pipelines where no API key is
    available.
    """

    _TEMPLATES: Dict[str, Dict[str, str]] = {
        "new_mobile_paid": {
            "headline": "Upgrade your {product} game — trusted by thousands",
            "subtitle": "Tap to explore what creators are loving right now.",
            "cta_text": "Shop Trending",
        },
        "new_desktop_direct": {
            "headline": "The {product} setup professionals swear by",
            "subtitle": "Engineered for focus. Designed for your desk.",
            "cta_text": "Explore Now",
        },
        "returning_any": {
            "headline": "Welcome back — fresh {product} picks for you",
            "subtitle": "Based on what you loved last time.",
            "cta_text": "See New Arrivals",
        },
        "price_sensitive": {
            "headline": "{product} bundles starting at $29",
            "subtitle": "Premium quality without the premium price.",
            "cta_text": "Grab the Deal",
        },
        "default": {
            "headline": "Discover the best {product} for your workflow",
            "subtitle": "Curated picks for every work style.",
            "cta_text": "Browse Collection",
        },
    }

    def generate(
        self,
        product: str,
        reviews: List[str],
        segment: str,
        *,
        num_variants: int = 3,
    ) -> List[VariantContent]:
        tpl = self._TEMPLATES.get(segment, self._TEMPLATES["default"])
        results: List[VariantContent] = []
        for i in range(num_variants):
            suffix = "" if i == 0 else f" #{i + 1}"
            results.append(
                VariantContent(
                    headline=tpl["headline"].format(product=product) + suffix,
                    subtitle=tpl["subtitle"],
                    cta_text=tpl["cta_text"],
                    trust_signals=["AI-generated copy", f"Variant {i + 1} of {num_variants}"],
                    style_class=f"variant-{'abc'[i % 3]}",
                )
            )
        return results


def _build_copy_prompt(product: str, reviews: List[str], segment: str, num_variants: int) -> str:
    seg_desc = SEGMENT_DESCRIPTIONS.get(segment, segment)
    reviews_block = "\n".join(f"- {r}" for r in reviews[:5]) if reviews else "(no reviews)"
    return (
        f"You are a direct-response copywriter for a Shopify store.\n\n"
        f"Product: {product}\n"
        f"Target visitor segment: {seg_desc}\n\n"
        f"Customer reviews for tone inspiration:\n{reviews_block}\n\n"
        f"Generate exactly {num_variants} hero-banner copy variants.  "
        f"Each variant must have: headline (≤12 words), subtitle (≤20 words), "
        f"cta_text (≤4 words), and 2-3 trust_signals (short phrases).\n\n"
        f"Respond ONLY with a JSON array of objects with keys: "
        f"headline, subtitle, cta_text, trust_signals (array of strings).\n"
    )


class GeminiCopyGenerator(CopyGenerator):
    """Calls Google Gemini to generate structured JSON copy variants."""

    def __init__(self, model: str | None = None) -> None:
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise ImportError(
                "pip install google-genai to use GeminiCopyGenerator"
            ) from exc

        api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError(
                "Set GOOGLE_API_KEY or GEMINI_API_KEY for Gemini copy generation"
            )

        self._client = genai.Client(api_key=api_key)
        self._model_name = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        self._config = types.GenerateContentConfig(
            responseMimeType="application/json",
            responseSchema={
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "headline": {"type": "string"},
                        "subtitle": {"type": "string"},
                        "cta_text": {"type": "string"},
                        "trust_signals": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                },
            },
            temperature=0.8,
            maxOutputTokens=1024,
        )

    def generate(
        self,
        product: str,
        reviews: List[str],
        segment: str,
        *,
        num_variants: int = 3,
    ) -> List[VariantContent]:
        prompt = _build_copy_prompt(product, reviews, segment, num_variants)
        try:
            response = self._client.models.generate_content(
                model=self._model_name,
                contents=prompt,
                config=self._config,
            )
        except Exception:
            logger.exception("Gemini generate_content failed")
            return []

        try:
            raw = (response.text or "").strip()
        except ValueError:
            # Blocked or empty candidates
            logger.warning("Gemini returned no text (safety filter or empty response)")
            return []

        if not raw:
            return []

        return parse_llm_variant_json(raw, num_variants)


class CachedCopyGenerator(CopyGenerator):
    """Wrapper that caches results by ``(product, segment)`` to avoid
    redundant LLM calls during a server lifetime."""

    def __init__(self, inner: CopyGenerator) -> None:
        self._inner = inner
        self._cache: Dict[Tuple[str, str], List[VariantContent]] = {}

    def generate(
        self,
        product: str,
        reviews: List[str],
        segment: str,
        *,
        num_variants: int = 3,
    ) -> List[VariantContent]:
        key = (product, segment)
        if key in self._cache:
            logger.debug("Cache hit for %s", key)
            return self._cache[key]
        result = self._inner.generate(product, reviews, segment, num_variants=num_variants)
        self._cache[key] = result
        return result

    @property
    def cache_size(self) -> int:
        return len(self._cache)


def create_generator() -> CopyGenerator:
    """Factory: pick backend from ``COPY_GENERATOR_BACKEND`` env var."""
    backend = os.environ.get("COPY_GENERATOR_BACKEND", "mock").lower()

    # Back-compat: old docs mentioned "openai"
    if backend == "openai":
        logger.warning(
            "COPY_GENERATOR_BACKEND=openai is deprecated; use COPY_GENERATOR_BACKEND=gemini"
        )
        backend = "gemini"

    if backend == "gemini":
        try:
            inner = GeminiCopyGenerator()
        except (ValueError, ImportError) as exc:
            logger.warning(
                "COPY_GENERATOR_BACKEND=gemini but Gemini is unavailable (%s); using mock",
                exc,
            )
            inner = MockCopyGenerator()
    else:
        inner = MockCopyGenerator()

    return CachedCopyGenerator(inner)
