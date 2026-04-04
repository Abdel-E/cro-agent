from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Sequence


@dataclass
class ArmStats:
    impressions: int = 0
    successes: int = 0
    failures: int = 0


class ThompsonSampler:
    """Single-segment Thompson sampling over Bernoulli arms."""

    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random()

    def choose(self, stats: Dict[str, ArmStats]) -> tuple[str, float]:
        best_variant = ""
        best_sample = -1.0

        for variant_id, arm in stats.items():
            alpha = arm.successes + 1
            beta = arm.failures + 1
            sample = self.rng.betavariate(alpha, beta)
            if sample > best_sample:
                best_variant = variant_id
                best_sample = sample

        return best_variant, best_sample


_GLOBAL_SEGMENT = "__global__"


class SegmentedThompsonSampler:
    """Thompson sampling with independent posteriors per visitor segment.

    Each (segment, variant) pair maintains its own Beta posterior.  When a
    segment has fewer than *min_samples* total impressions the sampler blends
    segment-specific posteriors with the global posterior to avoid noisy
    early decisions.
    """

    def __init__(
        self,
        variants: Sequence[str],
        *,
        min_samples: int = 20,
        rng: random.Random | None = None,
    ) -> None:
        self.variants = list(variants)
        self.min_samples = min_samples
        self.rng = rng or random.Random()
        self._sampler = ThompsonSampler(self.rng)

        self._stats: Dict[str, Dict[str, ArmStats]] = defaultdict(
            lambda: {v: ArmStats() for v in self.variants}
        )
        # Eagerly initialise the global bucket
        _ = self._stats[_GLOBAL_SEGMENT]

    # -- public API --------------------------------------------------------

    def choose(self, segment: str) -> tuple[str, float]:
        """Pick a variant for *segment*, blending with global when cold."""
        seg_stats = self._stats[segment]
        total_impressions = sum(a.impressions for a in seg_stats.values())

        if total_impressions >= self.min_samples:
            return self._sampler.choose(seg_stats)

        # Blend: merge segment counts into global counts so the posterior
        # is warmed by traffic from all segments while still incorporating
        # whatever local evidence exists.
        global_stats = self._stats[_GLOBAL_SEGMENT]
        blended: Dict[str, ArmStats] = {}
        for v in self.variants:
            g = global_stats[v]
            s = seg_stats[v]
            blended[v] = ArmStats(
                impressions=g.impressions + s.impressions,
                successes=g.successes + s.successes,
                failures=g.failures + s.failures,
            )
        return self._sampler.choose(blended)

    def update(self, segment: str, variant_id: str, reward: int) -> None:
        """Record a reward for *variant_id* in both segment and global stats."""
        for key in (segment, _GLOBAL_SEGMENT):
            arm = self._stats[key][variant_id]
            arm.impressions += 1
            if reward == 1:
                arm.successes += 1
            else:
                arm.failures += 1

    # -- introspection -----------------------------------------------------

    def segment_stats(self, segment: str) -> Dict[str, ArmStats]:
        return dict(self._stats[segment])

    def global_stats(self) -> Dict[str, ArmStats]:
        return dict(self._stats[_GLOBAL_SEGMENT])

    def all_segments(self) -> List[str]:
        """Return segment IDs that have received at least one impression."""
        return [
            s
            for s, arms in self._stats.items()
            if s != _GLOBAL_SEGMENT and any(a.impressions > 0 for a in arms.values())
        ]
