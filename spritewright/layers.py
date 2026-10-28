"""Layers: named canvases with visibility, opacity and normal/multiply blending."""
from __future__ import annotations

import numpy as np

from .canvas import Canvas
from .errors import PixelError
from .palette import TRANSPARENT, Palette


class Layer:
    def __init__(self, name, canvas, visible=True, opacity=1.0, blend="normal"):
        if blend not in ("normal", "multiply"):
            raise PixelError(f"layer {name!r}: blend must be 'normal' or 'multiply', got {blend!r}")
        if not 0.0 <= opacity <= 1.0:
            raise PixelError(f"layer {name!r}: opacity must be 0..1, got {opacity}")
        self.name, self.canvas, self.visible, self.opacity, self.blend = name, canvas, visible, opacity, blend

    def __repr__(self):
        return f"Layer({self.name!r}, visible={self.visible}, opacity={self.opacity}, blend={self.blend!r})"


class LayerStack:
    """Bottom-to-top list of layers. stack.add('body') returns the layer's Canvas."""

    def __init__(self, w, h, palette, strict=True):
        self.w, self.h = w, h
        self.palette = Palette.load(palette)
        self.strict = strict
        self.layers: list[Layer] = []

    def add(self, name, canvas=None, visible=True, opacity=1.0, blend="normal", index=None) -> Canvas:
        if any(l.name == name for l in self.layers):
            raise PixelError(f"layer {name!r} already exists")
        cv = canvas if canvas is not None else Canvas(self.w, self.h, self.palette, strict=self.strict, name=name)
        if cv.size != (self.w, self.h):
            raise PixelError(f"layer {name!r} is {cv.w}x{cv.h}, stack is {self.w}x{self.h}")
        lay = Layer(name, cv, visible, opacity, blend)
        self.layers.insert(len(self.layers) if index is None else index, lay)
        return cv

    def layer(self, name) -> Layer:
        for l in self.layers:
            if l.name == name:
                return l
        raise PixelError(f"no layer {name!r}; layers: {', '.join(l.name for l in self.layers)}")

    def __getitem__(self, name) -> Canvas:
        return self.layer(name).canvas

    def remove(self, name):
        self.layers.remove(self.layer(name))

    def move(self, name, index):
        l = self.layer(name)
        self.layers.remove(l)
        self.layers.insert(index, l)

    def flatten(self) -> Canvas:
        """Composite visible layers. Pure normal/opaque stacks stay exact; opacity or multiply
        are composited in RGB and snapped back to the nearest palette color."""
        out = Canvas(self.w, self.h, self.palette, strict=self.strict)
        vis = [l for l in self.layers if l.visible and l.opacity > 0]
        if all(l.opacity == 1.0 and l.blend == "normal" for l in vis):
            for l in vis:
                out.stamp(l.canvas, 0, 0)
            return out
        rgb = np.zeros((self.h, self.w, 3))
        a = np.zeros((self.h, self.w))
        for l in vis:
            src = l.canvas.to_rgba().astype(np.float64)
            sa = (l.canvas.data >= 0) * l.opacity
            srgb = src[..., :3]
            if l.blend == "multiply":
                srgb = np.where(a[..., None] > 0, rgb * srgb / 255.0, srgb)
            na = sa + a * (1 - sa)
            with np.errstate(invalid="ignore", divide="ignore"):
                rgb = np.where(na[..., None] > 0,
                               (srgb * sa[..., None] + rgb * (a * (1 - sa))[..., None]) / na[..., None], 0)
            a = na
        idx = self.palette.nearest_many(rgb)
        out.data[:] = np.where(a >= 0.5, idx, TRANSPARENT)
        return out
