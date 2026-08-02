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

CX = WIDTH // 2
CY = HEIGHT // 2
RADIUS = 270


@dataclass
class SyntheticField:
    q: float
    p: float
    activity: float
    tempo: float
    irregularity: float
    idle: float


class LiquidLensV02:
    """
    Liquid Lens sandbox v0.2

    One dark cohesive body inside an optical cavity.

    Keys:
        1 Idle
        2 Typing
        3 Mouse stroke
        4 Fragmented
        5 Recovery
        A Automatic cycling
        Esc Close
    """

    NAMES = {
        1: "Idle",
        2: "Typing",
        3: "Mouse stroke",
        4: "Fragmented",
        5: "Recovery",
    }

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Lacuna Liquid Lens — Sandbox v0.2")
        self.root.configure(bg="#070809")
        self.root.resizable(False, False)

        self.canvas = tk.Canvas(
            root,
            width=WIDTH,
            height=HEIGHT,
            bg="#070809",
            highlightthickness=0,
        )
        self.canvas.pack()
        self.canvas.focus_set()

        self.image_id = self.canvas.create_image(0, 0, anchor="nw")
        self.status_id = self.canvas.create_text(
            22,
            22,
            anchor="nw",
            fill="#b5b5b5",
            font=("Segoe UI", 11),
        )
        self.help_id = self.canvas.create_text(
            22,
            HEIGHT - 22,
            anchor="sw",
            fill="#686868",
            font=("Segoe UI", 9),
            text="1 Idle   2 Typing   3 Mouse   4 Fragmented   5 Recovery   A Auto",
        )

        self.photo: ImageTk.PhotoImage | None = None
        self.mode = 1
        self.auto = False
        self.started = time.perf_counter()
        self.last_mode_change = self.started

        yy, xx = np.mgrid[0:HEIGHT, 0:WIDTH]
        self.x = (xx - CX) / RADIUS
        self.y = (yy - CY) / RADIUS
        self.r = np.sqrt(self.x * self.x + self.y * self.y)
        self.theta = np.arctan2(self.y, self.x)
        self.inside = self.r <= 1.0

        self.root.bind("<Key>", self.on_key)
        self.root.after(0, self.update)

    def on_key(self, event: tk.Event) -> None:
        key = event.keysym.lower()

        if key == "escape":
            self.root.destroy()
            return

        if key == "a":
            self.auto = not self.auto
            self.last_mode_change = time.perf_counter()
            return

        if key in {"1", "2", "3", "4", "5"}:
            self.mode = int(key)
            self.auto = False
            self.last_mode_change = time.perf_counter()

    def field(self, elapsed: float) -> SyntheticField:
        if self.mode == 1:
            return SyntheticField(
                q=0.106,
                p=0.005 * math.sin(elapsed * 0.22),
                activity=0.04,
                tempo=0.08,
                irregularity=0.03,
                idle=0.99,
            )

        if self.mode == 2:
            return SyntheticField(
                q=0.24 + 0.05 * math.sin(elapsed * 1.4),
                p=0.16 * math.sin(elapsed * 1.9),
                activity=0.48,
                tempo=0.72,
                irregularity=0.16,
                idle=0.12,
            )

        if self.mode == 3:
            return SyntheticField(
                q=0.72 * math.sin(elapsed * 0.48),
                p=0.82 * math.cos(elapsed * 0.48),
                activity=0.92,
                tempo=0.34,
                irregularity=0.10,
                idle=0.02,
            )

        if self.mode == 4:
            return SyntheticField(
                q=0.38 * math.sin(elapsed * 0.63),
                p=0.48 * math.cos(elapsed * 0.79),
                activity=0.76,
                tempo=0.58,
                irregularity=0.74,
                idle=0.04,
            )

        decay = math.exp(-0.18 * (elapsed % 35.0))
        return SyntheticField(
            q=0.106 + 0.58 * decay * math.sin(elapsed * 0.92),
            p=0.68 * decay * math.cos(elapsed * 0.92),
            activity=0.58 * decay,
            tempo=0.28,
            irregularity=0.12 * decay,
            idle=1.0 - decay,
        )

    def make_frame(self, elapsed: float, field: SyntheticField) -> Image.Image:
        x = self.x
        y = self.y
        r = self.r
        theta = self.theta

        # Optical cavity.
        aperture = np.clip(1.0 - np.power(r, 8.0), 0.0, 1.0)
        depth = np.clip(1.0 - r, 0.0, 1.0)

        cavity = 0.018 + 0.030 * np.power(depth, 0.65)

        flow_angle = math.atan2(field.p, field.q + 1e-9)
        along = x * math.cos(flow_angle) + y * math.sin(flow_angle)
        across = -x * math.sin(flow_angle) + y * math.cos(flow_angle)

        # One asymmetric fold.
        bend = (
            0.13 * np.sin(2.1 * along + elapsed * 0.18)
            + 0.055 * field.q
            + 0.035 * np.sin(elapsed * 0.27)
        )

        centreline = across - bend

        width = (
            0.080
            + 0.030 * field.activity
            + 0.018 * np.sin(elapsed * 0.32)
        )

        body = np.exp(-(centreline * centreline) / max(width, 0.025))
        body *= np.exp(-0.95 * along * along)

        # Typing compresses and softly corrugates the body.
        if self.mode == 2:
            compression = 1.0 + 0.16 * np.sin(
                4.0 * along - elapsed * (1.0 + field.tempo)
            )
            body *= np.clip(compression, 0.72, 1.28)

        # Mouse movement curves and rotates the same body.
        if self.mode == 3:
            tail = np.exp(
                -(
                    (across - bend - 0.06 * np.sin(3.0 * along)) ** 2
                )
                / 0.030
            )
            tail *= np.exp(-1.5 * (along + 0.10) ** 2)
            body = np.maximum(body, 0.72 * tail)

        # Fragmented activity reluctantly separates one small companion mass.
        if self.mode == 4:
            orbit = elapsed * 0.24
            separation = 0.26 + 0.04 * np.sin(elapsed * 0.35)

            blob_x = separation * math.cos(orbit)
            blob_y = separation * math.sin(orbit)

            companion = np.exp(
                -(
                    ((x - blob_x) ** 2) / 0.055
                    + ((y - blob_y) ** 2) / 0.038
                )
            )

            neck = np.exp(
                -(
                    (y - 0.12 * np.sin(2.0 * x + elapsed * 0.25)) ** 2
                )
                / 0.030
            )
            neck *= np.exp(-3.0 * x * x)

            body = np.maximum(body * 0.88, 0.48 * neck)
            body = np.maximum(body, 0.82 * companion)

        body = np.tanh(body * 2.1)
        body *= aperture

        # Dense graphite/hematite material.
        material_depth = body * (0.65 + 0.35 * depth)

        dark = cavity - 0.010 * material_depth
        metallic = (
            0.10 * material_depth
            + 0.17 * np.power(material_depth, 2.2)
        )

        # Narrow highlights only where the imagined light catches the body.
        body_gradient = np.gradient(material_depth)
        normal_hint = np.sqrt(
            body_gradient[0] * body_gradient[0]
            + body_gradient[1] * body_gradient[1]
        )
        normal_hint = np.clip(normal_hint * 2.4, 0.0, 1.0)

        light = np.clip(
            0.58 - 0.46 * x - 0.36 * y,
            0.0,
            1.0,
        )

        specular = normal_hint * light * material_depth

        red = dark + metallic * 0.66 + specular * 0.24
        green = dark + metallic * 0.72 + specular * 0.27
        blue = dark + metallic * 0.76 + specular * 0.31

        # Concave sapphire reflections.
        rim = np.exp(-((r - 0.972) ** 2) / 0.00075)
        inner_rim = np.exp(-((r - 0.895) ** 2) / 0.0035)

        rim_light = rim * np.clip(
            0.50 - 0.35 * x - 0.55 * y,
            0.0,
            1.0,
        )

        ar_shift = 0.5 + 0.5 * np.cos(theta - 0.55)

        red += 0.12 * rim_light + 0.018 * inner_rim
        green += 0.08 * rim_light + 0.030 * inner_rim * ar_shift
        blue += 0.16 * rim_light + 0.045 * inner_rim * ar_shift

        # One restrained overhead reflection.
        reflection = np.exp(
            -(
                ((x + 0.32) / 0.34) ** 2
                + ((y + 0.40) / 0.12) ** 2
            )
        )
        reflection *= aperture

        red += 0.025 * reflection
        green += 0.027 * reflection
        blue += 0.032 * reflection

        # Dark surround and restrained brass-toned housing line.
        outside = 0.006 + 0.004 * np.clip(1.10 - r, 0.0, 1.0)

        red = np.where(self.inside, red, outside)
        green = np.where(self.inside, green, outside)
        blue = np.where(self.inside, blue, outside)

        housing = np.exp(-((r - 1.025) ** 2) / 0.00035)

        red += 0.24 * housing
        green += 0.16 * housing
        blue += 0.075 * housing

        rgb = np.stack([red, green, blue], axis=-1)
        rgb = np.clip(rgb, 0.0, 1.0)
        rgb = np.power(rgb, 0.78)

        return Image.fromarray(
            np.uint8(rgb * 255.0),
            mode="RGB",
        )

    def update(self) -> None:
        now = time.perf_counter()
        elapsed = now - self.started

        if self.auto and now - self.last_mode_change >= 10.0:
            self.mode = 1 + (self.mode % 5)
            self.last_mode_change = now

        field = self.field(elapsed)
        image = self.make_frame(elapsed, field)

        self.photo = ImageTk.PhotoImage(image)
        self.canvas.itemconfigure(self.image_id, image=self.photo)
        self.canvas.tag_raise(self.status_id)
        self.canvas.tag_raise(self.help_id)

        self.canvas.itemconfigure(
            self.status_id,
            text=(
                f"{self.NAMES[self.mode]}   "
                f"q {field.q:+.2f}   "
                f"p {field.p:+.2f}   "
                f"activity {field.activity:.2f}   "
                f"auto {'ON' if self.auto else 'OFF'}"
            ),
        )

        self.root.after(max(1, int(1000 / FPS)), self.update)


def main() -> None:
    root = tk.Tk()
    LiquidLensV02(root)
    root.mainloop()


if __name__ == "__main__":
    main()
