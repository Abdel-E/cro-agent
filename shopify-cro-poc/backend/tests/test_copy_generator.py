from app.copy_generator import (
    CachedCopyGenerator,
    MockCopyGenerator,
    parse_llm_variant_json,
)


class TestMockCopyGenerator:
    def test_returns_requested_count(self) -> None:
        gen = MockCopyGenerator()
        results = gen.generate("leather bags", [], "default", num_variants=3)
        assert len(results) == 3

    def test_all_fields_populated(self) -> None:
        gen = MockCopyGenerator()
        for vc in gen.generate("desk lamp", [], "new_mobile_paid"):
            assert vc.headline
            assert vc.subtitle
            assert vc.cta_text
            assert len(vc.trust_signals) >= 1

    def test_product_name_injected(self) -> None:
        gen = MockCopyGenerator()
        results = gen.generate("standing desk", [], "returning_any")
        assert "standing desk" in results[0].headline.lower()

    def test_unknown_segment_uses_default(self) -> None:
        gen = MockCopyGenerator()
        results = gen.generate("monitor", [], "nonexistent")
        assert len(results) > 0
        assert results[0].headline


class TestCachedCopyGenerator:
    def test_cache_hit_avoids_second_call(self) -> None:
        inner = MockCopyGenerator()
        cached = CachedCopyGenerator(inner)

        first = cached.generate("keyboard", [], "default")
        second = cached.generate("keyboard", [], "default")
        assert first == second
        assert cached.cache_size == 1

    def test_different_segment_is_cache_miss(self) -> None:
        cached = CachedCopyGenerator(MockCopyGenerator())
        cached.generate("keyboard", [], "default")
        cached.generate("keyboard", [], "returning_any")
        assert cached.cache_size == 2


class TestParseLlmVariantJson:
    def test_valid_json_parsed(self) -> None:
        raw = '[{"headline":"H","subtitle":"S","cta_text":"C","trust_signals":["a"]}]'
        results = parse_llm_variant_json(raw, 3)
        assert len(results) == 1
        assert results[0].headline == "H"

    def test_markdown_fenced_json(self) -> None:
        raw = '```json\n[{"headline":"X","subtitle":"Y","cta_text":"Z","trust_signals":[]}]\n```'
        results = parse_llm_variant_json(raw, 3)
        assert len(results) == 1
        assert results[0].headline == "X"

    def test_malformed_json_returns_empty(self) -> None:
        results = parse_llm_variant_json("not json at all", 3)
        assert results == []

    def test_truncates_to_expected_count(self) -> None:
        raw = (
            '[{"headline":"A","subtitle":"","cta_text":"","trust_signals":[]},'
            '{"headline":"B","subtitle":"","cta_text":"","trust_signals":[]},'
            '{"headline":"C","subtitle":"","cta_text":"","trust_signals":[]},'
            '{"headline":"D","subtitle":"","cta_text":"","trust_signals":[]}]'
        )
        results = parse_llm_variant_json(raw, 2)
        assert len(results) == 2
