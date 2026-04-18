"""Contextual traffic simulator for the CRO personalization agent.

Generates diverse visitor profiles with segment-specific true CTRs and
feeds them through the /decide → /feedback loop.  The resulting CSV
captures per-session decisions alongside a uniform-random baseline for
comparison.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import requests

# ── Default visitor profiles ─────────────────────────────────────────────

DEFAULT_PROFILES: List[Dict[str, Any]] = [
    {
        "segment": "new_mobile_paid",
        "weight": 0.30,
        "context": {"device_type": "mobile", "traffic_source": "meta", "is_returning": False},
        "ctrs": {"A": 0.01, "B": 0.03, "C": 0.05},
    },
    {
        "segment": "high_intent_search",
        "weight": 0.20,
        "context": {"device_type": "desktop", "traffic_source": "organic", "is_returning": False},
        "ctrs": {"A": 0.03, "B": 0.06, "C": 0.04},
    },
    {
        "segment": "new_desktop_direct",
        "weight": 0.20,
        "context": {"device_type": "desktop", "traffic_source": "direct", "is_returning": False},
        "ctrs": {"A": 0.04, "B": 0.02, "C": 0.01},
    },
    {
        "segment": "returning_any",
        "weight": 0.15,
        "context": {"device_type": "desktop", "traffic_source": "direct", "is_returning": True},
        "ctrs": {"A": 0.02, "B": 0.05, "C": 0.03},
    },
    {
        "segment": "price_sensitive",
        "weight": 0.10,
        "context": {"device_type": "mobile", "traffic_source": "google", "utm_campaign": "summer_discount", "is_returning": False},
        "ctrs": {"A": 0.01, "B": 0.01, "C": 0.06},
    },
    {
        "segment": "default",
        "weight": 0.05,
        "context": {"device_type": "mobile", "traffic_source": "email", "is_returning": False},
        "ctrs": {"A": 0.02, "B": 0.02, "C": 0.02},
    },
]


@dataclass
class SimulationStats:
    bandit_reward: int = 0
    baseline_reward: int = 0
    completed_sessions: int = 0
    failed_decides: int = 0
    failed_feedback: int = 0
    selection_counts: Dict[str, int] = field(default_factory=dict)
    segment_counts: Dict[str, int] = field(default_factory=dict)


def load_profiles(path: str | None) -> List[Dict[str, Any]]:
    if not path:
        return DEFAULT_PROFILES
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def sample_profile(profiles: List[Dict[str, Any]], rng: random.Random) -> Dict[str, Any]:
    weights = [p["weight"] for p in profiles]
    return rng.choices(profiles, weights=weights, k=1)[0]


def choose_uniform_variant(variants: List[str], rng: random.Random) -> str:
    return variants[rng.randrange(len(variants))]


def write_run_metadata(
    output_file: Path,
    *,
    base_url: str,
    requested_sessions: int,
    seed: int,
    profiles_path: str | None,
    uniform_baseline: bool,
    profiles: List[Dict[str, Any]],
    variants: List[str],
    stats: SimulationStats,
) -> Path:
    metadata_file = output_file.with_suffix(".meta.json")
    payload = {
        "csv_file": output_file.name,
        "base_url": base_url,
        "sessions_requested": requested_sessions,
        "sessions_completed": stats.completed_sessions,
        "seed": seed,
        "profiles_source": profiles_path or "DEFAULT_PROFILES",
        "uniform_baseline": uniform_baseline,
        "variants": variants,
        "profiles": profiles,
        "failed_decides": stats.failed_decides,
        "failed_feedback": stats.failed_feedback,
        "bandit_reward": stats.bandit_reward,
        "baseline_reward": stats.baseline_reward,
    }
    metadata_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return metadata_file


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run contextual traffic simulation against the bandit API",
    )
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--sessions", type=int, default=5000)
    parser.add_argument("--profiles", default=None, help="Path to profiles JSON file")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--uniform-baseline", action="store_true")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    profiles = load_profiles(args.profiles)

    all_variants = sorted({v for p in profiles for v in p["ctrs"]})

    output_dir = Path(__file__).resolve().parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"simulation_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"

    decide_url = f"{args.base_url.rstrip('/')}/decide"
    feedback_url = f"{args.base_url.rstrip('/')}/feedback"

    stats = SimulationStats(
        selection_counts={v: 0 for v in all_variants},
        segment_counts={p["segment"]: 0 for p in profiles},
    )

    header = [
        "session", "segment", "variant", "reward",
        "cumulative_bandit_reward",
        "device_type", "traffic_source", "is_returning",
        "baseline_variant", "baseline_reward", "cumulative_baseline_reward",
    ]

    with output_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)

        for session in range(1, args.sessions + 1):
            profile = sample_profile(profiles, rng)
            segment = profile["segment"]
            ctx = dict(profile["context"])
            stats.segment_counts[segment] = stats.segment_counts.get(segment, 0) + 1

            try:
                resp = requests.post(
                    decide_url,
                    json={"surface_id": "hero_banner", "context": ctx},
                    timeout=5,
                )
                resp.raise_for_status()
                decision = resp.json()
            except requests.RequestException as exc:
                stats.failed_decides += 1
                print(f"[session {session}] /decide failed: {exc}", file=sys.stderr)
                continue

            variant_id = decision["variant_id"]
            stats.selection_counts[variant_id] = stats.selection_counts.get(variant_id, 0) + 1

            true_ctr = profile["ctrs"].get(variant_id, 0.02)
            reward = 1 if rng.random() < true_ctr else 0
            stats.bandit_reward += reward

            try:
                fb_resp = requests.post(
                    feedback_url,
                    json={
                        "decision_id": decision["decision_id"],
                        "variant_id": variant_id,
                        "reward": reward,
                    },
                    timeout=5,
                )
                fb_resp.raise_for_status()
            except requests.RequestException as exc:
                stats.failed_feedback += 1
                print(f"[session {session}] /feedback failed: {exc}", file=sys.stderr)

            baseline_variant = ""
            baseline_event: int | str = ""
            baseline_cumulative: int | str = ""
            if args.uniform_baseline:
                baseline_variant = choose_uniform_variant(all_variants, rng)
                bl_ctr = profile["ctrs"].get(baseline_variant, 0.02)
                bl_reward = 1 if rng.random() < bl_ctr else 0
                stats.baseline_reward += bl_reward
                baseline_event = bl_reward
                baseline_cumulative = stats.baseline_reward

            writer.writerow([
                session, segment, variant_id, reward,
                stats.bandit_reward,
                ctx.get("device_type", ""), ctx.get("traffic_source", ""),
                ctx.get("is_returning", False),
                baseline_variant, baseline_event, baseline_cumulative,
            ])
            stats.completed_sessions += 1

            if session % 500 == 0:
                print(f"  ... {session}/{args.sessions} sessions")

    metadata_file = write_run_metadata(
        output_file,
        base_url=args.base_url.rstrip("/"),
        requested_sessions=args.sessions,
        seed=args.seed,
        profiles_path=args.profiles,
        uniform_baseline=args.uniform_baseline,
        profiles=profiles,
        variants=all_variants,
        stats=stats,
    )

    print(f"\nSimulation complete — requested {args.sessions} sessions")
    print(f"Completed sessions:  {stats.completed_sessions}")
    print(f"Segment distribution: {dict(stats.segment_counts)}")
    print(f"Selection counts:     {dict(stats.selection_counts)}")
    print(f"Bandit cumulative reward: {stats.bandit_reward}")
    if args.uniform_baseline:
        print(f"Baseline cumulative reward: {stats.baseline_reward}")
        print(f"Reward lift: {stats.bandit_reward - stats.baseline_reward}")
    if stats.failed_decides or stats.failed_feedback:
        print(
            "Warnings:"
            f" failed /decide={stats.failed_decides},"
            f" failed /feedback={stats.failed_feedback}"
        )
    print(f"Output: {output_file}")
    print(f"Metadata: {metadata_file}")


if __name__ == "__main__":
    main()
