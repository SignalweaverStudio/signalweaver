"""Engagement-regime analysis.

Tests the two-regime hypothesis against THREE candidate regime
definitions side by side, rather than assuming one threshold is
correct:

    not_deep_idle   : idle < 0.95             (everything except deep, sustained inactivity)
    low_activity    : activity == floor (0.119203)  (no input excitation)
    strict_engaged  : activity > floor AND idle < 0.50

For each definition we compute: occupancy over absolute time, episode
counts/durations, q mean/spread by regime, transition rate over the
day, and first-half vs second-half occupancy. If the across-day
decline shows up under all three, the finding is robust to how
"engaged" is defined. If only under not_deep_idle, the finding is
specifically about deep accumulated inactivity, not engagement
generally -- which is a materially different (and more precise) claim.

Does not touch the live engine or recorder. Reads existing raw
recording CSVs only.

Scope note on chunked reading: with usecols=[elapsed_s, idle,
activity, q] at float32, the largest recording (~3.7M rows) is
roughly 60-90MB in memory, not several hundred -- pandas' per-column
overhead is real but not that large at 4 numeric columns. I've kept
a single in-memory read per file rather than true chunked streaming,
since at these file sizes it's unlikely to matter in practice. If you
hit actual memory pressure (e.g. much longer future recordings), the
right fix is switching load_recording() to pd.read_csv(...,
chunksize=...) with incremental aggregation -- flagging this as a
deliberate scope decision, not an oversight, so you can push back if
you want it built now instead of if-and-when it's needed.

Usage:
    python engagement_regime_v2.py --out diagnostic_outputs/engagement \
        experiment_002_all_day.csv experiment_003_all_day.csv \
        experiment_004_all_day.csv experiment_005_all_day.csv \
        experiment_006_all_day.csv
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# --- Constants -----------------------------------------------------------
ACTIVITY_FLOOR = 0.119203
MIN_EPISODE_S = 1.0
MIN_INTERRUPTION_S = 1.0     # opposite-state runs shorter than this get merged away
OCCUPANCY_BIN_S = 60.0
TRANSITION_BIN_S = 600.0
SCATTER_PLOT_MAX_POINTS = 50_000

REQUIRED_COLUMNS = ["elapsed_s", "idle", "q", "activity"]


def regime_not_deep_idle(df: pd.DataFrame) -> np.ndarray:
    """Candidate engaged state: every sample that is not deeply idle."""
    return (df["idle"].to_numpy() < 0.95)


def regime_low_activity(df: pd.DataFrame) -> np.ndarray:
    """engaged = any input excitation above the floor."""
    return ~np.isclose(df["activity"].to_numpy(), ACTIVITY_FLOOR, atol=1e-5)


def regime_strict_engaged(df: pd.DataFrame) -> np.ndarray:
    """engaged = above floor AND not substantially idle."""
    above_floor = ~np.isclose(df["activity"].to_numpy(), ACTIVITY_FLOOR, atol=1e-5)
    not_idle = df["idle"].to_numpy() < 0.50
    return above_floor & not_idle


REGIME_DEFINITIONS = {
    "not_deep_idle": regime_not_deep_idle,
    "low_activity": regime_low_activity,
    "strict_engaged": regime_strict_engaged,
}


def load_recording(path: Path) -> pd.DataFrame:
    df = pd.read_csv(
        path,
        usecols=REQUIRED_COLUMNS,
        dtype={
            "elapsed_s": "float64",
            "idle": "float32",
            "q": "float32",
            "activity": "float32",
        },
    )
    return df


def estimate_sample_rate_hz(elapsed_s: np.ndarray) -> float:
    dt = np.diff(elapsed_s)
    dt = dt[dt > 0]
    return 1.0 / np.median(dt)


# --- Vectorised run-length / episode detection ----------------------------

def find_runs(mask: np.ndarray, elapsed_s: np.ndarray):
    """Return list of (value, start_idx, end_idx, start_s, end_s, duration_s)
    for contiguous runs of `mask`. Vectorised via np.diff, not a Python loop
    over every sample."""
    n = len(mask)
    if n == 0:
        return []
    change_points = np.where(np.diff(mask.astype(np.int8)) != 0)[0] + 1
    starts = np.concatenate(([0], change_points))
    ends = np.concatenate((change_points, [n]))
    values = mask[starts]

    runs = []
    for v, s, e in zip(values, starts, ends):
        start_s = elapsed_s[s]
        end_s = elapsed_s[e - 1]
        runs.append([bool(v), s, e, start_s, end_s, end_s - start_s])
    return runs


def merge_short_interruptions(runs: list, min_interruption_s: float) -> list:
    """Flip runs shorter than min_interruption_s to match their neighbours,
    then re-merge adjacent same-value runs. Prevents a 0.2s dropout inside a
    20-minute engaged stretch from being counted as two separate episodes
    and two extra transitions."""
    if not runs:
        return runs

    changed = True
    runs = [r[:] for r in runs]  # shallow copy
    while changed:
        changed = False
        for i, r in enumerate(runs):
            duration = r[5]
            if duration < min_interruption_s and len(runs) > 1:
                # flip to match the longer neighbour
                left_dur = runs[i - 1][5] if i > 0 else -1
                right_dur = runs[i + 1][5] if i < len(runs) - 1 else -1
                if left_dur >= right_dur and i > 0:
                    runs[i][0] = runs[i - 1][0]
                elif i < len(runs) - 1:
                    runs[i][0] = runs[i + 1][0]
                changed = True
        if changed:
            # re-merge adjacent runs with equal value
            merged = [runs[0]]
            for r in runs[1:]:
                if r[0] == merged[-1][0]:
                    merged[-1][2] = r[2]
                    merged[-1][4] = r[4]
                    merged[-1][5] = merged[-1][4] - merged[-1][3]
                else:
                    merged.append(r)
            runs = merged
    return runs


# --- Per-regime analyses ---------------------------------------------------

def analyze_regime(df: pd.DataFrame, engaged: np.ndarray, regime_name: str,
                    label: str, out_dir: Path) -> dict:
    elapsed_s = df["elapsed_s"].to_numpy()
    q = df["q"].to_numpy()

    result = {"regime": regime_name}

    # q mean/spread by regime
    idle_q = q[~engaged]
    active_q = q[engaged]
    result["q_by_regime"] = {
        "idle_q_mean": float(idle_q.mean()) if len(idle_q) else None,
        "idle_q_std": float(idle_q.std()) if len(idle_q) else None,
        "active_q_mean": float(active_q.mean()) if len(active_q) else None,
        "active_q_std": float(active_q.std()) if len(active_q) else None,
        "idle_sample_count": int(len(idle_q)),
        "active_sample_count": int(len(active_q)),
    }

    # Occupancy over absolute time (60s bins -- already compact)
    bin_index = (elapsed_s // OCCUPANCY_BIN_S).astype(int)
    occ = pd.Series(engaged, dtype=float).groupby(bin_index).mean()
    occ.index = occ.index * OCCUPANCY_BIN_S / 60.0
    occ.to_csv(out_dir / f"{label}_{regime_name}_occupancy.csv", header=["fraction_engaged"])

    half = len(engaged) // 2
    first_half_occ = float(engaged[:half].mean())
    second_half_occ = float(engaged[half:].mean())
    result["occupancy"] = {"first_half": first_half_occ, "second_half": second_half_occ}

    # Episodes: vectorised detection, then merge short interruptions,
    # then drop remaining sub-MIN_EPISODE_S runs from the final counts.
    raw_runs = find_runs(engaged, elapsed_s)
    merged_runs = merge_short_interruptions(raw_runs, MIN_INTERRUPTION_S)
    kept_runs = [r for r in merged_runs if r[5] >= MIN_EPISODE_S]

    idle_durations = np.array([r[5] for r in kept_runs if not r[0]])
    active_durations = np.array([r[5] for r in kept_runs if r[0]])

    def summarize(durations):
        if len(durations) == 0:
            return {"count": 0}
        return {
            "count": int(len(durations)),
            "mean_s": float(durations.mean()),
            "median_s": float(np.median(durations)),
            "p95_s": float(np.percentile(durations, 95)),
            "max_s": float(durations.max()),
        }

    result["episodes"] = {
        "idle": summarize(idle_durations),
        "active": summarize(active_durations),
    }

    # Transition rate over the day, using the *merged* run boundaries
    # (so debounced sub-second flickers don't inflate the count)
    transition_times_s = np.array([r[3] for r in kept_runs[1:]])  # start of each run after the first
    if len(transition_times_s):
        tbin = (transition_times_s // TRANSITION_BIN_S).astype(int)
        total_bins = int(elapsed_s[-1] // TRANSITION_BIN_S) + 1
        counts = np.bincount(tbin, minlength=total_bins)[:total_bins]
        per_hour = counts * (3600.0 / TRANSITION_BIN_S)
        times_min = np.arange(total_bins) * TRANSITION_BIN_S / 60.0
        pd.Series(per_hour, index=times_min, name="transitions_per_hour").to_csv(
            out_dir / f"{label}_{regime_name}_transition_rate.csv", header=True
        )

    return result


def combined_plots_for_recording(df: pd.DataFrame, regimes: dict, label: str, out_dir: Path):
    """One figure per recording, comparing all three regime definitions."""
    elapsed_min = df["elapsed_s"].to_numpy() / 60.0
    q = df["q"].to_numpy()

    fig, axes = plt.subplots(1, len(regimes), figsize=(5 * len(regimes), 4.5), sharey=True)
    if len(regimes) == 1:
        axes = [axes]
    for ax, (name, engaged) in zip(axes, regimes.items()):
        bin_index = (df["elapsed_s"].to_numpy() // OCCUPANCY_BIN_S).astype(int)
        occ = pd.Series(engaged, dtype=float).groupby(bin_index).mean()
        occ.index = occ.index * OCCUPANCY_BIN_S / 60.0
        ax.plot(occ.index, occ.values)
        ax.set_title(name)
        ax.set_xlabel("Elapsed (min)")
        ax.set_ylim(-0.02, 1.02)
    axes[0].set_ylabel("Fraction engaged (60s bins)")
    fig.suptitle(f"{label}: occupancy by regime definition")
    plt.tight_layout()
    plt.savefig(out_dir / f"{label}_occupancy_by_regime.png", dpi=110)
    plt.close(fig)

    # Active-only q trend, one panel per regime, downsampled for plotting
    fig, axes = plt.subplots(1, len(regimes), figsize=(5 * len(regimes), 4.5), sharey=True)
    if len(regimes) == 1:
        axes = [axes]
    rng = np.random.default_rng(0)
    for ax, (name, engaged) in zip(axes, regimes.items()):
        eng_elapsed = elapsed_min[engaged]
        eng_q = q[engaged]
        if len(eng_elapsed) > SCATTER_PLOT_MAX_POINTS:
            idx = rng.choice(len(eng_elapsed), SCATTER_PLOT_MAX_POINTS, replace=False)
            idx.sort()
            plot_elapsed, plot_q = eng_elapsed[idx], eng_q[idx]
        else:
            plot_elapsed, plot_q = eng_elapsed, eng_q
        ax.scatter(plot_elapsed, plot_q, s=2, alpha=0.15)
        if len(eng_elapsed) > 10:
            slope, intercept = np.polyfit(eng_elapsed, eng_q, 1)
            x_line = np.array([eng_elapsed.min(), eng_elapsed.max()])
            y_line = slope * x_line + intercept
            ax.plot(x_line, y_line, color="red",
                    label=f"{slope:+.5f} q/min")
            ax.legend(fontsize=8)
        ax.set_title(name)
        ax.set_xlabel("Elapsed (min), engaged samples only")
    axes[0].set_ylabel("q")
    fig.suptitle(f"{label}: active-only q trend by regime definition")
    plt.tight_layout()
    plt.savefig(out_dir / f"{label}_active_q_trend_by_regime.png", dpi=110)
    plt.close(fig)


def analyze_recording(path: Path, out_root: Path) -> dict:
    label = path.stem
    out_dir = out_root / label
    out_dir.mkdir(parents=True, exist_ok=True)

    df = load_recording(path)
    sample_rate = estimate_sample_rate_hz(df["elapsed_s"].to_numpy())

    regime_masks = {name: fn(df) for name, fn in REGIME_DEFINITIONS.items()}

    result = {"label": label, "sample_rate_hz": sample_rate, "rows": len(df), "regimes": {}}
    for name, mask in regime_masks.items():
        result["regimes"][name] = analyze_regime(df, mask, name, label, out_dir)

    combined_plots_for_recording(df, regime_masks, label, out_dir)

    with open(out_dir / f"{label}_engagement_summary.json", "w") as f:
        json.dump(result, f, indent=2)

    return result


def cross_recording_agreement(all_results: list, out_root: Path):
    """For each regime definition, does first-half > second-half occupancy
    hold across every recording? This is the actual robustness check."""
    rows = []
    for r in all_results:
        for regime_name, regime_result in r["regimes"].items():
            occ = regime_result["occupancy"]
            rows.append({
                "recording": r["label"],
                "regime": regime_name,
                "first_half_occupancy": occ["first_half"],
                "second_half_occupancy": occ["second_half"],
                "decline": occ["first_half"] - occ["second_half"],
            })
    df = pd.DataFrame(rows)
    df.to_csv(out_root / "cross_recording_agreement.csv", index=False)

    print("\nRobustness check: does first-half occupancy exceed second-half\n"
          "occupancy under every regime definition, in every recording?\n")
    for regime_name in REGIME_DEFINITIONS:
        sub = df[df["regime"] == regime_name]
        all_positive = bool((sub["decline"] > 0).all())
        print(f"  {regime_name}: decline positive in all recordings = {all_positive} "
              f"(min decline = {sub['decline'].min():+.3f}, max = {sub['decline'].max():+.3f})")


def main():
    parser = argparse.ArgumentParser(description="Engagement-regime analysis")
    parser.add_argument("recordings", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=Path("diagnostic_outputs/engagement"))
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    missing = [str(path) for path in args.recordings if not path.exists()]
    if missing:
        parser.error("Recording file(s) not found: " + ", ".join(missing))

    all_results = []
    for path in args.recordings:
        print(f"Analyzing {path.name} ...")
        result = analyze_recording(path, args.out)
        all_results.append(result)
        for regime_name, regime_result in result["regimes"].items():
            occ = regime_result["occupancy"]
            print(f"  [{regime_name}] first-half occ={occ['first_half']:.3f}, "
                  f"second-half occ={occ['second_half']:.3f}")

    cross_recording_agreement(all_results, args.out)

    with open(args.out / "engagement_regime_report.json", "w") as f:
        json.dump(all_results, f, indent=2)

    print(f"\nDone. Results written to {args.out}")


if __name__ == "__main__":
    main()
