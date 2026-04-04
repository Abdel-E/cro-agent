"""Visitor-context → segment classifier.

Maps raw request context (device type, traffic source, returning flag, etc.)
into a discrete segment ID consumed by the contextual bandit.

All rules are deterministic and side-effect-free so the classifier is trivially
testable and reproducible across backend / simulator boundaries.
"""

from __future__ import annotations

from typing import Any, Dict, List

SEGMENT_NEW_MOBILE_PAID = "new_mobile_paid"
SEGMENT_NEW_DESKTOP_DIRECT = "new_desktop_direct"
SEGMENT_RETURNING = "returning_any"
SEGMENT_PRICE_SENSITIVE = "price_sensitive"
SEGMENT_DEFAULT = "default"

ALL_SEGMENTS: List[str] = [
    SEGMENT_NEW_MOBILE_PAID,
    SEGMENT_NEW_DESKTOP_DIRECT,
    SEGMENT_RETURNING,
    SEGMENT_PRICE_SENSITIVE,
    SEGMENT_DEFAULT,
]

SEGMENT_DESCRIPTIONS: Dict[str, str] = {
    SEGMENT_NEW_MOBILE_PAID: "First-time mobile visitor from paid ads (Meta / Google)",
    SEGMENT_NEW_DESKTOP_DIRECT: "First-time desktop visitor via direct or organic traffic",
    SEGMENT_RETURNING: "Returning visitor on any device or traffic source",
    SEGMENT_PRICE_SENSITIVE: "Visitor flagged as price-sensitive (UTM or explicit hint)",
    SEGMENT_DEFAULT: "Visitor that does not match any specific segment rule",
}

_PAID_SOURCES = frozenset({"meta", "google", "tiktok", "paid", "cpc"})


def classify(context: Dict[str, Any]) -> str:
    """Return a segment ID for the given visitor context.

    Priority order (first match wins):
      1. Explicit ``segment_hint`` override
      2. ``is_returning`` flag
      3. Price-sensitive inference from ``utm_campaign``
      4. Device + traffic-source combination
      5. ``"default"`` fallback
    """
    if not context:
        return SEGMENT_DEFAULT

    hint = str(context.get("segment_hint") or "").strip().lower()
    if hint and hint in ALL_SEGMENTS:
        return hint

    is_returning = context.get("is_returning", False)
    if is_returning is True or str(is_returning).lower() == "true":
        return SEGMENT_RETURNING

    utm = str(context.get("utm_campaign") or "").lower()
    if "discount" in utm or "sale" in utm or "price" in utm:
        return SEGMENT_PRICE_SENSITIVE

    device = str(context.get("device_type") or "").lower()
    source = str(context.get("traffic_source") or "").lower()

    is_mobile = device in ("mobile", "tablet")
    is_paid = source in _PAID_SOURCES

    if is_mobile and is_paid:
        return SEGMENT_NEW_MOBILE_PAID

    if not is_mobile and source in ("direct", "organic", ""):
        return SEGMENT_NEW_DESKTOP_DIRECT

    return SEGMENT_DEFAULT
