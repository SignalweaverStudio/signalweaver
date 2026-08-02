from __future__ import annotations

import math
import time
import tkinter as tk
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageTk


WIDTH = 640
HEIGHT = 640
FPS = 30

LENS_RADIUS = 270
LENS_CENTRE_X = WIDTH // 2
LENS_CENTRE_Y = HEIGHT // 2


@dataclass
class SyntheticField:
    q: float
    p: float
    activity: float
    tempo: float
    irregularity: float
    idle: float


class LiquidLensSandbox:
    """
    Disposable Liquid Lens visual sandbox.

    This renderer is deliberately synthetic. It does not connect to Lacuna's
    acquisition or engine layers.

    Keys:
        1 — Idle
        2 — Typing
        3 — Mouse stroke
        4 — Fragmented activity
        5 — Recovery
        A — Toggle automatic cycling
        Esc — Close
    """

    STATE_NAMES = {
        1: "Idle",
        2: "Typing",
        3: "Mouse stroke",
        4: "Fragmented activity",
        5: "Recovery",
    }

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Lacuna Liquid Lens — Visual Sandbox v0.1")
        self.root.configure(bg="#08090a")
        self.root.resizable(False, False)

        self.canvas = tk.Canvas(
            root,
            width=WIDTH,
            height=HEIGHT,
            bg="#08090a",
            highlightthickness=0,
        )
        self.canvas.pack()

        self.mode = 1
        self.auto_cycle = False
        self.started = time.perf_counter()
        self.last_mode_change = self.started

        self.photo: ImageTk.PhotoImage | None = None
        self.image_id = self.canvas.create_image(0, 0, anchor="nw")

        self.status_id = self.canvas.create_text(
            24,
            24,
            anchor="nw",
            fill="#a8a8a8",
            font=("Segoe UI", 11),
            text="",
        )

        self.help_id = self.canvas.create_text(
            24,
            HEIGHT - 24,
            anchor="sw",
            fill="#666666",
            font=("Segoe UI", 9),
            text="1 Idle   2 Typing   3 Mouse stroke   4 Fragmented   5 Recovery   A Auto",
        )

        self.root.bind("<Key>", self.on_key)
        self.canvas.focus_set()

        yy, xx = np.mgrid[0:HEIGHT, 0:WIDTH]
        self.x = (xx - LENS_CENTRE_X) / LENS_RADIUS
        self.y = (yy - LENS_CENTRE_Y) / LENS_RADIUS
        self.radius = np.sqrt(self.x * self.x + self.y * self.y)
        self.angle = np.arctan2(self.y, self.x)
        self.inside = self.radius <= 1.0

        self.root.after(0, self.update)

    def on_key(self, event: tk.Event) -> None:
        key = event.keysym.lower()

        if key == "escape":
            self.root.destroy()
            return

        if key == "a":
            self.auto_cycle = not self.auto_cycle
            self.last_mode_change = time.perf_counter()
            return

        if key in {"1", "2", "3", "4", "5"}:
            self.mode = int(key)
            self.auto_cycle = False
            self.last_mode_change = time.perf_counter()

    def synthetic_field(self, elapsed: float) -> SyntheticField:
        if self.mode == 1:
            return SyntheticField(
                q=0.10 + 0.01 * math.sin(elapsed * 0.18),
                p=0.015 * math.sin(elapsed * 0.25),
                activity=0.06,
                tempo=0.10,
                irregularity=0.04,
                idle=0.98,
            )

        if self.mode == 2:
            return SyntheticField(
                q=0.30 + 0.10 * math.sin(elapsed * 1.8),
                p=0.25 * math.sin(elapsed * 2.4),
                activity=0.52,
                tempo=0.75,
                irregularity=0.18,
                idle=0.10,
            )

        if self.mode == 3:
            return SyntheticField(
                q=0.68 * math.sin(elapsed * 0.62),
                p=0.78 * math.cos(elapsed * 0.62),
                activity=0.90,
                tempo=0.38,
                irregularity=0.12,
                idle=0.02,
            )

        if self.mode == 4:
            return SyntheticField(
                q=0.34 * math.sin(elapsed * 0.83),
                p=0.42 * math.cos(elapsed * 1.17),
                activity=0.74,
                tempo=0.64,
                irregularity=0.82,
                idle=0.04,
            )

        decay = math.exp(-0.20 * (elapsed % 30.0))
        return SyntheticField(
            q=0.106 + 0.62 * decay * math.sin(elapsed * 1.1),
            p=0.72 * decay * math.cos(elapsed * 1.1),
            activity=0.60 * decay,
            tempo=0.34,
            irregularity=0.15 * decay,
            idle=1.0 - decay,
        )

    def make_frame(self, elapsed: float, field: SyntheticField) -> Image.Image:
        x = self.x
        y = self.y
        r = self.radius
        theta = self.angle

        # Optical well: dark centre, slightly brighter sapphire edge.
        depth = np.clip(1.0 - r, 0.0, 1.0)
        glass = 0.10 + 0.18 * np.power(depth, 0.45)

        # Broad coherent displacement controlled by q and p.
        flow_angle = math.atan2(field.p, field.q + 1e-9)
        directional = x * math.cos(flow_angle) + y * math.sin(flow_angle)
        transverse = -x * math.sin(flow_angle) + y * math.cos(flow_angle)

        broad_fold = np.exp(
            -(
                (directional - 0.22 * field.q) ** 2 / 0.22
                + transverse**2 / 0.055
            )
        )

        # Smooth standing waves for typing-like states.
        wave_frequency = 5.0 + 6.0 * field.tempo
        standing_wave = (
            0.5
            + 0.5
            * np.cos(
                wave_frequency * r
                - elapsed * (0.45 + 0.8 * field.tempo)
                + 0.4 * math.sin(elapsed * 0.3)
            )
        )
        standing_wave *= np.exp(-2.0 * r * r)

        # Continuous ribbon: stretched, never spiky.
        ribbon_curve = (
            transverse
            - 0.16 * np.sin(2.4 * directional + elapsed * 0.35)
            - 0.08 * field.p
        )
        ribbon = np.exp(
            -(ribbon_curve**2) / (0.012 + 0.035 * (1.0 - field.activity))
        )
        ribbon *= np.exp(-1.15 * directional**2)

        # Fragmented state uses a few smooth mercury-like masses.
        droplets = np.zeros_like(r)

        if field.irregularity > 0.45:
            count = 3
            orbital_radius = 0.32 + 0.05 * math.sin(elapsed * 0.4)

            for index in range(count):
                orbit = elapsed * (0.18 + index * 0.025) + index * 2.1
                cx = orbital_radius * math.cos(orbit)
                cy = orbital_radius * math.sin(orbit)
                size = 0.055 + 0.014 * math.sin(elapsed * 0.7 + index)
                droplets += np.exp(
                    -((x - cx) ** 2 + (y - cy) ** 2) / max(size, 0.02)
                )

        material = (
            0.55 * broad_fold
            + 0.55 * field.activity * standing_wave
            + 0.90 * field.activity * ribbon
            + 0.65 * field.irregularity * droplets
        )

        # Keep the medium continuous and calm.
        material = np.tanh(material * 1.65)
        material *= np.clip(1.0 - np.power(r, 5.0), 0.0, 1.0)

        # Optical highlights suggest a concave coated lens.
        rim = np.exp(-((r - 0.965) ** 2) / 0.0009)
        inner_rim = np.exp(-((r - 0.875) ** 2) / 0.004)

        light_direction = np.clip(
            0.55 - 0.35 * x - 0.50 * y,
            0.0,
            1.0,
        )

        highlight = rim * light_direction
        internal_reflection = inner_rim * (0.45 + 0.55 * np.cos(theta - 0.8))

        # Silver-black material over an optical abyss.
        base = glass + 0.16 * material
        silver = 0.48 * material + 0.20 * material**2

        red = base + silver * 0.76
        green = base + silver * 0.82
        blue = base + silver * 0.86

        # Restrained anti-reflective purple/green edge colour.
        red += 0.30 * highlight
        green += 0.20 * highlight + 0.09 * internal_reflection
        blue += 0.38 * highlight + 0.14 * internal_reflection

        # Subtle glass reflection.
        reflection = np.exp(
            -(
                ((x + 0.30) / 0.42) ** 2
                + ((y + 0.38) / 0.18) ** 2
            )
        )
        red += 0.06 * reflection
        green += 0.065 * reflection
        blue += 0.075 * reflection

        # Outside the optical aperture remains dark.
        edge_shadow = np.clip((r - 1.0) / 0.07, 0.0, 1.0)
        outside_value = 0.012 * (1.0 - edge_shadow)

        red = np.where(self.inside, red, outside_value)
        green = np.where(self.inside, green, outside_value)
        blue = np.where(self.inside, blue, outside_value)

        # Fine circular housing line, deliberately restrained.
        housing = np.exp(-((r - 1.025) ** 2) / 0.00045)
        red += 0.42 * housing
        green += 0.31 * housing
        blue += 0.16 * housing

        rgb = np.stack([red, green, blue], axis=-1)
        rgb = np.clip(rgb, 0.0, 1.0)
        rgb = np.power(rgb, 0.68)

        return Image.fromarray(
            np.uint8(rgb * 255.0),
            mode="RGB",
        )

    def update(self) -> None:
        now = time.perf_counter()
        elapsed = now - self.started

        if self.auto_cycle and now - self.last_mode_change >= 10.0:
            self.mode = 1 + (self.mode % 5)
            self.last_mode_change = now

        field = self.synthetic_field(elapsed)
        image = self.make_frame(elapsed, field)

        self.photo = ImageTk.PhotoImage(image)
        self.canvas.itemconfigure(self.image_id, image=self.photo)
        self.canvas.tag_raise(self.status_id)
        self.canvas.tag_raise(self.help_id)

        auto_text = "ON" if self.auto_cycle else "OFF"
        self.canvas.itemconfigure(
            self.status_id,
            text=(
                f"{self.STATE_NAMES[self.mode]}   "
                f"q {field.q:+.2f}   p {field.p:+.2f}   "
                f"activity {field.activity:.2f}   "
                f"auto {auto_text}"
            ),
        )

        self.root.after(max(1, int(1000 / FPS)), self.update)


def main() -> None:
    root = tk.Tk()
    LiquidLensSandbox(root)
    root.mainloop()


if __name__ == "__main__":
    main()
