#!/usr/bin/env python
"""Lacunar Observatory v1.0 — streaming comparison of full-day recordings."""
from __future__ import annotations

import argparse
import glob
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

VERSION = "2.0"
CHUNK_ROWS = 200_000
SAMPLE_ROWS = 120_000
PROFILE_BINS = 120
IDLE_THRESHOLD = 0.120
RNG_SEED = 24072026
NOMINAL_SAMPLE_RATE_HZ = 120.0
LARGE_GAP_FACTOR = 2.0
PRIMARY_COLUMNS = ("elapsed_s", "activity", "irregularity", "tempo", "idle", "q", "p")

EPOCH_A_FILES = {
    f"experiment_{index:03d}_all_day.csv"
    for index in range(2, 9)
}

EPOCH_B1_FILES = {
    "epoch_b_validation_01.csv",
}

EPOCH_B2_FILES = {
    "epoch_b_validation_02.csv",
    "epoch_b_idle_settling_01.csv",
}


@dataclass
class RunningStats:
    count: int = 0
    total: float = 0.0
    total_sq: float = 0.0
    minimum: float = math.inf
    maximum: float = -math.inf

    def update(self, values: np.ndarray) -> None:
        values = np.asarray(values, dtype=np.float64)
        values = values[np.isfinite(values)]
        if values.size == 0:
            return
        self.count += int(values.size)
        self.total += float(values.sum())
        self.total_sq += float(np.square(values).sum())
        self.minimum = min(self.minimum, float(values.min()))
        self.maximum = max(self.maximum, float(values.max()))

    @property
    def mean(self) -> float:
        return self.total / self.count if self.count else math.nan

    @property
    def std(self) -> float:
        if not self.count:
            return math.nan
        variance = max(self.total_sq / self.count - self.mean ** 2, 0.0)
        return math.sqrt(variance)


@dataclass
class Reservoir:
    capacity: int
    rng: np.random.Generator
    seen: int = 0
    rows: list[np.ndarray] = field(default_factory=list)

    def update(self, values: np.ndarray) -> None:
        values = np.asarray(values)
        if values.ndim == 1:
            values = values.reshape(-1, 1)
        for row in values:
            self.seen += 1
            if len(self.rows) < self.capacity:
                self.rows.append(row.copy())
            else:
                slot = int(self.rng.integers(0, self.seen))
                if slot < self.capacity:
                    self.rows[slot] = row.copy()

    def array(self) -> np.ndarray:
        return np.asarray(self.rows, dtype=np.float64) if self.rows else np.empty((0, 0))


@dataclass
class Result:
    path: Path
    label: str
    rows: int
    duration_s: float
    epoch: str
    sample_rate_hz: float
    dt_mean_s: float
    dt_std_s: float
    dt_min_s: float
    dt_max_s: float
    nonpositive_dt_count: int
    large_gap_count: int
    nonfinite_elapsed_count: int
    dt_bucket_counts: tuple[int, int, int, int, int, int]
    short_dt_count: int
    short_after_12ms_count: int
    short_after_20ms_count: int
    historical_engine_time_s: float
    historical_engine_wall_ratio: float
    stats: dict[str, RunningStats]
    percentiles: dict[str, dict[str, float]]
    idle_fraction: float
    idle_episode_count: int
    idle_episode_mean_s: float
    idle_episode_max_s: float
    sample: pd.DataFrame
    profile: pd.DataFrame


def human_duration(seconds: float) -> str:
    if not np.isfinite(seconds):
        return "unknown"
    hours, remainder = divmod(max(float(seconds), 0.0), 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{int(hours)}h {int(minutes):02d}m {secs:05.2f}s"


def epoch_for(path: Path) -> str:
    name = path.name.lower()

    if name in EPOCH_A_FILES:
        return "A"

    if name in EPOCH_B1_FILES:
        return "B1"

    if name in EPOCH_B2_FILES:
        return "B2"

    return "UNKNOWN"


def label_for(path: Path) -> str:
    stem = path.stem
    if stem.startswith("experiment_"):
        stem = stem[len("experiment_"):]
    return stem.replace("_all_day", "").replace("_", " ").strip().title()


def resolve_inputs(patterns: Sequence[str]) -> list[Path]:
    candidates: list[Path] = []
    if patterns:
        for pattern in patterns:
            matches = [Path(item) for item in glob.glob(pattern)]
            candidates.extend(matches or [Path(pattern)])
    else:
        candidates.extend(Path.cwd().glob("experiment_*_all_day.csv"))

    unique: dict[str, Path] = {}
    for path in candidates:
        if not path.is_file() or path.suffix.lower() != ".csv":
            continue
        upper = path.name.upper()
        if "_RAW" in upper or "_BACKUP" in upper:
            continue
        unique[str(path.resolve()).lower()] = path.resolve()
    return sorted(unique.values(), key=lambda item: item.name.lower())


def idle_mask(chunk: pd.DataFrame, threshold: float) -> np.ndarray:
    if "idle" in chunk:
        values = pd.to_numeric(chunk["idle"], errors="coerce").to_numpy(dtype=float)
        finite = values[np.isfinite(values)]
        if finite.size and np.all(np.isin(np.unique(finite[:50_000]), [0.0, 1.0])):
            return np.nan_to_num(values, nan=0.0) >= 0.5
    activity = pd.to_numeric(chunk["activity"], errors="coerce").to_numpy(dtype=float)
    return np.nan_to_num(activity, nan=np.inf) <= threshold


def analyse(path: Path, chunk_rows: int, sample_rows: int, profile_bins: int,
            threshold: float, rng: np.random.Generator) -> Result:
    columns = list(pd.read_csv(path, nrows=0).columns)
    usecols = [name for name in PRIMARY_COLUMNS if name in columns]
    for required in ("elapsed_s", "activity"):
        if required not in usecols:
            raise ValueError(f"{path.name}: required column '{required}' is missing")

    stat_names = [name for name in usecols if name != "elapsed_s"]
    stats = {name: RunningStats() for name in stat_names}
    sample_columns = [name for name in ("elapsed_s", "activity", "irregularity", "tempo", "q", "p") if name in usecols]
    reservoir = Reservoir(sample_rows, rng)

    rows = 0
    first_elapsed = math.nan
    last_elapsed = math.nan
    previous_elapsed: float | None = None
    dt_stats = RunningStats()
    nonpositive_dt_count = 0
    large_gap_count = 0
    nonfinite_elapsed_count = 0
    dt_bucket_counts = np.zeros(6, dtype=np.int64)
    short_dt_count = 0
    short_after_12ms_count = 0
    short_after_20ms_count = 0
    previous_dt: float | None = None
    historical_engine_time_s = 0.0
    schedule_row_index = 0
    large_gap_threshold_s = LARGE_GAP_FACTOR / NOMINAL_SAMPLE_RATE_HZ
    nominal_dt = 1.0 / NOMINAL_SAMPLE_RATE_HZ
    engine_dt_min = nominal_dt * 0.25
    engine_dt_max = nominal_dt * 4.0
    idle_samples = 0
    idle_start: float | None = None
    idle_episodes: list[float] = []

    for chunk in pd.read_csv(path, usecols=usecols, chunksize=chunk_rows, low_memory=False):
        rows += len(chunk)
        elapsed = pd.to_numeric(chunk["elapsed_s"], errors="coerce").to_numpy(dtype=float)
        finite_mask = np.isfinite(elapsed)
        nonfinite_elapsed_count += int((~finite_mask).sum())
        finite_elapsed = elapsed[finite_mask]

        if finite_elapsed.size:
            if not np.isfinite(first_elapsed):
                first_elapsed = float(finite_elapsed[0])
            last_elapsed = float(finite_elapsed[-1])

            if previous_elapsed is not None:
                diffs = np.diff(np.concatenate(([previous_elapsed], finite_elapsed)))
            elif finite_elapsed.size > 1:
                diffs = np.diff(finite_elapsed)
            else:
                diffs = np.empty(0, dtype=float)

            if diffs.size:
                dt_stats.update(diffs)
                finite_diffs = diffs[np.isfinite(diffs)]
                nonpositive_dt_count += int((finite_diffs <= 0.0).sum())
                large_gap_count += int((finite_diffs > large_gap_threshold_s).sum())

                positive_diffs = finite_diffs[finite_diffs > 0.0]
                if positive_diffs.size:
                    bucket_edges = np.array(
                        [0.004, 0.012, 0.020, 0.050, 0.100],
                        dtype=float,
                    )
                    bucket_ids = np.digitize(
                        positive_diffs,
                        bucket_edges,
                        right=True,
                    )
                    dt_bucket_counts += np.bincount(
                        bucket_ids,
                        minlength=6,
                    )[:6]

                if previous_dt is not None and finite_diffs.size:
                    pair_diffs = np.concatenate(([previous_dt], finite_diffs))
                else:
                    pair_diffs = finite_diffs

                if pair_diffs.size >= 2:
                    before = pair_diffs[:-1]
                    current = pair_diffs[1:]
                    short = current <= 0.004
                    short_dt_count += int(short.sum())
                    short_after_12ms_count += int(
                        (short & (before >= 0.012)).sum()
                    )
                    short_after_20ms_count += int(
                        (short & (before >= 0.020)).sum()
                    )

                if finite_diffs.size:
                    previous_dt = float(finite_diffs[-1])

            finite_positions = np.flatnonzero(finite_mask)
            if finite_positions.size:
                row_indices = (
                    schedule_row_index + finite_positions.astype(np.float64)
                )
                raw_engine_dt = (
                    finite_elapsed
                    - ((row_indices - 1.0) * nominal_dt)
                )
                reconstructed_engine_dt = np.clip(
                    raw_engine_dt,
                    engine_dt_min,
                    engine_dt_max,
                )
                historical_engine_time_s += float(
                    reconstructed_engine_dt.sum()
                )

            schedule_row_index += len(elapsed)
            previous_elapsed = float(finite_elapsed[-1])

        for name in stat_names:
            values = pd.to_numeric(chunk[name], errors="coerce").to_numpy(dtype=float)
            stats[name].update(values)

        matrix = chunk[sample_columns].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
        reservoir.update(matrix[np.isfinite(matrix).all(axis=1)])

        mask = idle_mask(chunk, threshold)
        idle_samples += int(mask.sum())
        for timestamp, is_idle in zip(elapsed, mask):
            if not np.isfinite(timestamp):
                continue
            if is_idle and idle_start is None:
                idle_start = float(timestamp)
            elif not is_idle and idle_start is not None:
                idle_episodes.append(max(float(timestamp) - idle_start, 0.0))
                idle_start = None

    if idle_start is not None and np.isfinite(last_elapsed):
        idle_episodes.append(max(last_elapsed - idle_start, 0.0))

    duration = last_elapsed - first_elapsed if np.isfinite(first_elapsed) and np.isfinite(last_elapsed) else math.nan
    rate = 1.0 / dt_stats.mean if np.isfinite(dt_stats.mean) and dt_stats.mean > 0 else math.nan
    sample_array = reservoir.array()
    sample = pd.DataFrame(sample_array, columns=sample_columns) if sample_array.size else pd.DataFrame(columns=sample_columns)

    percentiles: dict[str, dict[str, float]] = {}
    for name in ("activity", "irregularity", "tempo", "q", "p"):
        if name not in sample:
            continue
        values = sample[name].to_numpy(dtype=float)
        values = values[np.isfinite(values)]
        if values.size:
            points = np.percentile(values, [5, 25, 50, 75, 95, 99])
            percentiles[name] = dict(zip(("p05", "p25", "p50", "p75", "p95", "p99"), map(float, points)))

    profile_data: dict[str, np.ndarray] = {
        "day_fraction": (np.arange(profile_bins, dtype=float) + 0.5) / profile_bins
    }
    if not sample.empty and np.isfinite(duration) and duration > 0:
        positions = np.clip((sample["elapsed_s"].to_numpy(dtype=float) - first_elapsed) / duration, 0, 1)
        bins = np.minimum((positions * profile_bins).astype(int), profile_bins - 1)
        for name in ("activity", "irregularity", "tempo", "q", "p"):
            if name not in sample:
                continue
            values = sample[name].to_numpy(dtype=float)
            sums = np.zeros(profile_bins)
            counts = np.zeros(profile_bins, dtype=int)
            valid = np.isfinite(values)
            np.add.at(sums, bins[valid], values[valid])
            np.add.at(counts, bins[valid], 1)
            profile_data[name] = np.divide(sums, counts, out=np.full(profile_bins, np.nan), where=counts > 0)
    profile = pd.DataFrame(profile_data)

    episodes = np.asarray(idle_episodes, dtype=float)
    historical_engine_wall_ratio = (
        historical_engine_time_s / duration
        if np.isfinite(duration) and duration > 0
        else math.nan
    )

    return Result(
        path=path,
        label=label_for(path),
        rows=rows,
        epoch=epoch_for(path),
        duration_s=duration,
        sample_rate_hz=rate,
        dt_mean_s=dt_stats.mean,
        dt_std_s=dt_stats.std,
        dt_min_s=dt_stats.minimum if dt_stats.count else math.nan,
        dt_max_s=dt_stats.maximum if dt_stats.count else math.nan,
        nonpositive_dt_count=nonpositive_dt_count,
        large_gap_count=large_gap_count,
        nonfinite_elapsed_count=nonfinite_elapsed_count,
        dt_bucket_counts=tuple(int(value) for value in dt_bucket_counts),
        short_dt_count=short_dt_count,
        short_after_12ms_count=short_after_12ms_count,
        short_after_20ms_count=short_after_20ms_count,
        historical_engine_time_s=historical_engine_time_s,
        historical_engine_wall_ratio=historical_engine_wall_ratio,
        stats=stats,
        percentiles=percentiles,
        idle_fraction=idle_samples / rows if rows else math.nan,
        idle_episode_count=int(episodes.size),
        idle_episode_mean_s=float(episodes.mean()) if episodes.size else 0.0,
        idle_episode_max_s=float(episodes.max()) if episodes.size else 0.0,
        sample=sample,
        profile=profile,
    )


def summary_row(result: Result) -> dict[str, object]:
    row: dict[str, object] = {
        "recording": result.path.name,
        "label": result.label,
        "epoch": result.epoch,
        "rows": result.rows,
        "duration_s": result.duration_s,
        "duration_h": result.duration_s / 3600 if np.isfinite(result.duration_s) else math.nan,
        "sample_rate_hz": result.sample_rate_hz,
        "dt_mean_s": result.dt_mean_s,
        "dt_std_s": result.dt_std_s,
        "dt_min_s": result.dt_min_s,
        "dt_max_s": result.dt_max_s,
        "nonpositive_dt_count": result.nonpositive_dt_count,
        "large_gap_count": result.large_gap_count,
        "nonfinite_elapsed_count": result.nonfinite_elapsed_count,
        "dt_le_4ms": result.dt_bucket_counts[0],
        "dt_4_12ms": result.dt_bucket_counts[1],
        "dt_12_20ms": result.dt_bucket_counts[2],
        "dt_20_50ms": result.dt_bucket_counts[3],
        "dt_50_100ms": result.dt_bucket_counts[4],
        "dt_gt_100ms": result.dt_bucket_counts[5],
        "short_dt_count": result.short_dt_count,
        "short_after_12ms_count": result.short_after_12ms_count,
        "short_after_20ms_count": result.short_after_20ms_count,
        "historical_engine_time_s": result.historical_engine_time_s,
        "historical_engine_wall_ratio": result.historical_engine_wall_ratio,
        "idle_fraction": result.idle_fraction,
        "idle_episode_count": result.idle_episode_count,
        "idle_episode_mean_s": result.idle_episode_mean_s,
        "idle_episode_max_s": result.idle_episode_max_s,
    }
    for name, stat in result.stats.items():
        row[f"{name}_mean"] = stat.mean
        row[f"{name}_std"] = stat.std
        row[f"{name}_min"] = stat.minimum if stat.count else math.nan
        row[f"{name}_max"] = stat.maximum if stat.count else math.nan
    for name, values in result.percentiles.items():
        for percentile, value in values.items():
            row[f"{name}_{percentile}"] = value
    return row


def distribution_plot(results: Sequence[Result], column: str, destination: Path, title: str) -> None:
    available = []
    for result in results:
        if column in result.sample:
            values = result.sample[column].to_numpy(dtype=float)
            values = values[np.isfinite(values)]
            if values.size:
                available.append(values)
    if not available:
        return
    combined = np.concatenate(available)
    low, high = np.percentile(combined, [0.5, 99.5])
    if low == high:
        high = low + 1e-9
    bins = np.linspace(low, high, 80)
    fig, ax = plt.subplots(figsize=(10, 6))
    for result in results:
        if column not in result.sample:
            continue
        values = result.sample[column].to_numpy(dtype=float)
        values = values[np.isfinite(values)]
        if values.size:
            ax.hist(values, bins=bins, density=True, histtype="step", linewidth=1.5, label=result.label)
    ax.set_title(title)
    ax.set_xlabel(column.title())
    ax.set_ylabel("Density")
    ax.legend()
    fig.tight_layout()
    fig.savefig(destination, dpi=160)
    plt.close(fig)


def phase_atlas(results: Sequence[Result], destination: Path) -> None:
    usable = [r for r in results if {"q", "p"}.issubset(r.sample.columns)]
    if not usable:
        return
    all_q = np.concatenate([r.sample["q"].to_numpy(dtype=float) for r in usable])
    all_p = np.concatenate([r.sample["p"].to_numpy(dtype=float) for r in usable])
    valid = np.isfinite(all_q) & np.isfinite(all_p)
    if not valid.any():
        return
    extent = max(abs(float(np.percentile(all_q[valid], 0.5))), abs(float(np.percentile(all_q[valid], 99.5))),
                 abs(float(np.percentile(all_p[valid], 0.5))), abs(float(np.percentile(all_p[valid], 99.5))), 1e-6)
    cols = min(3, len(usable))
    rows = math.ceil(len(usable) / cols)
    fig, axes = plt.subplots(rows, cols, figsize=(5 * cols, 5 * rows), squeeze=False)
    for ax, result in zip(axes.flat, usable):
        q = result.sample["q"].to_numpy(dtype=float)
        p = result.sample["p"].to_numpy(dtype=float)
        mask = np.isfinite(q) & np.isfinite(p)
        ax.hexbin(q[mask], p[mask], gridsize=80, extent=(-extent, extent, -extent, extent), mincnt=1)
        ax.set_title(result.label)
        ax.set_xlabel("q")
        ax.set_ylabel("p")
        ax.set_xlim(-extent, extent)
        ax.set_ylim(-extent, extent)
        ax.set_aspect("equal", adjustable="box")
    for ax in axes.flat[len(usable):]:
        ax.axis("off")
    fig.suptitle("Lacunar Phase-Space Atlas — Identical Axes")
    fig.tight_layout()
    fig.savefig(destination, dpi=160)
    plt.close(fig)


def idle_plot(results: Sequence[Result], destination: Path) -> None:
    positions = np.arange(len(results))
    width = 0.38
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.bar(positions - width / 2, [r.idle_fraction * 100 for r in results], width, label="Idle fraction (%)")
    ax.bar(positions + width / 2, [r.idle_episode_max_s / 60 for r in results], width, label="Longest idle episode (min)")
    ax.set_xticks(positions)
    ax.set_xticklabels([r.label for r in results], rotation=25, ha="right")
    ax.set_title("Idle Behaviour Comparison")
    ax.legend()
    fig.tight_layout()
    fig.savefig(destination, dpi=160)
    plt.close(fig)


def profile_plot(results: Sequence[Result], destination: Path) -> None:
    fields = [name for name in ("activity", "irregularity", "tempo") if any(name in r.profile for r in results)]
    if not fields:
        return
    fig, axes = plt.subplots(len(fields), 1, figsize=(11, 3.5 * len(fields)), squeeze=False)
    for ax, name in zip(axes.flat, fields):
        for result in results:
            if name in result.profile:
                ax.plot(result.profile["day_fraction"] * 100, result.profile[name], label=result.label)
        ax.set_title(name.title())
        ax.set_xlabel("Recording progress (%)")
        ax.set_ylabel("Mean")
        ax.legend(ncol=min(3, len(results)))
    fig.suptitle("Time-Normalised Day Profiles")
    fig.tight_layout()
    fig.savefig(destination, dpi=160)
    plt.close(fig)


def constellation(summary: pd.DataFrame, destination: Path) -> None:
    wanted = [
        "activity_mean", "activity_std", "activity_p50", "activity_p95",
        "irregularity_mean", "irregularity_std", "tempo_mean", "q_std", "p_std", "idle_fraction",
    ]
    features = [name for name in wanted if name in summary]
    if len(features) < 2 or len(summary) < 2:
        return
    frame = summary[features].astype(float).replace([np.inf, -np.inf], np.nan)
    for name in features:
        median = frame[name].median()
        frame[name] = frame[name].fillna(median if np.isfinite(median) else 0.0)
    matrix = frame.to_numpy(dtype=float)
    std = matrix.std(axis=0)
    std[std == 0] = 1.0
    matrix = (matrix - matrix.mean(axis=0)) / std
    u, singular, _ = np.linalg.svd(matrix, full_matrices=False)
    coords = u[:, :2] * singular[:2]
    if coords.shape[1] == 1:
        coords = np.column_stack([coords[:, 0], np.zeros(len(coords))])
    variance = singular ** 2
    ratio = variance / variance.sum() if variance.sum() else variance
    fig, ax = plt.subplots(figsize=(9, 7))
    ax.scatter(coords[:, 0], coords[:, 1], s=90)
    for index, label in enumerate(summary["label"]):
        ax.annotate(str(label), tuple(coords[index]), xytext=(6, 6), textcoords="offset points")
    ax.axhline(0, linewidth=0.7)
    ax.axvline(0, linewidth=0.7)
    ax.set_title("Daily Constellation — PCA of Comparable Features")
    ax.set_xlabel(f"Principal component 1 ({ratio[0] * 100:.1f}% variance)")
    ax.set_ylabel(f"Principal component 2 ({(ratio[1] if len(ratio) > 1 else 0) * 100:.1f}% variance)")
    fig.text(0.01, 0.01, "Features: " + ", ".join(features), fontsize=8)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(destination, dpi=160)
    plt.close(fig)


def extreme(summary: pd.DataFrame, column: str, maximum: bool) -> str:
    if column not in summary or summary[column].dropna().empty:
        return "not available"
    index = summary[column].idxmax() if maximum else summary[column].idxmin()
    return str(summary.loc[index, "label"])


def report(results: Sequence[Result], summary: pd.DataFrame, destination: Path) -> None:
    lines = [
        "=" * 68, f"LACUNAR OBSERVATORY v{VERSION}", "=" * 68, "",
        f"Recordings compared: {len(results)}",
        f"Total rows: {int(summary['rows'].sum()):,}",
        f"Total duration: {human_duration(float(summary['duration_s'].sum()))}", "",
        "RECORDINGS", "-" * 68,
    ]
    for result in results:
        lines.extend([
            result.label,
            f"  File: {result.path.name}",
            f"  Rows: {result.rows:,}",
            f"  Engine epoch: {result.epoch}",
            f"  Duration: {human_duration(result.duration_s)}",
            f"  Sample rate: {result.sample_rate_hz:.2f} Hz",
            f"  Mean frame interval: {result.dt_mean_s * 1000:.3f} ms",
            f"  Frame interval jitter (std): {result.dt_std_s * 1000:.3f} ms",
            f"  Minimum frame interval: {result.dt_min_s * 1000:.3f} ms",
            f"  Maximum frame interval: {result.dt_max_s * 1000:.3f} ms",
            f"  Non-positive frame intervals: {result.nonpositive_dt_count}",
            f"  Gaps > {LARGE_GAP_FACTOR:.1f}x nominal interval: {result.large_gap_count}",
            f"  Non-finite elapsed timestamps: {result.nonfinite_elapsed_count}",
            "  Frame interval distribution:",
            f"    <= 4 ms:    {result.dt_bucket_counts[0]:,}",
            f"    4-12 ms:    {result.dt_bucket_counts[1]:,}",
            f"    12-20 ms:   {result.dt_bucket_counts[2]:,}",
            f"    20-50 ms:   {result.dt_bucket_counts[3]:,}",
            f"    50-100 ms:  {result.dt_bucket_counts[4]:,}",
            f"    > 100 ms:   {result.dt_bucket_counts[5]:,}",
            "  Adjacent interval structure:",
            f"    <=4 ms intervals: {result.short_dt_count:,}",
            f"    <=4 ms following >=12 ms: {result.short_after_12ms_count:,}",
            f"    <=4 ms following >=20 ms: {result.short_after_20ms_count:,}",
            (
                "    % <=4 ms following >=12 ms: "
                f"{100.0 * result.short_after_12ms_count / result.short_dt_count:.2f}%"
                if result.short_dt_count
                else "    % <=4 ms following >=12 ms: not available"
            ),
            (
                "    % <=4 ms following >=20 ms: "
                f"{100.0 * result.short_after_20ms_count / result.short_dt_count:.2f}%"
                if result.short_dt_count
                else "    % <=4 ms following >=20 ms: not available"
            ),
            (
                "  Epoch-A runtime reconstruction:"
                if result.epoch == "A"
                else "  Counterfactual Epoch-A reconstruction:"
            ),
            f"    Reconstructed engine time: {human_duration(result.historical_engine_time_s)}",
            f"    Engine/wall-time ratio: {result.historical_engine_wall_ratio:.6f}",
            f"  Idle fraction: {result.idle_fraction * 100:.2f}%",
            f"  Longest idle episode: {human_duration(result.idle_episode_max_s)}", "",
        ])
    lines.extend([
        "ENGINE EPOCHS", "-" * 68,
        "Epoch A: historical timestep bug plus lower timestep clamp.",
        "Epoch B1: previous-frame timestep fixed; lower clamp still present.",
        "Epoch B2: previous-frame timestep fixed; lower clamp removed.",
        "          This is the current validated timing baseline.",
        "UNKNOWN: recording provenance has not been explicitly assigned.",
        "",
        "Epoch is provenance, not inferred behaviour.",
        "",
        "COMPARATIVE HIGHLIGHTS", "-" * 68,
        f"Highest mean activity: {extreme(summary, 'activity_mean', True)}",
        f"Lowest mean activity: {extreme(summary, 'activity_mean', False)}",
        f"Highest activity variability: {extreme(summary, 'activity_std', True)}",
        f"Lowest mean irregularity: {extreme(summary, 'irregularity_mean', False)}",
        f"Highest mean irregularity: {extreme(summary, 'irregularity_mean', True)}",
        f"Lowest idle fraction: {extreme(summary, 'idle_fraction', False)}",
        f"Highest idle fraction: {extreme(summary, 'idle_fraction', True)}",
        f"Largest q spread: {extreme(summary, 'q_std', True)}",
        f"Largest p spread: {extreme(summary, 'p_std', True)}", "",
        "INTERPRETATION CAUTION", "-" * 68,
        "These comparisons describe recorded input dynamics, not cognitive states.",
        "Differences may reflect recording length, task mix, AFK time, hardware",
        "behaviour, engine configuration, or calibration changes. The phase atlas",
        "uses identical axes and the profiles are normalised by recording duration.", "",
    ])
    destination.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare Lacunar Mirror full-day CSV recordings.")
    parser.add_argument("inputs", nargs="*", help="CSV files or wildcard patterns")
    parser.add_argument("--output", default="lacunar_observatory")
    parser.add_argument("--chunk-rows", type=int, default=CHUNK_ROWS)
    parser.add_argument("--sample-rows", type=int, default=SAMPLE_ROWS)
    parser.add_argument("--profile-bins", type=int, default=PROFILE_BINS)
    parser.add_argument("--idle-threshold", type=float, default=IDLE_THRESHOLD)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    paths = resolve_inputs(args.inputs)
    if len(paths) < 2:
        print("Need at least two canonical CSV recordings. RAW and backup files are excluded.", file=sys.stderr)
        return 2

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    print("\n" + "=" * 68)
    print(f"LACUNAR OBSERVATORY v{VERSION}")
    print("=" * 68 + "\n")
    for path in paths:
        print(f"  - {path.name}")
    print()

    rng = np.random.default_rng(RNG_SEED)
    results: list[Result] = []
    for index, path in enumerate(paths, 1):
        print(f"[{index}/{len(paths)}] Analysing {path.name} ...")
        try:
            item = analyse(path, args.chunk_rows, args.sample_rows, args.profile_bins, args.idle_threshold, rng)
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        results.append(item)
        print(f"    {item.rows:,} rows | {human_duration(item.duration_s)} | {item.sample_rate_hz:.2f} Hz")

    summary = pd.DataFrame([summary_row(item) for item in results])
    summary.to_csv(output / "comparison_summary.csv", index=False)
    for item in results:
        item.profile.to_csv(output / f"{item.path.stem}_normalised_profile.csv", index=False)

    print("\nCreating comparison figures ...")
    distribution_plot(results, "activity", output / "activity_distributions.png", "Activity Distributions — Common Scale")
    distribution_plot(results, "irregularity", output / "irregularity_distributions.png", "Irregularity Distributions — Common Scale")
    phase_atlas(results, output / "phase_space_atlas.png")
    idle_plot(results, output / "idle_episode_comparison.png")
    profile_plot(results, output / "normalised_day_profiles.png")
    constellation(summary, output / "daily_constellation.png")
    report(results, summary, output / "comparison_report.txt")

    print("\n" + "=" * 68)
    print("OBSERVATORY COMPLETE")
    print("=" * 68)
    print(f"\nOutput directory: {output.resolve()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
