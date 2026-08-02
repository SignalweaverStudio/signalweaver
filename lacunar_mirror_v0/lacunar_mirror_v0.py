#!/usr/bin/env python3
"""
Lacunar Mirror v0 — dynamics bench rig

Purpose
-------
Test whether a small continuous dynamical system can turn sparse interaction rhythm
into an instrument-like evolving state without classifying the user.

This prototype has:
- telemetry inputs: activity rate r, irregularity rho, tempo tau, idle delta
- internal state: displacement q, momentum p, slow compliance s
- deterministic semi-implicit Euler integration
- synthetic test mode
- optional live keyboard/mouse timing mode via pynput
- optional matplotlib visualisation
- CSV logging

No semantic data is recorded:
- no key identities
- no mouse coordinates
- no application names
- no typed content

Usage
-----
Synthetic:
    python lacunar_mirror_v0.py --mode synthetic --plot

Live:
    pip install pynput matplotlib
    python lacunar_mirror_v0.py --mode live --plot

Stop live mode with Ctrl+C.
"""

from __future__ import annotations

import argparse
import csv
import math
import queue
import random
import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Deque, Iterable, Optional, Tuple


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EngineConfig:
    # Core dynamics
    mass: float = 1.0
    baseline_damping: float = 0.34
    idle_damping_gain: float = 0.85
    baseline_stiffness: float = 1.20
    compliance_sensitivity: float = 0.55
    nonlinearity: float = 0.12
    energy_gain: float = 0.85
    irregularity_gain: float = 0.20
    memory_rate: float = 0.004
    tempo_sensitivity: float = 0.45

    # Bounded slow state
    slow_state_min: float = -0.75
    slow_state_max: float = 0.75
    slow_state_rest: float = 0.0

    # Input safety
    max_force: float = 2.5
    max_idle_norm: float = 1.0

    # Numerical safety
    max_abs_q: float = 8.0
    max_abs_p: float = 8.0


@dataclass
class TelemetryFrame:
    # All values should be normalised to [0, 1].
    activity: float = 0.0       # r
    irregularity: float = 0.0   # rho
    tempo: float = 0.0          # tau
    idle: float = 0.0           # delta


@dataclass
class EngineState:
    q: float = 0.0
    p: float = 0.0
    s: float = 0.0
    energy: float = 0.0
    stiffness: float = 0.0
    damping: float = 0.0
    force: float = 0.0


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


def robust_sigmoid(value: float, centre: float, scale: float) -> float:
    """Map a raw value to [0, 1] without overflow."""
    scale = max(scale, 1e-9)
    z = clamp((value - centre) / scale, -30.0, 30.0)
    return 1.0 / (1.0 + math.exp(-z))


# ---------------------------------------------------------------------------
# Dynamics engine
# ---------------------------------------------------------------------------

class LacunarDynamicsEngine:
    """
    Minimal 3-state dynamical system.

    q: displacement
    p: momentum
    s: slow compliance offset

    The implementation is intentionally modest:
    - deterministic
    - bounded
    - renderer-independent
    - no state labels
    """

    def __init__(self, config: Optional[EngineConfig] = None) -> None:
        self.cfg = config or EngineConfig()
        self.state = EngineState(
            q=0.0,
            p=0.0,
            s=self.cfg.slow_state_rest,
        )
        self._recompute_derived(TelemetryFrame())

    def reset(self) -> None:
        self.state = EngineState(
            q=0.0,
            p=0.0,
            s=self.cfg.slow_state_rest,
        )
        self._recompute_derived(TelemetryFrame())

    def step(self, telemetry: TelemetryFrame, dt: float) -> EngineState:
        if dt <= 0.0:
            raise ValueError("dt must be positive")

        r = clamp(telemetry.activity, 0.0, 1.0)
        rho = clamp(telemetry.irregularity, 0.0, 1.0)
        tau = clamp(telemetry.tempo, 0.0, 1.0)
        idle = clamp(telemetry.idle, 0.0, self.cfg.max_idle_norm)

        # Slow compliance target: pace alters the instrument's natural tone,
        # but only gradually.
        target_s = clamp(
            self.cfg.slow_state_rest
            + self.cfg.tempo_sensitivity * (2.0 * tau - 1.0),
            self.cfg.slow_state_min,
            self.cfg.slow_state_max,
        )

        s_dot = self.cfg.memory_rate * (target_s - self.state.s)
        next_s = clamp(
            self.state.s + dt * s_dot,
            self.cfg.slow_state_min,
            self.cfg.slow_state_max,
        )

        stiffness = max(
            0.05,
            self.cfg.baseline_stiffness
            + self.cfg.compliance_sensitivity * next_s,
        )
        damping = max(
            0.01,
            self.cfg.baseline_damping
            + self.cfg.idle_damping_gain * idle,
        )

        # Positive interaction energy only. Irregularity adds texture by changing
        # the forcing magnitude, not by assigning a negative meaning.
        force = self.cfg.energy_gain * r * (
            1.0 + self.cfg.irregularity_gain * rho
        )
        force = clamp(force, 0.0, self.cfg.max_force)

        q = self.state.q
        p = self.state.p

        # Semi-implicit Euler:
        # p' = -kq - beta*q^3 - d*p + force
        p_dot = (
            -stiffness * q
            - self.cfg.nonlinearity * (q ** 3)
            - damping * p
            + force
        )
        next_p = p + dt * p_dot
        next_q = q + dt * (next_p / self.cfg.mass)

        # Hard safety bounds are not part of the "feel"; they prevent numerical
        # corruption if parameters are accidentally edited into an unsafe region.
        next_p = clamp(next_p, -self.cfg.max_abs_p, self.cfg.max_abs_p)
        next_q = clamp(next_q, -self.cfg.max_abs_q, self.cfg.max_abs_q)

        self.state.q = next_q
        self.state.p = next_p
        self.state.s = next_s
        self._recompute_derived(
            TelemetryFrame(r, rho, tau, idle),
            stiffness=stiffness,
            damping=damping,
            force=force,
        )
        return EngineState(**vars(self.state))

    def _recompute_derived(
        self,
        telemetry: TelemetryFrame,
        stiffness: Optional[float] = None,
        damping: Optional[float] = None,
        force: Optional[float] = None,
    ) -> None:
        stiffness = (
            stiffness
            if stiffness is not None
            else max(
                0.05,
                self.cfg.baseline_stiffness
                + self.cfg.compliance_sensitivity * self.state.s,
            )
        )
        damping = (
            damping
            if damping is not None
            else self.cfg.baseline_damping
            + self.cfg.idle_damping_gain * telemetry.idle
        )
        force = force if force is not None else 0.0

        kinetic = (self.state.p ** 2) / (2.0 * self.cfg.mass)
        elastic = 0.5 * stiffness * (self.state.q ** 2)
        nonlinear = 0.25 * self.cfg.nonlinearity * (self.state.q ** 4)

        self.state.energy = kinetic + elastic + nonlinear
        self.state.stiffness = stiffness
        self.state.damping = damping
        self.state.force = force


# ---------------------------------------------------------------------------
# Synthetic telemetry
# ---------------------------------------------------------------------------

class SyntheticTelemetry:
    """
    Repeatable staged input:
      0-8s   idle
      8-22s  steady work
      22-32s fragmented bursts
      32-42s quiet thought / near-idle
      42-58s steady faster work
      58-70s full idle and settling
    """

    def __init__(self, seed: int = 7) -> None:
        self.rng = random.Random(seed)

    def frame_at(self, t: float) -> TelemetryFrame:
        if t < 8.0:
            return TelemetryFrame(0.0, 0.0, 0.2, min(t / 5.0, 1.0))

        if t < 22.0:
            wobble = 0.025 * math.sin(t * 1.4)
            return TelemetryFrame(
                activity=clamp(0.52 + wobble, 0.0, 1.0),
                irregularity=0.10,
                tempo=0.50,
                idle=0.0,
            )

        if t < 32.0:
            burst = 0.75 if int(t * 2.0) % 3 else 0.15
            noise = self.rng.uniform(-0.12, 0.12)
            return TelemetryFrame(
                activity=clamp(burst + noise, 0.0, 1.0),
                irregularity=0.82,
                tempo=0.74,
                idle=0.0,
            )

        if t < 42.0:
            # Deliberate pause / reading. The engine should settle gently,
            # not treat the silence as failure.
            idle = clamp((t - 32.0) / 8.0, 0.0, 1.0)
            return TelemetryFrame(
                activity=0.03,
                irregularity=0.15,
                tempo=0.28,
                idle=idle,
            )

        if t < 58.0:
            wobble = 0.035 * math.sin(t * 1.9)
            return TelemetryFrame(
                activity=clamp(0.68 + wobble, 0.0, 1.0),
                irregularity=0.14,
                tempo=0.69,
                idle=0.0,
            )

        idle = clamp((t - 58.0) / 7.0, 0.0, 1.0)
        return TelemetryFrame(0.0, 0.0, 0.2, idle)


# ---------------------------------------------------------------------------
# Live telemetry
# ---------------------------------------------------------------------------

class LiveTimingTelemetry:
    """
    Captures event timing only.

    Raw timing samples are held briefly in memory and converted into normalised
    activity, irregularity, tempo, and idle signals.
    """

    def __init__(
        self,
        window_seconds: float = 2.0,
        mouse_gate_ns: int = 16_000_000,
    ) -> None:
        self.window_seconds = window_seconds
        self.mouse_gate_ns = mouse_gate_ns

        self.events: Deque[float] = deque()
        self.lock = threading.Lock()
        self.last_event_time = time.perf_counter()
        self.last_mouse_ns = 0
        self.listeners = []

        # Conservative initial calibration anchors. These adapt slowly.
        self.rate_centre = 8.0
        self.rate_scale = 4.0
        self.interval_centre = 0.12
        self.interval_scale = 0.08

    def start(self) -> None:
        try:
            from pynput import keyboard, mouse
        except ImportError as exc:
            raise RuntimeError(
                "Live mode requires pynput. Install with: pip install pynput"
            ) from exc

        def record_event() -> None:
            now = time.perf_counter()
            with self.lock:
                self.events.append(now)
                self.last_event_time = now

        def on_move(_x: int, _y: int) -> None:
            now_ns = time.perf_counter_ns()
            if now_ns - self.last_mouse_ns < self.mouse_gate_ns:
                return
            self.last_mouse_ns = now_ns
            record_event()

        def on_press(_key: object) -> None:
            record_event()

        mouse_listener = mouse.Listener(on_move=on_move)
        keyboard_listener = keyboard.Listener(on_press=on_press)
        mouse_listener.start()
        keyboard_listener.start()
        self.listeners = [mouse_listener, keyboard_listener]

    def stop(self) -> None:
        for listener in self.listeners:
            try:
                listener.stop()
            except Exception:
                pass
        self.listeners = []

    def sample(self) -> TelemetryFrame:
        now = time.perf_counter()

        with self.lock:
            while self.events and now - self.events[0] > self.window_seconds:
                self.events.popleft()
            times = list(self.events)
            idle_seconds = max(0.0, now - self.last_event_time)

        rate = len(times) / self.window_seconds
        activity = robust_sigmoid(rate, self.rate_centre, self.rate_scale)

        if len(times) >= 4:
            intervals = [
                b - a for a, b in zip(times, times[1:]) if b > a
            ]
        else:
            intervals = []

        if len(intervals) >= 3:
            mean_interval = statistics.fmean(intervals)
            stdev = statistics.pstdev(intervals)
            cv = stdev / mean_interval if mean_interval > 1e-9 else 0.0
            irregularity = clamp(cv / 1.2, 0.0, 1.0)

            median_interval = statistics.median(intervals)
            tempo = 1.0 - robust_sigmoid(
                median_interval,
                self.interval_centre,
                self.interval_scale,
            )
        else:
            irregularity = 0.0
            tempo = 0.0

        idle = clamp(idle_seconds / 8.0, 0.0, 1.0)
        return TelemetryFrame(activity, irregularity, tempo, idle)


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

class LivePlot:
    def __init__(self, history_seconds: float, update_hz: float) -> None:
        try:
            import matplotlib.pyplot as plt
        except ImportError as exc:
            raise RuntimeError(
                "Plotting requires matplotlib. Install with: pip install matplotlib"
            ) from exc

        self.plt = plt
        self.max_points = max(10, int(history_seconds * update_hz))
        self.t: Deque[float] = deque(maxlen=self.max_points)
        self.q: Deque[float] = deque(maxlen=self.max_points)
        self.p: Deque[float] = deque(maxlen=self.max_points)
        self.s: Deque[float] = deque(maxlen=self.max_points)
        self.energy: Deque[float] = deque(maxlen=self.max_points)

        self.fig, self.axes = plt.subplots(4, 1, sharex=True, figsize=(10, 8))
        self.lines = []
        labels = ("q — displacement", "p — momentum", "s — slow compliance", "energy")
        for ax, label in zip(self.axes, labels):
            line, = ax.plot([], [])
            ax.set_ylabel(label)
            ax.grid(True, alpha=0.25)
            self.lines.append(line)
        self.axes[-1].set_xlabel("seconds")
        self.fig.suptitle("Lacunar Mirror v0 — dynamics bench")
        plt.tight_layout()
        plt.ion()
        plt.show(block=False)

    def update(self, t: float, state: EngineState) -> None:
        self.t.append(t)
        self.q.append(state.q)
        self.p.append(state.p)
        self.s.append(state.s)
        self.energy.append(state.energy)

        series = (self.q, self.p, self.s, self.energy)
        for ax, line, values in zip(self.axes, self.lines, series):
            line.set_data(self.t, values)
            ax.relim()
            ax.autoscale_view()
        self.fig.canvas.draw_idle()
        self.fig.canvas.flush_events()

    def close(self) -> None:
        self.plt.ioff()
        self.plt.show()


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> None:
    engine = LacunarDynamicsEngine()
    update_hz = args.hz
    dt = 1.0 / update_hz
    duration = args.duration

    plotter = LivePlot(args.history, update_hz) if args.plot else None
    synthetic = SyntheticTelemetry(seed=args.seed)
    live = LiveTimingTelemetry() if args.mode == "live" else None

    log_path = Path(args.log).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    if live:
        live.start()

    start = time.perf_counter()
    next_tick = start
    previous_step_time = start

    try:
        with log_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "elapsed_s",
                    "activity",
                    "irregularity",
                    "tempo",
                    "idle",
                    "q",
                    "p",
                    "s",
                    "energy",
                    "stiffness",
                    "damping",
                    "force",
                ]
            )

            last_print = 0.0
            while True:
                now = time.perf_counter()
                elapsed = now - start

                if args.mode == "synthetic" and elapsed >= duration:
                    break

                if now < next_tick:
                    time.sleep(min(next_tick - now, 0.005))
                    continue

                # Use actual elapsed step, capped to prevent a stalled debugger or
                # window drag from injecting one giant numerical jump.
                actual_dt = clamp(now - previous_step_time, 0.0, dt * 4.0)
                previous_step_time = now
                next_tick += dt

                telemetry = (
                    synthetic.frame_at(elapsed)
                    if args.mode == "synthetic"
                    else live.sample()
                )
                state = engine.step(telemetry, actual_dt)

                writer.writerow(
                    [
                        f"{elapsed:.6f}",
                        f"{telemetry.activity:.6f}",
                        f"{telemetry.irregularity:.6f}",
                        f"{telemetry.tempo:.6f}",
                        f"{telemetry.idle:.6f}",
                        f"{state.q:.6f}",
                        f"{state.p:.6f}",
                        f"{state.s:.6f}",
                        f"{state.energy:.6f}",
                        f"{state.stiffness:.6f}",
                        f"{state.damping:.6f}",
                        f"{state.force:.6f}",
                    ]
                )

                if plotter:
                    plotter.update(elapsed, state)

                if elapsed - last_print >= 0.5:
                    print(
                        "\r"
                        f"t={elapsed:6.1f}s  "
                        f"r={telemetry.activity:4.2f}  "
                        f"rho={telemetry.irregularity:4.2f}  "
                        f"q={state.q:7.3f}  "
                        f"p={state.p:7.3f}  "
                        f"s={state.s:6.3f}  "
                        f"E={state.energy:7.3f}",
                        end="",
                        flush=True,
                    )
                    last_print = elapsed

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        if live:
            live.stop()
        if plotter:
            plotter.close()

    print(f"\nCSV written to: {log_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Lacunar Mirror v0 dynamics bench rig"
    )
    parser.add_argument(
        "--mode",
        choices=("synthetic", "live"),
        default="synthetic",
        help="Use repeatable synthetic input or live keyboard/mouse timing.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=70.0,
        help="Synthetic-mode duration in seconds.",
    )
    parser.add_argument(
        "--hz",
        type=float,
        default=120.0,
        help="Dynamics update rate.",
    )
    parser.add_argument(
        "--history",
        type=float,
        default=30.0,
        help="Seconds of plot history.",
    )
    parser.add_argument(
        "--plot",
        action="store_true",
        help="Show q, p, s, and energy using matplotlib.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=7,
        help="Random seed for synthetic fragmented input.",
    )
    parser.add_argument(
        "--log",
        default="lacunar_mirror_session.csv",
        help="CSV output path.",
    )
    return parser


if __name__ == "__main__":
    run(build_parser().parse_args())
