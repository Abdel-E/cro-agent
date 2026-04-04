from app.content import ContentRegistry, VariantContent, build_default_registry
from app.segments import ALL_SEGMENTS, SEGMENT_DEFAULT


class TestVariantContent:
    def test_to_dict_round_trip(self) -> None:
        vc = VariantContent(
            headline="H", subtitle="S", cta_text="C",
            trust_signals=["a", "b"], style_class="variant-x",
        )
        d = vc.to_dict()
        assert d["headline"] == "H"
        assert d["trust_signals"] == ["a", "b"]


class TestContentRegistry:
    def test_get_known_entry(self) -> None:
        reg = ContentRegistry()
        content = VariantContent(headline="Hi", subtitle="Sub", cta_text="Click")
        reg.register("A", "seg1", content)
        assert reg.get("A", "seg1") is content

    def test_fallback_to_default_segment(self) -> None:
        reg = ContentRegistry()
        default = VariantContent(headline="Default", subtitle="", cta_text="Go")
        reg.register("A", SEGMENT_DEFAULT, default)
        assert reg.get("A", "unknown_segment") is default

    def test_returns_none_when_no_default(self) -> None:
        reg = ContentRegistry()
        assert reg.get("Z", "missing") is None

    def test_register_overwrites(self) -> None:
        reg = ContentRegistry()
        v1 = VariantContent(headline="Old", subtitle="", cta_text="")
        v2 = VariantContent(headline="New", subtitle="", cta_text="")
        reg.register("A", "seg", v1)
        reg.register("A", "seg", v2)
        assert reg.get("A", "seg") is v2

    def test_all_variant_ids(self) -> None:
        reg = ContentRegistry()
        reg.register("X", "s", VariantContent(headline="", subtitle="", cta_text=""))
        reg.register("Y", "s", VariantContent(headline="", subtitle="", cta_text=""))
        assert set(reg.all_variant_ids()) == {"X", "Y"}


class TestDefaultRegistry:
    def test_all_variants_and_segments_populated(self) -> None:
        reg = build_default_registry()
        for variant in ("A", "B", "C"):
            for segment in ALL_SEGMENTS:
                content = reg.get(variant, segment)
                assert content is not None, f"Missing ({variant}, {segment})"
                assert content.headline, f"Empty headline for ({variant}, {segment})"
                assert content.cta_text, f"Empty CTA for ({variant}, {segment})"

    def test_registry_size(self) -> None:
        reg = build_default_registry()
        assert len(reg) == 15  # 3 variants × 5 segments
