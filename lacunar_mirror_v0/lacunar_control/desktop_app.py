"""Lacuna desktop instrument.

Renders the engine's live phase-space position (q, p) as a single
constant-size point with a short optical persistence trail, inside a
circular field with no axes, scale, or labels. This is a minimal
phase-space instrument, not a dashboard: energy and force are never
displayed directly, only felt through the point's motion.
"""

import math
from collections import deque
import tkinter as tk
from tkinter import ttk

from lacunar_mirror_v0 import (
    LacunarDynamicsEngine,
    LiveTimingTelemetry,
)

from .live_acquisition import LiveAcquisitionSource
from .recorder_session import RecorderSession


class LacunaDesktopApp:
    REFRESH_MS = 16

    PHASE_SCALE_PX_PER_UNIT = 100.0
    POINT_RADIUS_PX = 5
    TRAIL_LENGTH = 180

    BG_WINDOW = "#171717"
    BG_FIELD = "#202020"
    FIELD_EDGE = "#333333"
    POINT_COLOUR = (232, 228, 220)
    TRAIL_FLOOR_COLOUR = (32, 32, 32)
    STATUS_COLOUR = "#77736d"

    def __init__(self, root: tk.Tk) -> None:
        self._root = root
        self._root.title("Lacuna")
        self._root.geometry("430x430")
        self._root.minsize(360, 360)
        self._root.configure(bg=self.BG_WINDOW)

        self._session = self._new_session()
        self._trail: deque[tuple[float, float]] = deque(
            maxlen=self.TRAIL_LENGTH
        )

        self._status_var = tk.StringVar(value="Ready")

        self._build_ui()
        self._refresh()

    @staticmethod
    def _new_session() -> RecorderSession:
        return RecorderSession(
            acquisition_source=LiveAcquisitionSource(
                LiveTimingTelemetry(
                    mouse_gate_ns=50_000_000,
                )
            ),
            engine=LacunarDynamicsEngine(),
        )

    def _build_ui(self) -> None:
        style = ttk.Style()
        style.configure(
            "Lacuna.TButton",
            font=("Segoe UI", 9),
            padding=(10, 5),
        )

        header = tk.Frame(
            self._root,
            bg=self.BG_WINDOW,
            padx=14,
            pady=10,
        )
        header.pack(fill="x")

        tk.Label(
            header,
            text="Lacuna",
            font=("Segoe UI", 16, "bold"),
            fg="#e8e4dc",
            bg=self.BG_WINDOW,
        ).pack(side="left")

        tk.Label(
            header,
            textvariable=self._status_var,
            font=("Segoe UI", 10),
            fg=self.STATUS_COLOUR,
            bg=self.BG_WINDOW,
        ).pack(side="right")

        instrument_frame = tk.Frame(
            self._root,
            bg=self.BG_WINDOW,
        )
        instrument_frame.pack(
            fill="both",
            expand=True,
            padx=14,
            pady=(0, 8),
        )

        self._canvas = tk.Canvas(
            instrument_frame,
            bg=self.BG_WINDOW,
            highlightthickness=0,
        )
        self._canvas.pack(fill="both", expand=True)

        controls = tk.Frame(
            self._root,
            bg=self.BG_WINDOW,
            padx=14,
            pady=10,
        )
        controls.pack(fill="x")

        self._start_button = ttk.Button(
            controls,
            text="Start",
            command=self._start,
            style="Lacuna.TButton",
        )
        self._start_button.pack(side="left")

        self._stop_button = ttk.Button(
            controls,
            text="Stop",
            command=self._stop,
            style="Lacuna.TButton",
        )
        self._stop_button.pack(side="left", padx=(10, 0))

    def _start(self) -> None:
        snapshot = self._session.snapshot()

        if snapshot.state.value == "recorded":
            self._session = self._new_session()
            self._trail.clear()

        self._session.start()

    def _stop(self) -> None:
        snapshot = self._session.snapshot()

        if snapshot.state.value == "recording":
            self._session.request_stop()

    @staticmethod
    def _lerp_colour(
        c_from: tuple[int, int, int],
        c_to: tuple[int, int, int],
        t: float,
    ) -> str:
        t = max(0.0, min(1.0, t))
        r = round(c_from[0] + (c_to[0] - c_from[0]) * t)
        g = round(c_from[1] + (c_to[1] - c_from[1]) * t)
        b = round(c_from[2] + (c_to[2] - c_from[2]) * t)
        return f"#{r:02x}{g:02x}{b:02x}"

    def _draw_instrument(self, state) -> None:
        self._canvas.delete("all")

        width = max(self._canvas.winfo_width(), 1)
        height = max(self._canvas.winfo_height(), 1)

        centre_x = width / 2
        centre_y = height / 2

        aperture_radius = max(min(width, height) / 2 - 14, 10)

        self._canvas.create_oval(
            centre_x - aperture_radius,
            centre_y - aperture_radius,
            centre_x + aperture_radius,
            centre_y + aperture_radius,
            fill=self.BG_FIELD,
            outline=self.FIELD_EDGE,
            width=1,
        )

        if state is None:
            q, p = 0.0, 0.0
        else:
            q, p = state.q, state.p

        self._trail.append((q, p))
        draw_radius = aperture_radius * 0.92

        def to_canvas(
            qq: float,
            pp: float,
        ) -> tuple[float, float]:
            dx = qq * self.PHASE_SCALE_PX_PER_UNIT
            dy = -pp * self.PHASE_SCALE_PX_PER_UNIT
            distance = math.hypot(dx, dy)

            if distance > draw_radius and distance > 0:
                scale = draw_radius / distance
                dx *= scale
                dy *= scale

            return centre_x + dx, centre_y + dy

        trail_len = len(self._trail)

        for index, (tq, tp) in enumerate(self._trail):
            age_fraction = index / max(trail_len - 1, 1)
            x, y = to_canvas(tq, tp)

            if index == trail_len - 1:
                r = self.POINT_RADIUS_PX
                colour = self._lerp_colour(
                    self.TRAIL_FLOOR_COLOUR,
                    self.POINT_COLOUR,
                    1.0,
                )
            else:
                r = 1.5
                colour = self._lerp_colour(
                    self.TRAIL_FLOOR_COLOUR,
                    self.POINT_COLOUR,
                    age_fraction,
                )

            self._canvas.create_oval(
                x - r,
                y - r,
                x + r,
                y + r,
                fill=colour,
                outline="",
            )

    def _refresh(self) -> None:
        snapshot = self._session.snapshot()

        self._status_var.set(snapshot.state.value.title())
        self._draw_instrument(snapshot.latest_engine_state)

        if snapshot.state.value == "recording":
            self._start_button.state(["disabled"])
            self._stop_button.state(["!disabled"])
        elif snapshot.state.value == "stopping":
            self._start_button.state(["disabled"])
            self._stop_button.state(["disabled"])
        else:
            self._start_button.state(["!disabled"])
            self._stop_button.state(["disabled"])

        self._root.after(self.REFRESH_MS, self._refresh)


def main() -> None:
    root = tk.Tk()
    LacunaDesktopApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()