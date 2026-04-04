from __future__ import annotations

import random
from collections import Counter

from app.bandit import ArmStats, SegmentedThompsonSampler, ThompsonSampler


class TestThompsonSampler:
    def test_choose_returns_valid_variant(self) -> None:
        stats = {"A": ArmStats(), "B": ArmStats(), "C": ArmStats()}
        sampler = ThompsonSampler(rng=random.Random(0))
        variant, score = sampler.choose(stats)
        assert variant in stats
        assert 0.0 <= score <= 1.0

    def test_biased_arm_gets_chosen_more(self) -> None:
        stats = {
            "A": ArmStats(impressions=100, successes=80, failures=20),
            "B": ArmStats(impressions=100, successes=5, failures=95),
        }
        sampler = ThompsonSampler(rng=random.Random(42))
        picks = Counter(sampler.choose(stats)[0] for _ in range(200))
        assert picks["A"] > picks["B"]


class TestSegmentedThompsonSampler:
    def _make(self, **kwargs) -> SegmentedThompsonSampler:
        defaults = dict(variants=["A", "B", "C"], min_samples=20, rng=random.Random(7))
        defaults.update(kwargs)
        return SegmentedThompsonSampler(**defaults)

    def test_cold_segment_blends_with_global(self) -> None:
        """A new segment with no traffic should still return valid choices."""
        sampler = self._make()
        variant, score = sampler.choose("brand_new_segment")
        assert variant in ("A", "B", "C")
        assert 0.0 <= score <= 1.0

    def test_update_records_in_both_segment_and_global(self) -> None:
        sampler = self._make()
        sampler.update("seg1", "A", 1)
        sampler.update("seg1", "A", 0)

        seg = sampler.segment_stats("seg1")
        assert seg["A"].impressions == 2
        assert seg["A"].successes == 1
        assert seg["A"].failures == 1

        glob = sampler.global_stats()
        assert glob["A"].impressions == 2

    def test_two_segments_diverge_after_biased_feedback(self) -> None:
        sampler = self._make(min_samples=5)
        for _ in range(50):
            sampler.update("mobile", "A", 1)
            sampler.update("mobile", "B", 0)
            sampler.update("desktop", "B", 1)
            sampler.update("desktop", "A", 0)

        mobile_picks = Counter(sampler.choose("mobile")[0] for _ in range(100))
        desktop_picks = Counter(sampler.choose("desktop")[0] for _ in range(100))

        assert mobile_picks["A"] > mobile_picks["B"]
        assert desktop_picks["B"] > desktop_picks["A"]

    def test_min_samples_threshold(self) -> None:
        sampler = self._make(min_samples=10)
        # Feed 5 impressions (below threshold) — should blend with global
        for _ in range(5):
            sampler.update("cold", "A", 1)

        seg = sampler.segment_stats("cold")
        total = sum(a.impressions for a in seg.values())
        assert total < sampler.min_samples

        # Still produces a valid choice
        variant, _ = sampler.choose("cold")
        assert variant in ("A", "B", "C")

    def test_all_segments_excludes_global(self) -> None:
        sampler = self._make()
        sampler.update("seg_x", "A", 1)
        sampler.update("seg_y", "B", 0)

        segments = sampler.all_segments()
        assert "seg_x" in segments
        assert "seg_y" in segments
        assert "__global__" not in segments

    def test_deterministic_with_seed(self) -> None:
        choices_a = []
        choices_b = []
        for seed in (99, 99):
            s = SegmentedThompsonSampler(
                variants=["A", "B", "C"], min_samples=20, rng=random.Random(seed)
            )
            target = choices_a if len(choices_a) == 0 else choices_b
            for _ in range(30):
                target.append(s.choose("seg")[0])
        assert choices_a == choices_b
