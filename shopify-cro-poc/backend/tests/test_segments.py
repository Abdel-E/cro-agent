from app.segments import (
    ALL_SEGMENTS,
    SEGMENT_DEFAULT,
    SEGMENT_NEW_DESKTOP_DIRECT,
    SEGMENT_NEW_MOBILE_PAID,
    SEGMENT_PRICE_SENSITIVE,
    SEGMENT_RETURNING,
    classify,
)


class TestClassify:
    def test_empty_context_returns_default(self) -> None:
        assert classify({}) == SEGMENT_DEFAULT

    def test_none_device_with_no_source_falls_to_desktop_direct(self) -> None:
        # device_type=None → empty string → not mobile; source="" → direct bucket
        assert classify({"device_type": None}) == SEGMENT_NEW_DESKTOP_DIRECT

    def test_segment_hint_override(self) -> None:
        ctx = {"segment_hint": "price_sensitive", "is_returning": True}
        assert classify(ctx) == SEGMENT_PRICE_SENSITIVE

    def test_invalid_segment_hint_ignored(self) -> None:
        # Invalid hint is ignored; no device/source → desktop+direct bucket
        ctx = {"segment_hint": "nonexistent_segment"}
        assert classify(ctx) == SEGMENT_NEW_DESKTOP_DIRECT

    def test_returning_visitor(self) -> None:
        ctx = {"is_returning": True, "device_type": "mobile", "traffic_source": "meta"}
        assert classify(ctx) == SEGMENT_RETURNING

    def test_returning_string_true(self) -> None:
        assert classify({"is_returning": "true"}) == SEGMENT_RETURNING

    def test_price_sensitive_from_utm(self) -> None:
        ctx = {"utm_campaign": "summer_discount_2026"}
        assert classify(ctx) == SEGMENT_PRICE_SENSITIVE

    def test_new_mobile_paid(self) -> None:
        ctx = {"device_type": "mobile", "traffic_source": "meta"}
        assert classify(ctx) == SEGMENT_NEW_MOBILE_PAID

    def test_tablet_counts_as_mobile(self) -> None:
        ctx = {"device_type": "tablet", "traffic_source": "google"}
        assert classify(ctx) == SEGMENT_NEW_MOBILE_PAID

    def test_new_desktop_direct(self) -> None:
        ctx = {"device_type": "desktop", "traffic_source": "direct"}
        assert classify(ctx) == SEGMENT_NEW_DESKTOP_DIRECT

    def test_desktop_organic(self) -> None:
        ctx = {"device_type": "desktop", "traffic_source": "organic"}
        assert classify(ctx) == SEGMENT_NEW_DESKTOP_DIRECT

    def test_desktop_empty_source_is_direct(self) -> None:
        ctx = {"device_type": "desktop"}
        assert classify(ctx) == SEGMENT_NEW_DESKTOP_DIRECT

    def test_mobile_direct_falls_to_default(self) -> None:
        ctx = {"device_type": "mobile", "traffic_source": "direct"}
        assert classify(ctx) == SEGMENT_DEFAULT

    def test_all_segments_reachable(self) -> None:
        """Every segment in ALL_SEGMENTS can be produced by classify()."""
        contexts = {
            SEGMENT_NEW_MOBILE_PAID: {"device_type": "mobile", "traffic_source": "meta"},
            SEGMENT_NEW_DESKTOP_DIRECT: {"device_type": "desktop", "traffic_source": "direct"},
            SEGMENT_RETURNING: {"is_returning": True},
            SEGMENT_PRICE_SENSITIVE: {"utm_campaign": "big_sale"},
            SEGMENT_DEFAULT: {},
        }
        for expected_segment, ctx in contexts.items():
            assert classify(ctx) == expected_segment, f"Failed for {expected_segment}"

        reached = set(contexts.keys())
        assert reached == set(ALL_SEGMENTS)
