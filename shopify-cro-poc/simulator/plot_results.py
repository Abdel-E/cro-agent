"""Generate per-segment charts from contextual simulation CSV output.

Charts produced:
  1. Per-segment allocation share (one subplot per segment)
  2. Per-segment CTR convergence (observed vs true CTR)
  3. Aggregate cumulative reward (bandit vs baseline)
  4. Segment × variant heatmap (final observed CTR)
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

import matplotlib.pyplot as plt
import numpy as np

# ── True CTRs per (segment, variant) for reference lines ─────────────
TRUE_CTRS: Dict[str, Dict[str, float]] = {
    "new_mobile_paid":    {"A": 0.01, "B": 0.03, "C": 0.05},
    "high_intent_search": {"A": 0.03, "B": 0.06, "C": 0.04},
    "new_desktop_direct": {"A": 0.04, "B": 0.02, "C": 0.01},
    "returning_any":      {"A": 0.02, "B": 0.05, "C": 0.03},
    "price_sensitive":    {"A": 0.01, "B": 0.01, "C": 0.06},
    "default":            {"A": 0.02, "B": 0.02, "C": 0.02},
}

BASE_VARIANT_COLORS = {"A": "#2563eb", "B": "#16a34a", "C": "#d97706"}


def latest_csv(output_dir: Path) -> Path:
    files = sorted(output_dir.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f"No CSV files in {output_dir}")
    return files[0]


def load_rows(csv_file: Path) -> List[Dict[str, str]]:
    with csv_file.open("r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_run_metadata(csv_file: Path) -> Dict[str, object]:
    metadata_file = csv_file.with_suffix(".meta.json")
    if not metadata_file.exists():
        return {}
    return json.loads(metadata_file.read_text(encoding="utf-8"))


def discover_variants(rows: List[Dict[str, str]], metadata: Dict[str, object]) -> List[str]:
    from_metadata = [str(v) for v in metadata.get("variants", []) if str(v).strip()]
    if from_metadata:
        return from_metadata

    variants = {
        str(row.get("variant", "")).strip()
        for row in rows
        if str(row.get("variant", "")).strip()
    }
    variants.update(
        str(row.get("baseline_variant", "")).strip()
        for row in rows
        if str(row.get("baseline_variant", "")).strip()
    )
    return sorted(variants)


def build_true_ctrs(metadata: Dict[str, object]) -> Dict[str, Dict[str, float]]:
    profiles = metadata.get("profiles", [])
    if not isinstance(profiles, list):
        return TRUE_CTRS

    derived: Dict[str, Dict[str, float]] = {}
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        segment = str(profile.get("segment", "")).strip()
        ctrs = profile.get("ctrs", {})
        if not segment or not isinstance(ctrs, dict):
            continue
        derived[segment] = {
            str(variant): float(value)
            for variant, value in ctrs.items()
        }
    return derived or TRUE_CTRS


def build_variant_colors(variants: List[str]) -> Dict[str, object]:
    cmap = plt.get_cmap("tab10")
    colors: Dict[str, object] = {}
    for idx, variant in enumerate(variants):
        colors[variant] = BASE_VARIANT_COLORS.get(variant, cmap(idx % 10))
    return colors


def build_plot_subtitle(csv_file: Path, rows: List[Dict[str, str]], metadata: Dict[str, object]) -> str:
    requested = int(metadata.get("sessions_requested", len(rows) or 0))
    completed = int(metadata.get("sessions_completed", len(rows) or 0))
    seed = metadata.get("seed", "n/a")
    baseline = "on" if metadata.get("uniform_baseline") else "off"
    return f"{csv_file.name} | completed {completed}/{requested} sessions | seed={seed} | uniform baseline={baseline}"


# ── Chart 1: Per-segment allocation share ────────────────────────────

def plot_segment_allocation(
    rows: List[Dict[str, str]],
    out: Path,
    *,
    variants: List[str],
    variant_colors: Dict[str, object],
    subtitle: str,
) -> None:
    seg_data: Dict[str, Dict[str, List]] = defaultdict(
        lambda: {"sessions": [], **{variant: [] for variant in variants}}
    )
    seg_counts: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {variant: 0 for variant in variants}
    )
    seg_n: Dict[str, int] = defaultdict(int)

    for row in rows:
        seg = row["segment"]
        var = row["variant"]
        seg_n[seg] += 1
        seg_counts[seg][var] += 1

        n = seg_n[seg]
        seg_data[seg]["sessions"].append(n)
        for v in variants:
            seg_data[seg][v].append(seg_counts[seg][v] / n)

    segments = sorted(seg_data.keys())
    ncols = min(3, len(segments))
    nrows = (len(segments) + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 4 * nrows), squeeze=False)

    for idx, seg in enumerate(segments):
        r, c = divmod(idx, ncols)
        ax = axes[r][c]
        d = seg_data[seg]
        for v in variants:
            ax.plot(d["sessions"], d[v], label=f"Variant {v}", color=variant_colors[v], linewidth=1.2)
        ax.set_title(seg.replace("_", " ").title(), fontsize=11)
        ax.set_ylim(0, 1)
        ax.set_xlabel("Session (within segment)")
        ax.set_ylabel("Allocation share")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.15)

    for idx in range(len(segments), nrows * ncols):
        r, c = divmod(idx, ncols)
        axes[r][c].set_visible(False)

    fig.suptitle("Per-Segment Variant Allocation Share", fontsize=14, y=0.99)
    fig.text(0.5, 0.965, subtitle, ha="center", va="top", fontsize=9)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)


# ── Chart 2: Per-segment CTR convergence ─────────────────────────────

def plot_ctr_convergence(
    rows: List[Dict[str, str]],
    out: Path,
    *,
    variants: List[str],
    variant_colors: Dict[str, object],
    true_ctrs: Dict[str, Dict[str, float]],
    subtitle: str,
) -> None:
    seg_imp: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    seg_suc: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    seg_sessions: Dict[str, List[int]] = defaultdict(list)
    seg_ctr_series: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    seg_n: Dict[str, int] = defaultdict(int)

    for row in rows:
        seg = row["segment"]
        var = row["variant"]
        reward = int(row["reward"])
        seg_imp[seg][var] += 1
        seg_suc[seg][var] += reward
        seg_n[seg] += 1
        seg_sessions[seg].append(seg_n[seg])
        for v in variants:
            imp = seg_imp[seg][v]
            seg_ctr_series[seg][v].append(seg_suc[seg][v] / imp if imp else 0.0)

    segments = sorted(seg_sessions.keys())
    ncols = min(3, len(segments))
    nrows = (len(segments) + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 4 * nrows), squeeze=False)

    for idx, seg in enumerate(segments):
        r, c = divmod(idx, ncols)
        ax = axes[r][c]
        sessions = seg_sessions[seg]
        for v in variants:
            ax.plot(sessions, seg_ctr_series[seg][v], color=variant_colors[v], label=f"{v} observed", linewidth=1)
            true = true_ctrs.get(seg, {}).get(v)
            if true is not None:
                ax.axhline(true, color=variant_colors[v], linestyle="--", alpha=0.5, linewidth=0.8)
        ax.set_title(seg.replace("_", " ").title(), fontsize=11)
        ax.set_xlabel("Session (within segment)")
        ax.set_ylabel("Observed CTR")
        ax.legend(fontsize=7)
        ax.grid(alpha=0.15)

    for idx in range(len(segments), nrows * ncols):
        r, c = divmod(idx, ncols)
        axes[r][c].set_visible(False)

    fig.suptitle("CTR Convergence per Segment (dashed = true CTR)", fontsize=14, y=0.99)
    fig.text(0.5, 0.965, subtitle, ha="center", va="top", fontsize=9)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)


# ── Chart 3: Aggregate cumulative reward ─────────────────────────────

def plot_cumulative_reward(rows: List[Dict[str, str]], out: Path, *, subtitle: str) -> None:
    sessions, bandit, baseline = [], [], []
    has_baseline = False

    for row in rows:
        sessions.append(int(row["session"]))
        bandit.append(int(row["cumulative_bandit_reward"]))
        bl = row.get("cumulative_baseline_reward", "")
        if bl not in ("", None):
            has_baseline = True
            baseline.append(int(bl))
        else:
            baseline.append(0)

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(sessions, bandit, label="Contextual bandit", linewidth=1.5)
    if has_baseline:
        ax.plot(sessions, baseline, label="Uniform baseline", linewidth=1.5, alpha=0.7)
    ax.set_xlabel("Session")
    ax.set_ylabel("Cumulative clicks")
    ax.set_title("Cumulative Reward: Contextual Bandit vs Uniform Baseline")
    ax.text(0.5, 1.02, subtitle, transform=ax.transAxes, ha="center", va="bottom", fontsize=9)
    ax.legend()
    ax.grid(alpha=0.15)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


# ── Chart 4: Segment × Variant heatmap ──────────────────────────────

def plot_heatmap(
    rows: List[Dict[str, str]],
    out: Path,
    *,
    variants: List[str],
    subtitle: str,
) -> None:
    seg_imp: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    seg_suc: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for row in rows:
        seg = row["segment"]
        var = row["variant"]
        seg_imp[seg][var] += 1
        seg_suc[seg][var] += int(row["reward"])

    segments = sorted(seg_imp.keys())
    matrix = np.zeros((len(segments), len(variants)))
    for i, seg in enumerate(segments):
        for j, v in enumerate(variants):
            imp = seg_imp[seg][v]
            matrix[i, j] = seg_suc[seg][v] / imp if imp else 0.0

    fig, ax = plt.subplots(figsize=(6, max(3, len(segments) * 0.8 + 1)))
    im = ax.imshow(matrix, cmap="YlGn", aspect="auto")

    ax.set_xticks(range(len(variants)))
    ax.set_xticklabels(variants)
    ax.set_yticks(range(len(segments)))
    ax.set_yticklabels([s.replace("_", " ") for s in segments], fontsize=9)

    for i in range(len(segments)):
        for j in range(len(variants)):
            ax.text(j, i, f"{matrix[i, j]:.3f}", ha="center", va="center", fontsize=9)

    ax.set_title("Observed CTR: Segment × Variant", fontsize=13)
    ax.text(0.5, 1.02, subtitle, transform=ax.transAxes, ha="center", va="bottom", fontsize=9)
    fig.colorbar(im, ax=ax, label="CTR", shrink=0.8)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


# ── Main ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Plot contextual simulation results")
    parser.add_argument("--input-csv", default="")
    parser.add_argument("--output-dir", default="../demo_assets")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    default_output_dir = script_dir / "output"
    csv_file = Path(args.input_csv).resolve() if args.input_csv else latest_csv(default_output_dir)

    rows = load_rows(csv_file)
    if not rows:
        raise ValueError(f"No rows in {csv_file}")

    metadata = load_run_metadata(csv_file)
    variants = discover_variants(rows, metadata)
    if not variants:
        raise ValueError(f"No variants discovered in {csv_file}")
    variant_colors = build_variant_colors(variants)
    true_ctrs = build_true_ctrs(metadata)
    subtitle = build_plot_subtitle(csv_file, rows, metadata)

    out_dir = (script_dir / args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    plot_segment_allocation(
        rows, out_dir / "segment_allocation.png",
        variants=variants, variant_colors=variant_colors, subtitle=subtitle,
    )
    plot_ctr_convergence(
        rows, out_dir / "ctr_convergence.png",
        variants=variants, variant_colors=variant_colors, true_ctrs=true_ctrs, subtitle=subtitle,
    )
    plot_cumulative_reward(rows, out_dir / "cumulative_reward.png", subtitle=subtitle)
    plot_heatmap(rows, out_dir / "segment_heatmap.png", variants=variants, subtitle=subtitle)

    print(f"Input:  {csv_file}")
    print(f"Charts: {out_dir}")
    for name in ("segment_allocation", "ctr_convergence", "cumulative_reward", "segment_heatmap"):
        print(f"  ✓ {name}.png")


if __name__ == "__main__":
    main()
