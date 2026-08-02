import tkinter as tk
from tkinter import ttk

from lacunar_mirror_v0 import (
    LacunarDynamicsEngine,
    LiveTimingTelemetry,
)

from .live_acquisition import LiveAcquisitionSource
from .recorder_session import RecorderSession


class LacunaDesktopApp:
    def __init__(self, root: tk.Tk) -> None:
        self._root = root
        self._root.title("Lacuna")
        self._root.geometry("360x260")

        self._session = RecorderSession(
            acquisition_source=LiveAcquisitionSource(
                LiveTimingTelemetry()
            ),
            engine=LacunarDynamicsEngine(),
        )

        self._status_var = tk.StringVar(value="Ready")
        self._samples_var = tk.StringVar(value="0")
        self._energy_var = tk.StringVar(value="—")
        self._force_var = tk.StringVar(value="—")

        self._build_ui()
        self._refresh()

    def _build_ui(self) -> None:
        frame = ttk.Frame(self._root, padding=20)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text="Lacuna",
            font=("Segoe UI", 20, "bold"),
        ).pack(pady=(0, 16))

        ttk.Label(
            frame,
            textvariable=self._status_var,
        ).pack(pady=(0, 12))

        ttk.Label(
            frame,
            textvariable=self._samples_var,
        ).pack()

        ttk.Label(
            frame,
            textvariable=self._energy_var,
        ).pack()

        ttk.Label(
            frame,
            textvariable=self._force_var,
        ).pack()

        button_frame = ttk.Frame(frame)
        button_frame.pack(pady=20)

        self._start_button = ttk.Button(
            button_frame,
            text="Start",
            command=self._start,
        )
        self._start_button.pack(side="left", padx=5)

        self._stop_button = ttk.Button(
            button_frame,
            text="Stop",
            command=self._stop,
        )
        self._stop_button.pack(side="left", padx=5)

    def _start(self) -> None:
        snapshot = self._session.snapshot()

        if snapshot.state.value == "recorded":
            self._session = RecorderSession(
                acquisition_source=LiveAcquisitionSource(
                    LiveTimingTelemetry()
                ),
                engine=LacunarDynamicsEngine(),
            )

        self._session.start()

    def _stop(self) -> None:
        snapshot = self._session.snapshot()

        if snapshot.state.value == "recording":
            self._session.request_stop()

    def _refresh(self) -> None:
        snapshot = self._session.snapshot()

        self._status_var.set(
            f"Status: {snapshot.state.value.title()}"
        )
        self._samples_var.set(
            f"Samples: {snapshot.sample_count}"
        )

        state = snapshot.latest_engine_state

        if state is None:
            self._energy_var.set("Energy: —")
            self._force_var.set("Force: —")
        else:
            self._energy_var.set(
                f"Energy: {state.energy:.6f}"
            )
            self._force_var.set(
                f"Force: {state.force:.6f}"
            )

        if snapshot.state.value == "recording":
            self._start_button.state(["disabled"])
            self._stop_button.state(["!disabled"])
        elif snapshot.state.value == "stopping":
            self._start_button.state(["disabled"])
            self._stop_button.state(["disabled"])
        else:
            self._start_button.state(["!disabled"])
            self._stop_button.state(["disabled"])

        self._root.after(100, self._refresh)


def main() -> None:
    root = tk.Tk()
    LacunaDesktopApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()