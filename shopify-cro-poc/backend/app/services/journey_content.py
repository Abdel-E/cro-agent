from __future__ import annotations

from typing import Any, Dict

from app.content import VariantContent
from app.funnel import FunnelSurface

STYLE_CLASS_BY_VARIANT: Dict[str, str] = {
    "A": "variant-a",
    "B": "variant-b",
    "C": "variant-c",
}

EXPERIMENT_VARIANT_KEY_MAP: Dict[Any, str] = {
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


def style_class_for_variant(variant_id: str) -> str:
    return STYLE_CLASS_BY_VARIANT.get(variant_id, "variant-a")


def fallback_journey_content(variant_id: str, segment: str) -> VariantContent:
    return VariantContent(
        headline="Personalized content",
        subtitle=f"Optimized for segment '{segment}'.",
        cta_text="Continue",
        trust_signals=["Adaptive optimization"],
        style_class=style_class_for_variant(variant_id),
    )


def build_default_stage_templates() -> Dict[FunnelSurface, Dict[str, VariantContent]]:
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
