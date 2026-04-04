"""Content registry — maps (variant_id, segment) to a displayable content bundle.

The registry is the single source of truth for what headline, subtitle, CTA,
trust signals and visual style a given variant should show for a particular
visitor segment.  Content is data, not code: the entire registry is
JSON-serialisable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from app.segments import (
    ALL_SEGMENTS,
    SEGMENT_DEFAULT,
    SEGMENT_NEW_DESKTOP_DIRECT,
    SEGMENT_NEW_MOBILE_PAID,
    SEGMENT_PRICE_SENSITIVE,
    SEGMENT_RETURNING,
)

VARIANTS: List[str] = ["A", "B", "C"]


@dataclass(frozen=True)
class VariantContent:
    headline: str
    subtitle: str
    cta_text: str
    trust_signals: List[str] = field(default_factory=list)
    style_class: str = "variant-a"

    def to_dict(self) -> Dict[str, object]:
        return {
            "headline": self.headline,
            "subtitle": self.subtitle,
            "cta_text": self.cta_text,
            "trust_signals": list(self.trust_signals),
            "style_class": self.style_class,
        }


class ContentRegistry:
    """Thread-safe lookup of ``(variant_id, segment) → VariantContent``.

    Falls back to ``(variant_id, "default")`` when a segment-specific entry
    is not registered.
    """

    def __init__(self) -> None:
        self._store: Dict[Tuple[str, str], VariantContent] = {}

    def register(self, variant_id: str, segment: str, content: VariantContent) -> None:
        self._store[(variant_id, segment)] = content

    def get(self, variant_id: str, segment: str) -> Optional[VariantContent]:
        content = self._store.get((variant_id, segment))
        if content is not None:
            return content
        return self._store.get((variant_id, SEGMENT_DEFAULT))

    def all_variant_ids(self) -> List[str]:
        seen: dict[str, None] = {}
        for vid, _ in self._store:
            seen.setdefault(vid, None)
        return list(seen)

    def __len__(self) -> int:
        return len(self._store)


def build_default_registry() -> ContentRegistry:
    """Pre-populate a registry with handcrafted content for 3 variants × 5 segments."""
    reg = ContentRegistry()

    # ── Variant A: balanced, product-focused ──────────────────────────
    reg.register("A", SEGMENT_DEFAULT, VariantContent(
        headline="Build your desk for peak focus",
        subtitle="Curated bundles for creators, builders, and operators.",
        cta_text="Shop Now",
        trust_signals=["Free shipping over $50", "30-day returns"],
        style_class="variant-a",
    ))
    reg.register("A", SEGMENT_NEW_MOBILE_PAID, VariantContent(
        headline="Your workspace upgrade starts here",
        subtitle="Top-rated bundles — trusted by 2,300+ creators.",
        cta_text="Shop Now",
        trust_signals=["Free shipping", "30-day money-back guarantee", "4.8★ (2,340 reviews)"],
        style_class="variant-a",
    ))
    reg.register("A", SEGMENT_NEW_DESKTOP_DIRECT, VariantContent(
        headline="Build your desk for peak focus",
        subtitle="Curated bundles designed for deep work sessions.",
        cta_text="Explore Bundles",
        trust_signals=["Premium materials", "2-year warranty"],
        style_class="variant-a",
    ))
    reg.register("A", SEGMENT_RETURNING, VariantContent(
        headline="Welcome back — new arrivals just dropped",
        subtitle="Fresh picks based on what you loved last time.",
        cta_text="See What's New",
        trust_signals=["Loyalty reward available", "Free shipping on your next order"],
        style_class="variant-a",
    ))
    reg.register("A", SEGMENT_PRICE_SENSITIVE, VariantContent(
        headline="Workspace bundles from $29",
        subtitle="Same quality, smaller price tag — limited-time bundles.",
        cta_text="Grab the Deal",
        trust_signals=["Price-match guarantee", "Free returns", "Pay in 4 with Shop Pay"],
        style_class="variant-a",
    ))

    # ── Variant B: social-proof heavy ─────────────────────────────────
    reg.register("B", SEGMENT_DEFAULT, VariantContent(
        headline="Work better with one intentional upgrade",
        subtitle="Top-rated setup picks chosen to increase confidence to buy.",
        cta_text="See Bundles",
        trust_signals=["4.8★ average rating", "12,000+ happy customers"],
        style_class="variant-b",
    ))
    reg.register("B", SEGMENT_NEW_MOBILE_PAID, VariantContent(
        headline="Seen on Instagram — now in your hands",
        subtitle="The workspace bundles creators are raving about.",
        cta_text="See What's Trending",
        trust_signals=["As seen in @workfromhome", "Free 2-day shipping", "4.9★ on Trustpilot"],
        style_class="variant-b",
    ))
    reg.register("B", SEGMENT_NEW_DESKTOP_DIRECT, VariantContent(
        headline="Join 12,000+ professionals who upgraded",
        subtitle="Real reviews, real setups — see why they switched.",
        cta_text="Read Reviews",
        trust_signals=["Verified buyer reviews", "Featured in Wirecutter"],
        style_class="variant-b",
    ))
    reg.register("B", SEGMENT_RETURNING, VariantContent(
        headline="Still thinking about it? Others didn't wait",
        subtitle="247 people bought this bundle in the last 7 days.",
        cta_text="Complete Your Setup",
        trust_signals=["Selling fast", "Your cart is saved"],
        style_class="variant-b",
    ))
    reg.register("B", SEGMENT_PRICE_SENSITIVE, VariantContent(
        headline="Best value bundles — rated 4.8★",
        subtitle="Don't overpay. Our bundles save you 35% vs buying separately.",
        cta_text="Compare & Save",
        trust_signals=["35% bundle savings", "Price-match guarantee", "12,000+ sold"],
        style_class="variant-b",
    ))

    # ── Variant C: urgency / scarcity ─────────────────────────────────
    reg.register("C", SEGMENT_DEFAULT, VariantContent(
        headline="Upgrade your workflow in under 60 seconds",
        subtitle="A sharper message and CTA to boost click intent.",
        cta_text="Claim Deal",
        trust_signals=["Limited stock", "Sale ends tonight"],
        style_class="variant-c",
    ))
    reg.register("C", SEGMENT_NEW_MOBILE_PAID, VariantContent(
        headline="Flash sale — 40% off workspace bundles",
        subtitle="Ends in 2 hours. Tap now, upgrade today.",
        cta_text="Claim 40% Off",
        trust_signals=["⏰ 2 hours left", "Free express shipping", "Only 18 left"],
        style_class="variant-c",
    ))
    reg.register("C", SEGMENT_NEW_DESKTOP_DIRECT, VariantContent(
        headline="Your ideal setup is one click away",
        subtitle="Handpicked bundles. Ships tomorrow if you order now.",
        cta_text="Order Now",
        trust_signals=["Ships tomorrow", "Free returns within 30 days"],
        style_class="variant-c",
    ))
    reg.register("C", SEGMENT_RETURNING, VariantContent(
        headline="We saved your picks — but stock is running low",
        subtitle="3 items in your wishlist are almost gone.",
        cta_text="Buy Before It's Gone",
        trust_signals=["Only 5 left in stock", "10% returning-customer discount applied"],
        style_class="variant-c",
    ))
    reg.register("C", SEGMENT_PRICE_SENSITIVE, VariantContent(
        headline="Today only — extra 15% off clearance bundles",
        subtitle="Stack your discount. Best prices we've ever offered.",
        cta_text="Shop Clearance",
        trust_signals=["Extra 15% off at checkout", "Lowest price guarantee", "⏰ Today only"],
        style_class="variant-c",
    ))

    return reg
