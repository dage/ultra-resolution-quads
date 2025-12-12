import math
from typing import Literal

import numpy as np
from PIL import Image


def _cos_palette(t: np.ndarray) -> np.ndarray:
    """
    Deterministic smooth palette in [0,1] -> RGB in [0,1].
    """
    t = np.clip(t, 0.0, 1.0).astype(np.float32)
    two_pi = np.float32(2.0 * math.pi)
    r = 0.5 + 0.5 * np.cos(two_pi * (t + 0.00))
    g = 0.5 + 0.5 * np.cos(two_pi * (t + 0.33))
    b = 0.5 + 0.5 * np.cos(two_pi * (t + 0.67))
    return np.stack([r, g, b], axis=-1)


def _turbo_palette(t: np.ndarray) -> np.ndarray:
    """
    Turbo colormap approximation (returns RGB in [0,1]).
    Source: polynomial approximation popularized by Google's Turbo.
    """
    t = np.clip(t, 0.0, 1.0).astype(np.float32)
    # Coefficients for r,g,b polynomials (degree 5)
    r = (
        0.13572138
        + t * (4.61539260 + t * (-42.66032258 + t * (132.13108234 + t * (-152.94239396 + t * 59.28637943))))
    )
    g = (
        0.09140261
        + t * (2.19418839 + t * (4.84296658 + t * (-14.18503333 + t * (4.27729857 + t * 2.82956604))))
    )
    b = (
        0.10667330
        + t * (12.64194608 + t * (-60.58204836 + t * (110.36276771 + t * (-89.90310912 + t * 27.34824973))))
    )
    return np.stack([np.clip(r, 0.0, 1.0), np.clip(g, 0.0, 1.0), np.clip(b, 0.0, 1.0)], axis=-1)


def _mono_glow(
    t_escape: np.ndarray,
    trap: np.ndarray,
    active: np.ndarray,
    max_iter: int,
) -> np.ndarray:
    """
    Monochrome "fog + glow" look:
    - smooth gray interior using orbit trap
    - bright white boundary glow for points that escape late
    """
    # Interior shading from orbit-trap metric: smooth gray "fog" volumes.
    trap_safe = np.clip(trap.astype(np.float32), 0.0, 10.0)
    trap_n = np.log1p(trap_safe) / np.log1p(np.float32(10.0))
    # Darker fog: push mid-grays closer to black while preserving gradient.
    interior = 0.06 + 0.54 * trap_n

    t = np.clip(t_escape, 0.0, 1.0).astype(np.float32)
    # Escaped points: dark background with brightening near the boundary.
    esc_base = 0.03 + 0.26 * (t ** 0.95)
    # Boundary glow: broader, bright rim for t ~ 1.
    sigma = np.float32(0.12)
    glow_iter = np.exp(-((1.0 - t) / sigma) ** 2).astype(np.float32)
    # Sparkles: emphasize near-origin orbit visits (small trap) to mimic "white points".
    glow_trap = np.exp(-8.0 * trap_safe).astype(np.float32)
    glow = np.clip(glow_iter + 0.85 * glow_trap, 0.0, 1.5)
    esc = np.clip(esc_base + 1.55 * glow, 0.0, 1.0)

    luma = np.where(active, interior, esc).astype(np.float32)
    # Contrast curve to match the "dark fog + white sparks" aesthetic.
    # >1.0 darkens mids; keep highlights via glow.
    luma = np.clip(luma, 0.0, 1.0) ** np.float32(1.25)
    rgb = np.stack([luma, luma, luma], axis=-1)
    return rgb

class HybridOrbitSwitchRenderer:
    """
    Tile renderer for the hybrid_orbit_switch fractal from the gallery.

    Key goal: level 0 should approximately match downsample(level 1 composite),
    and the 4 L1 tiles should stitch seamlessly (no seams).
    """

    def __init__(
        self,
        tile_size: int = 1024,
        supersampling: int = 2,
        seq: str = "ABBABAAAAA",
        mapA: Literal["sin", "square", "tanh", "recip", "absfold"] = "sin",
        mapB: Literal["exp", "cube", "conj", "sinh", "log"] = "sinh",
        lamA: float = 1.4851075592198706,
        lamB: float = -1.6116093590081693,
        c_re: float = 0.11859028322078968,
        c_im: float = -0.10515024499795689,
        center_re: float = -0.4949049355354143,
        center_im: float = 0.3710307451429604,
        scale: float = 0.6274177092915492,
        max_iter: int = 188,
        bailout: float = 5.815555913477939,
    ):
        self.tile_size = int(tile_size)
        self.supersampling = int(supersampling)
        self.seq = str(seq)
        self.mapA = mapA
        self.mapB = mapB
        self.lamA = float(lamA)
        self.lamB = float(lamB)
        self.c = np.complex64(complex(float(c_re), float(c_im)))
        self.center = np.complex64(complex(float(center_re), float(center_im)))
        self.scale = float(scale)
        self.max_iter = int(max_iter)
        self.bailout = float(bailout)

        if self.supersampling not in (1, 2, 3, 4):
            raise ValueError("supersampling must be 1..4")
        if not self.seq or any(ch not in "AB" for ch in self.seq):
            raise ValueError("seq must be non-empty and only contain A/B")

    def supports_multithreading(self) -> bool:
        return True

    def _f_choice(self, name: str, z: np.ndarray, lam: float) -> np.ndarray:
        if name == "sin":
            return lam * np.sin(z)
        if name == "square":
            return lam * z * z
        if name == "tanh":
            return lam * np.tanh(z)
        if name == "recip":
            return lam / (z + np.complex64(1e-6))
        if name == "absfold":
            return (np.abs(z.real) + 1j * np.abs(z.imag)).astype(np.complex64) * lam
        if name == "exp":
            return lam * np.exp(z)
        if name == "cube":
            return lam * z * z * z
        if name == "conj":
            return lam * np.conj(z)
        if name == "sinh":
            return lam * np.sinh(z)
        if name == "log":
            return (lam * np.log(np.abs(z) + 1e-6) + 1j * np.angle(z)).astype(np.complex64)
        return z

    def _render_samples(self, level: int, tile_x: int, tile_y: int, ss: int) -> np.ndarray:
        """
        Returns RGB samples at resolution (tile_size*ss, tile_size*ss, 3) in [0,1].
        """
        out_w = self.tile_size * ss
        out_h = self.tile_size * ss
        tiles_per_axis = 2**int(level)
        full_px = self.tile_size * tiles_per_axis

        # Subpixel centers within each output pixel correspond to (sx+0.5)/ss in [0,1)
        # but we render directly at ssx scale, so each output pixel corresponds to a subpixel.
        # Map each output pixel center to global coordinates in the full view.
        gx0 = tile_x * self.tile_size
        gy0 = tile_y * self.tile_size

        xs = (gx0 + (np.arange(out_w, dtype=np.float64) + 0.5) / ss) / full_px
        ys = (gy0 + (np.arange(out_h, dtype=np.float64) + 0.5) / ss) / full_px

        xv, yv = np.meshgrid(xs, ys)
        # Match experiments.fractal_gallery_integrator complex_grid orientation:
        # row 0 corresponds to y=-1.
        u = (xv * 2.0 - 1.0).astype(np.float32)
        v = (yv * 2.0 - 1.0).astype(np.float32)
        z = (self.center + (u + 1j * v).astype(np.complex64) * np.float32(self.scale)).astype(
            np.complex64
        )

        active = np.ones(z.shape, dtype=bool)
        smooth = np.full(z.shape, float(self.max_iter), dtype=np.float32)
        # Orbit-trap style interior shading: track how close orbit gets to origin.
        trap = np.full(z.shape, 1e9, dtype=np.float32)
        bailout_sq = np.float32(self.bailout * self.bailout)
        log_bailout = math.log(self.bailout)
        seq = self.seq
        seq_len = len(seq)

        for i in range(self.max_iter):
            if not active.any():
                break
            ch = seq[i % seq_len]
            if ch == "A":
                z[active] = self._f_choice(self.mapA, z[active], self.lamA) + self.c
            else:
                z[active] = self._f_choice(self.mapB, z[active], self.lamB) + self.c

            # Update trap for points still active
            if active.any():
                zr = z.real.astype(np.float32)
                zi = z.imag.astype(np.float32)
                mag = np.sqrt(zr * zr + zi * zi)
                axis = np.minimum(np.abs(zr), np.abs(zi))
                trap_metric = 0.45 * mag + 0.55 * axis
                trap = np.minimum(trap, trap_metric)

            mag_sq = (z.real * z.real + z.imag * z.imag).astype(np.float32)
            escaped = mag_sq > bailout_sq
            newly = escaped & active
            if newly.any():
                mag = np.sqrt(mag_sq[newly]).astype(np.float32)
                # Generalized smooth coloring using magnitude; works across transcendental maps.
                smooth[newly] = np.float32(i + 1) - np.float32(
                    math.log(2.0)
                ) * np.log(np.log(mag + 1e-9) / log_bailout + 1e-9).astype(np.float32)
            active &= ~escaped

        t_escape = np.clip(smooth / float(self.max_iter), 0.0, 1.0).astype(np.float32)
        rgb = _mono_glow(t_escape=t_escape, trap=trap, active=active, max_iter=self.max_iter)
        return rgb

    @staticmethod
    def _quantize_u8(rgb_01: np.ndarray) -> np.ndarray:
        return (np.clip(rgb_01, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)

    @staticmethod
    def _downsample2_u8(img_u8: np.ndarray) -> np.ndarray:
        """
        Exact 2x BOX downsample with integer rounding to nearest.
        Input: HxWxC uint8 with even H,W. Output: (H/2)x(W/2)xC uint8.
        """
        a = img_u8.astype(np.uint16)
        s = a[0::2, 0::2] + a[1::2, 0::2] + a[0::2, 1::2] + a[1::2, 1::2]
        return ((s + 2) // 4).astype(np.uint8)

    def render(self, level: int, x: int, y: int) -> Image.Image:
        level = int(level)
        x = int(x)
        y = int(y)

        # Goal: L0 should match "compose 4x L1 then 2x BOX downsample".
        # L1 tiles are rendered with supersampling=self.supersampling (2x2 requested).
        # To reproduce the *same quantization path* at L0, we do a two-stage downsample:
        # (1) render at 4x4 sample grid (ss*2), average 2x2 -> quantize (simulates L1 pixelization),
        # (2) average 2x2 in uint8 space -> quantize (simulates the BOX downsample of the L1 composite).
        if level == 0 and self.supersampling == 2:
            rgb_ss4 = self._render_samples(level, x, y, ss=4)
            # Stage 1: average 2x2 to (2*tile)x(2*tile) float, then quantize.
            mid = rgb_ss4.reshape(self.tile_size * 2, 2, self.tile_size * 2, 2, 3).mean(axis=(1, 3))
            mid_u8 = self._quantize_u8(mid)
            # Stage 2: exact 2x BOX downsample in uint8 space with rounding.
            out_u8 = self._downsample2_u8(mid_u8)
            return Image.fromarray(out_u8, mode="RGB")

        ss = self.supersampling
        rgb_samples = self._render_samples(level, x, y, ss=ss)
        if ss > 1:
            rgb = rgb_samples.reshape(self.tile_size, ss, self.tile_size, ss, 3).mean(axis=(1, 3))
        else:
            rgb = rgb_samples
        return Image.fromarray(self._quantize_u8(rgb), mode="RGB")
