"""
Novel fractal discovery gallery.

Generates a wide range of non‑canonical fractals inspired by:
- Transcendental viscosity mappings
- Hybrid / switched dynamical systems
- Coupled Map Lattices (spatiotemporal chaos)
- Hypercomplex (quaternion) iteration slices
- Lyapunov hybrid stability fields

Optionally uses backend/tools/analyze_image.py as a VLM critic to score novelty and
describe each candidate. Outputs:

- artifacts/novel_fractal_gallery/images/*.png
- artifacts/novel_fractal_gallery/summary.json
- artifacts/novel_fractal_gallery/report.html
"""

import argparse
import asyncio
import json
import math
import os
import random
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

try:
    from backend.tools.analyze_image import analyze_images  # type: ignore
except Exception:
    analyze_images = None  # type: ignore

OUTPUT_ROOT = os.path.join("artifacts", "novel_fractal_gallery")
IMAGES_DIR = os.path.join(OUTPUT_ROOT, "images")
SUMMARY_PATH = os.path.join(OUTPUT_ROOT, "summary.json")
REPORT_PATH = os.path.join(OUTPUT_ROOT, "report.html")

DEFAULT_MODEL = "qwen/qwen3-vl-8b-instruct"


def ensure_dirs() -> None:
    os.makedirs(IMAGES_DIR, exist_ok=True)


def complex_grid(size: int, center: complex, scale: float) -> np.ndarray:
    lin = np.linspace(-1.0, 1.0, size, dtype=np.float64)
    x, y = np.meshgrid(lin, lin)
    return center + (x + 1j * y) * scale


def smooth_escape_iters(
    z0: np.ndarray,
    c: np.ndarray,
    map_fn: Callable[[np.ndarray, np.ndarray, Dict[str, Any]], np.ndarray],
    params: Dict[str, Any],
    max_iter: int,
    bailout: float,
) -> np.ndarray:
    z = z0.copy()
    iters = np.zeros(z.shape, dtype=np.float32)
    mask = np.ones(z.shape, dtype=bool)
    bailout_sq = bailout * bailout
    for i in range(max_iter):
        if not mask.any():
            break
        z[mask] = map_fn(z[mask], c[mask], params)
        mag_sq = (z.real * z.real + z.imag * z.imag)
        escaped = mag_sq > bailout_sq
        newly = escaped & mask
        if newly.any():
            iters[newly] = i + 1 - np.log2(
                np.log(np.sqrt(mag_sq[newly]) + 1e-9) / math.log(bailout)
            )
        mask &= ~escaped
    iters[mask] = max_iter
    return iters


def normalize_to_uint8(field: np.ndarray, clip: Tuple[float, float] = (1.0, 99.0)) -> np.ndarray:
    finite = np.isfinite(field)
    if not finite.any():
        field = np.zeros_like(field, dtype=np.float32)
        finite = np.ones_like(field, dtype=bool)
    else:
        fmin = float(np.min(field[finite]))
        fmax = float(np.max(field[finite]))
        field = np.nan_to_num(field, nan=fmin, posinf=fmax, neginf=fmin)
    lo, hi = np.percentile(field, clip)
    if hi <= lo:
        hi = lo + 1e-6
    norm = (field - lo) / (hi - lo)
    norm = np.clip(norm, 0.0, 1.0)
    return (norm * 255.0).astype(np.uint8)


def apply_palette(gray: np.ndarray, palette: str, rng: random.Random) -> np.ndarray:
    g = gray.astype(np.float32) / 255.0
    if palette == "hsv":
        hue_shift = rng.random()
        sat = 0.85 + 0.15 * rng.random()
        val = 0.6 + 0.4 * g
        h = (g * 0.9 + hue_shift) % 1.0
        c = val * sat
        x = c * (1 - np.abs((h * 6) % 2 - 1))
        m = val - c
        r = np.zeros_like(g)
        b = np.zeros_like(g)
        gr = np.zeros_like(g)
        idx = (h * 6).astype(int)
        for k in range(6):
            mask = idx == k
            if k == 0:
                r[mask], gr[mask], b[mask] = c[mask], x[mask], 0
            elif k == 1:
                r[mask], gr[mask], b[mask] = x[mask], c[mask], 0
            elif k == 2:
                r[mask], gr[mask], b[mask] = 0, c[mask], x[mask]
            elif k == 3:
                r[mask], gr[mask], b[mask] = 0, x[mask], c[mask]
            elif k == 4:
                r[mask], gr[mask], b[mask] = x[mask], 0, c[mask]
            else:
                r[mask], gr[mask], b[mask] = c[mask], 0, x[mask]
        rgb = np.stack([(r + m), (gr + m), (b + m)], axis=-1)
        return (np.clip(rgb, 0, 1) * 255).astype(np.uint8)
    if palette == "duotone":
        c1 = np.array([rng.random(), rng.random(), rng.random()])
        c2 = np.array([rng.random(), rng.random(), rng.random()])
        rgb = c1[None, None, :] * (1 - g[..., None]) + c2[None, None, :] * g[..., None]
        return (np.clip(rgb, 0, 1) * 255).astype(np.uint8)
    return np.stack([gray, gray, gray], axis=-1)


def save_image(rgb: np.ndarray, path: str) -> None:
    Image.fromarray(rgb, mode="RGB").save(path, optimize=True)


def shannon_entropy(gray_u8: np.ndarray) -> float:
    hist, _ = np.histogram(gray_u8, bins=256, range=(0, 255), density=True)
    hist = hist[hist > 0]
    return float(-np.sum(hist * np.log2(hist)))


def edge_density(gray_u8: np.ndarray) -> float:
    g = gray_u8.astype(np.float32) / 255.0
    gx = np.zeros_like(g)
    gy = np.zeros_like(g)
    gx[:, 1:-1] = g[:, 2:] - g[:, :-2]
    gy[1:-1, :] = g[2:, :] - g[:-2, :]
    mag = np.sqrt(gx * gx + gy * gy)
    return float(np.mean(mag))


def compression_ratio(rgb_u8: np.ndarray) -> float:
    raw_bytes = rgb_u8.size
    tmp = Image.fromarray(rgb_u8, mode="RGB")
    from io import BytesIO

    bio = BytesIO()
    tmp.save(bio, format="PNG", optimize=True)
    png_bytes = len(bio.getvalue())
    return float(png_bytes / raw_bytes)


# -------------------- Fractal families --------------------

# Each family provides: sample_params(rng), render(size, params), mutate(rng, params, feedback).

def map_transcendental(z: np.ndarray, c: np.ndarray, p: Dict[str, Any]) -> np.ndarray:
    t = p["type"]
    lam = p["lam"]
    alpha = p["alpha"]
    if t == "sine_viscosity":
        nxt = np.sin(z) + c
    elif t == "tanh_exp":
        nxt = np.tanh(z) + lam * np.exp(-z) + c
    elif t == "logistic_complex":
        nxt = lam * z * (1 - z) + c
    elif t == "cosh_fold":
        nxt = np.cosh(z) + lam * np.sin(z * z) + c
    elif t == "abs_conj":
        nxt = (np.abs(z.real) + 1j * np.abs(z.imag)) ** 2 + lam * np.conj(z) + c
    else:
        nxt = z * z + c
    return (1 - alpha) * z + alpha * nxt


def sample_transcendental(rng: random.Random) -> Dict[str, Any]:
    return {
        "type": rng.choice(
            ["sine_viscosity", "tanh_exp", "logistic_complex", "cosh_fold", "abs_conj"]
        ),
        "alpha": rng.uniform(0.1, 0.95),
        "lam": rng.uniform(-3.0, 3.0),
        "center": [rng.uniform(-0.7, 0.7), rng.uniform(-0.7, 0.7)],
        "scale": rng.uniform(0.4, 3.0),
        "c": [rng.uniform(-1.2, 1.2), rng.uniform(-1.2, 1.2)],
        "max_iter": rng.randint(120, 260),
        "bailout": rng.uniform(4.0, 10.0),
    }


def render_transcendental(size: int, params: Dict[str, Any]) -> np.ndarray:
    center = complex(*params["center"])
    scale = float(params["scale"])
    c_const = complex(*params["c"])
    z0 = complex_grid(size, center, scale)
    c = np.full_like(z0, c_const)
    field = smooth_escape_iters(
        z0,
        c,
        map_transcendental,
        params,
        max_iter=int(params["max_iter"]),
        bailout=float(params["bailout"]),
    )
    return field


def mutate_transcendental(rng: random.Random, params: Dict[str, Any], fb: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(params)
    excitement = (fb.get("excitement_score") or 0) if isinstance(fb, dict) else 0
    step = 0.25 if excitement < 6 else 0.1
    if rng.random() < 0.35:
        p["type"] = rng.choice(
            ["sine_viscosity", "tanh_exp", "logistic_complex", "cosh_fold", "abs_conj"]
        )
    p["alpha"] = float(np.clip(p["alpha"] + rng.uniform(-step, step), 0.05, 0.98))
    p["lam"] = float(np.clip(p["lam"] * rng.uniform(0.7, 1.4), -4.0, 4.0))
    p["scale"] = float(np.clip(p["scale"] * rng.uniform(0.6, 1.5), 0.25, 4.0))
    p["center"] = [
        float(np.clip(p["center"][0] + rng.uniform(-0.2, 0.2) * p["scale"], -2.0, 2.0)),
        float(np.clip(p["center"][1] + rng.uniform(-0.2, 0.2) * p["scale"], -2.0, 2.0)),
    ]
    p["c"] = [
        float(np.clip(p["c"][0] + rng.uniform(-0.4, 0.4), -2.0, 2.0)),
        float(np.clip(p["c"][1] + rng.uniform(-0.4, 0.4), -2.0, 2.0)),
    ]
    p["max_iter"] = int(np.clip(p["max_iter"] + rng.randint(-40, 60), 80, 420))
    p["bailout"] = float(np.clip(p["bailout"] * rng.uniform(0.8, 1.3), 3.0, 12.0))
    return p


def sample_hybrid_orbit(rng: random.Random) -> Dict[str, Any]:
    seq_len = rng.randint(5, 14)
    return {
        "seq": "".join(rng.choice("AB") for _ in range(seq_len)),
        "mapA": rng.choice(["sin", "square", "tanh", "recip", "absfold"]),
        "mapB": rng.choice(["exp", "cube", "conj", "sinh", "log"]),
        "lamA": rng.uniform(-2.5, 2.5),
        "lamB": rng.uniform(-2.5, 2.5),
        "c": [rng.uniform(-1.0, 1.0), rng.uniform(-1.0, 1.0)],
        "center": [rng.uniform(-0.8, 0.8), rng.uniform(-0.8, 0.8)],
        "scale": rng.uniform(0.3, 2.8),
        "max_iter": rng.randint(90, 220),
        "bailout": rng.uniform(5.0, 12.0),
    }


def render_hybrid_orbit(size: int, params: Dict[str, Any]) -> np.ndarray:
    seq = params["seq"]
    seq_len = len(seq)
    a = params["mapA"]
    b = params["mapB"]
    lam_a = float(params["lamA"])
    lam_b = float(params["lamB"])
    c_const = complex(*params["c"])
    center = complex(*params["center"])
    scale = float(params["scale"])

    def f_choice(name: str, z: np.ndarray, lam: float) -> np.ndarray:
        if name == "sin":
            return lam * np.sin(z)
        if name == "square":
            return lam * z * z
        if name == "tanh":
            return lam * np.tanh(z)
        if name == "recip":
            return lam / (z + 1e-6)
        if name == "absfold":
            return (np.abs(z.real) + 1j * np.abs(z.imag)) * lam
        if name == "exp":
            return lam * np.exp(z)
        if name == "cube":
            return lam * z * z * z
        if name == "conj":
            return lam * np.conj(z)
        if name == "sinh":
            return lam * np.sinh(z)
        if name == "log":
            return lam * np.log(np.abs(z) + 1e-6) + 1j * np.angle(z)
        return z

    def map_fn(z: np.ndarray, c: np.ndarray, p: Dict[str, Any]) -> np.ndarray:
        k = p["k"]
        ch = seq[k % seq_len]
        p["k"] = k + 1
        if ch == "A":
            return f_choice(a, z, lam_a) + c
        return f_choice(b, z, lam_b) + c

    z0 = complex_grid(size, center, scale)
    c = np.full_like(z0, c_const)
    field = smooth_escape_iters(
        z0,
        c,
        map_fn,
        {"k": 0},
        max_iter=int(params["max_iter"]),
        bailout=float(params["bailout"]),
    )
    return field


def mutate_hybrid_orbit(rng: random.Random, params: Dict[str, Any], fb: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(params)
    if rng.random() < 0.4:
        seq = list(p["seq"])
        idx = rng.randrange(len(seq))
        seq[idx] = "A" if seq[idx] == "B" else "B"
        if rng.random() < 0.2:
            seq.insert(idx, rng.choice("AB"))
        if len(seq) > 16 and rng.random() < 0.2:
            seq.pop(rng.randrange(len(seq)))
        p["seq"] = "".join(seq)
    if rng.random() < 0.25:
        p["mapA"] = rng.choice(["sin", "square", "tanh", "recip", "absfold"])
    if rng.random() < 0.25:
        p["mapB"] = rng.choice(["exp", "cube", "conj", "sinh", "log"])
    p["lamA"] = float(np.clip(p["lamA"] * rng.uniform(0.6, 1.6), -4.0, 4.0))
    p["lamB"] = float(np.clip(p["lamB"] * rng.uniform(0.6, 1.6), -4.0, 4.0))
    p["scale"] = float(np.clip(p["scale"] * rng.uniform(0.6, 1.7), 0.2, 4.0))
    p["center"] = [
        float(np.clip(p["center"][0] + rng.uniform(-0.25, 0.25) * p["scale"], -2.5, 2.5)),
        float(np.clip(p["center"][1] + rng.uniform(-0.25, 0.25) * p["scale"], -2.5, 2.5)),
    ]
    p["c"] = [
        float(np.clip(p["c"][0] + rng.uniform(-0.6, 0.6), -2.5, 2.5)),
        float(np.clip(p["c"][1] + rng.uniform(-0.6, 0.6), -2.5, 2.5)),
    ]
    p["max_iter"] = int(np.clip(p["max_iter"] + rng.randint(-20, 50), 60, 360))
    p["bailout"] = float(np.clip(p["bailout"] * rng.uniform(0.8, 1.5), 3.0, 14.0))
    return p


def quat_mul(q: np.ndarray, r: np.ndarray) -> np.ndarray:
    w1, x1, y1, z1 = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    w2, x2, y2, z2 = r[..., 0], r[..., 1], r[..., 2], r[..., 3]
    w = w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2
    x = w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2
    y = w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2
    z = w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2
    return np.stack([w, x, y, z], axis=-1)


def sample_quaternion_slice(rng: random.Random) -> Dict[str, Any]:
    normal = np.array([rng.uniform(-1, 1) for _ in range(4)], dtype=np.float64)
    normal /= np.linalg.norm(normal) + 1e-9
    return {
        "center": [rng.uniform(-0.5, 0.5), rng.uniform(-0.5, 0.5)],
        "scale": rng.uniform(0.5, 2.5),
        "normal": normal.tolist(),
        "c": [rng.uniform(-0.9, 0.9) for _ in range(4)],
        "bailout": rng.uniform(3.5, 12.0),
        "max_iter": rng.randint(80, 180),
    }


def render_quaternion_slice(size: int, params: Dict[str, Any]) -> np.ndarray:
    center = params["center"]
    scale = float(params["scale"])
    lin = np.linspace(-1.0, 1.0, size, dtype=np.float64)
    xg, yg = np.meshgrid(lin, lin)
    xg = center[0] + xg * scale
    yg = center[1] + yg * scale

    normal = np.array(params["normal"], dtype=np.float64)
    normal /= np.linalg.norm(normal) + 1e-9
    axis_u = np.roll(normal, 1)
    axis_u -= normal * np.dot(axis_u, normal)
    axis_u /= np.linalg.norm(axis_u) + 1e-9
    axis_v = np.roll(normal, 2)
    axis_v -= normal * np.dot(axis_v, normal)
    axis_v -= axis_u * np.dot(axis_v, axis_u)
    axis_v /= np.linalg.norm(axis_v) + 1e-9

    q = xg[..., None] * axis_u[None, None, :] + yg[..., None] * axis_v[None, None, :]
    c_vec = np.array(params["c"], dtype=np.float64)
    c = c_vec[None, None, :]
    bailout = float(params["bailout"])
    max_iter = int(params["max_iter"])
    field = np.zeros((size, size), dtype=np.float32)
    mask = np.ones((size, size), dtype=bool)
    for i in range(max_iter):
        if not mask.any():
            break
        qq = q[mask]
        q[mask] = quat_mul(qq, qq) + c
        norm_sq = np.sum(q[..., :4] ** 2, axis=-1)
        esc = norm_sq > bailout * bailout
        newly = esc & mask
        field[newly] = i + 1
        mask &= ~esc
    field[mask] = max_iter
    return field


def mutate_quaternion_slice(rng: random.Random, params: Dict[str, Any], fb: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(params)
    p["scale"] = float(np.clip(p["scale"] * rng.uniform(0.6, 1.7), 0.3, 4.0))
    p["center"] = [
        float(np.clip(p["center"][0] + rng.uniform(-0.3, 0.3) * p["scale"], -2.0, 2.0)),
        float(np.clip(p["center"][1] + rng.uniform(-0.3, 0.3) * p["scale"], -2.0, 2.0)),
    ]
    n = np.array(p["normal"], dtype=np.float64)
    n = n + rng.uniform(-0.25, 0.25) * np.roll(n, rng.randint(1, 3))
    n /= np.linalg.norm(n) + 1e-9
    p["normal"] = n.tolist()
    p["c"] = [float(np.clip(v + rng.uniform(-0.4, 0.4), -2.0, 2.0)) for v in p["c"]]
    p["max_iter"] = int(np.clip(p["max_iter"] + rng.randint(-10, 30), 60, 260))
    p["bailout"] = float(np.clip(p["bailout"] * rng.uniform(0.8, 1.4), 3.0, 14.0))
    return p


def sample_lyapunov_hybrid(rng: random.Random) -> Dict[str, Any]:
    seq_len = rng.randint(6, 14)
    return {
        "seq": "".join(rng.choice("AB") for _ in range(seq_len)),
        "mapA": rng.choice(["logistic", "sine", "tent"]),
        "mapB": rng.choice(["logistic", "sine", "tent"]),
        "r_range": [2.3 + 0.2 * rng.random(), 4.0],
        "iters": rng.randint(60, 120),
    }


def render_lyapunov_hybrid(size: int, params: Dict[str, Any]) -> np.ndarray:
    seq = params["seq"]
    seq_len = len(seq)
    map_a = params["mapA"]
    map_b = params["mapB"]
    r_min, r_max = params["r_range"]
    steps = int(params["iters"])
    x0 = 0.5

    def f_and_df(kind: str, x: np.ndarray, r: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        if kind == "logistic":
            fx = r * x * (1 - x)
            dfx = np.abs(r * (1 - 2 * x))
            return fx, dfx
        if kind == "sine":
            fx = r * np.sin(math.pi * x)
            dfx = np.abs(r * math.pi * np.cos(math.pi * x))
            return fx, dfx
        fx = np.where(x < 0.5, r * x, r * (1 - x))
        dfx = np.where(x < 0.5, np.abs(r), np.abs(-r))
        return fx, dfx

    lin = np.linspace(r_min, r_max, size, dtype=np.float64)
    ra, rb = np.meshgrid(lin, lin)
    x = np.full_like(ra, x0)
    lyap = np.zeros_like(ra)
    for i in range(steps):
        ch = seq[i % seq_len]
        if ch == "A":
            x, df = f_and_df(map_a, x, ra)
        else:
            x, df = f_and_df(map_b, x, rb)
        x = np.clip(x, 1e-6, 1.0 - 1e-6)
        lyap += np.log(df + 1e-9)
    lyap /= float(steps)
    return -lyap


def mutate_lyapunov_hybrid(rng: random.Random, params: Dict[str, Any], fb: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(params)
    if rng.random() < 0.4:
        seq = list(p["seq"])
        seq[rng.randrange(len(seq))] = rng.choice("AB")
        p["seq"] = "".join(seq)
    if rng.random() < 0.3:
        p["mapA"] = rng.choice(["logistic", "sine", "tent"])
    if rng.random() < 0.3:
        p["mapB"] = rng.choice(["logistic", "sine", "tent"])
    p["iters"] = int(np.clip(p["iters"] + rng.randint(-20, 30), 40, 160))
    r_min, r_max = p["r_range"]
    r_min = float(np.clip(r_min + rng.uniform(-0.1, 0.15), 1.8, 3.6))
    p["r_range"] = [r_min, float(r_max)]
    return p


def sample_cml(rng: random.Random) -> Dict[str, Any]:
    return {
        "steps": rng.randint(60, 160),
        "epsilon": rng.uniform(0.02, 0.45),
        "r": rng.uniform(3.4, 4.2),
        "topology": rng.choice(["von_neumann", "moore", "small_world"]),
        "seed": rng.randint(0, 10_000),
    }


def render_cml(size: int, params: Dict[str, Any]) -> np.ndarray:
    steps = int(params["steps"])
    eps = float(params["epsilon"])
    r_val = float(params["r"])
    topo = params["topology"]
    rs = np.random.RandomState(int(params["seed"]))
    field = rs.rand(size, size).astype(np.float64)
    field = np.clip(field, 0.0, 1.0)

    def local_map(x: np.ndarray) -> np.ndarray:
        return r_val * x * (1 - x)

    for _ in range(steps):
        fx = local_map(field)
        if topo == "von_neumann":
            neigh = (
                np.roll(fx, 1, 0)
                + np.roll(fx, -1, 0)
                + np.roll(fx, 1, 1)
                + np.roll(fx, -1, 1)
            ) / 4.0
        elif topo == "moore":
            neigh = (
                np.roll(fx, 1, 0)
                + np.roll(fx, -1, 0)
                + np.roll(fx, 1, 1)
                + np.roll(fx, -1, 1)
                + np.roll(np.roll(fx, 1, 0), 1, 1)
                + np.roll(np.roll(fx, 1, 0), -1, 1)
                + np.roll(np.roll(fx, -1, 0), 1, 1)
                + np.roll(np.roll(fx, -1, 0), -1, 1)
            ) / 8.0
        else:
            neigh = (
                np.roll(fx, 1, 0)
                + np.roll(fx, -1, 0)
                + np.roll(fx, 1, 1)
                + np.roll(fx, -1, 1)
            ) / 4.0
            if rs.rand() < 0.25:
                neigh = 0.7 * neigh + 0.3 * np.roll(neigh, rs.randint(-10, 10), rs.randint(0, 2))
        field = (1 - eps) * fx + eps * neigh
        field = np.clip(field, 0.0, 1.0)

    return field.astype(np.float32)


def mutate_cml(rng: random.Random, params: Dict[str, Any], fb: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(params)
    p["steps"] = int(np.clip(p["steps"] + rng.randint(-20, 40), 30, 240))
    p["epsilon"] = float(np.clip(p["epsilon"] + rng.uniform(-0.08, 0.08), 0.0, 0.6))
    p["r"] = float(np.clip(p["r"] + rng.uniform(-0.2, 0.2), 3.0, 4.5))
    if rng.random() < 0.25:
        p["topology"] = rng.choice(["von_neumann", "moore", "small_world"])
    if rng.random() < 0.2:
        p["seed"] = rng.randint(0, 10_000)
    return p


FAMILY_REGISTRY: Dict[str, Dict[str, Any]] = {
    "transcendental_viscosity": {
        "sample": sample_transcendental,
        "render": render_transcendental,
        "mutate": mutate_transcendental,
    },
    "hybrid_orbit_switch": {
        "sample": sample_hybrid_orbit,
        "render": render_hybrid_orbit,
        "mutate": mutate_hybrid_orbit,
    },
    "quaternion_slice": {
        "sample": sample_quaternion_slice,
        "render": render_quaternion_slice,
        "mutate": mutate_quaternion_slice,
    },
    "lyapunov_hybrid": {
        "sample": sample_lyapunov_hybrid,
        "render": render_lyapunov_hybrid,
        "mutate": mutate_lyapunov_hybrid,
    },
    "coupled_map_lattice": {
        "sample": sample_cml,
        "render": render_cml,
        "mutate": mutate_cml,
    },
}


def generate_candidate(size: int, family: str, params: Dict[str, Any]) -> np.ndarray:
    return FAMILY_REGISTRY[family]["render"](size, params)


# -------------------- VLM critic --------------------

CRITIC_PROMPT = (
    "You are a fractal‑art critic helping an autonomous search.\n"
    "Analyze the image ONLY by geometry/texture (ignore color aesthetics).\n"
    "Return strict JSON with keys:\n"
    "- description: short structural description\n"
    "- similarity: what known fractals/phenomena it resembles (or 'none')\n"
    "- novelty_score: 0-10 (new structure)\n"
    "- excitement_score: 0-10 (visual drama/interestingness)\n"
    "- variety_score: 0-10 (internal variety across the image)\n"
    "- failure_flags: array of strings if boring/flat/noisy/blank/etc.\n"
    "- suggested_mutations: array of short suggestions (e.g. 'increase coupling', 'try sin fold', 'more switching')\n"
    "- tags: array of 3-8 structural tags.\n"
    "Be honest; if it's boring say so."
)


def parse_critic_json(text: str) -> Dict[str, Any]:
    try:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
    except Exception:
        pass
    out: Dict[str, Any] = {"description": text.strip(), "tags": []}
    for key in ["novelty", "excitement", "variety"]:
        m2 = re.search(rf"{key}[^0-9]*([0-9]+(\.[0-9]+)?)", text, re.IGNORECASE)
        if m2:
            out[f"{key}_score"] = float(m2.group(1))
    out.setdefault("novelty_score", 0.0)
    out.setdefault("excitement_score", 0.0)
    out.setdefault("variety_score", 0.0)
    out.setdefault("similarity", "")
    out.setdefault("failure_flags", [])
    out.setdefault("suggested_mutations", [])
    return out


def critic_available() -> bool:
    return analyze_images is not None and bool(os.getenv("OPENROUTER_API_KEY"))


async def critique_one(image_path: str, model: str) -> Dict[str, Any]:
    if not critic_available():
        return {
            "description": "critic unavailable",
            "novelty_score": None,
            "similarity": None,
            "tags": [],
        }
    try:
        txt = await analyze_images([image_path], CRITIC_PROMPT, model=model)  # type: ignore
        return parse_critic_json(txt)
    except Exception as e:
        return {
            "description": f"critic error: {e}",
            "novelty_score": None,
            "similarity": None,
            "tags": [],
        }


# Style comparison critic (optional)
STYLE_PROMPT = (
    "You are comparing candidate fractals to reference exemplars.\n"
    "Image #1..#N are references in the target style. The last image is the candidate.\n"
    "Return strict JSON with keys:\n"
    "- similarity_score: 0-10 for stylistic similarity to references\n"
    "- keeps_style: boolean (true if candidate feels like same family/style)\n"
    "- notes: short text on why/why not\n"
    "- suggested_mutations: array of 1-4 tweaks to get closer to style."
)


async def critique_style(reference_paths: List[str], candidate_path: str, model: str) -> Dict[str, Any]:
    if not critic_available() or not reference_paths:
        return {"similarity_score": None, "keeps_style": None, "notes": "", "suggested_mutations": []}
    try:
        paths = reference_paths + [candidate_path]
        txt = await analyze_images(paths, STYLE_PROMPT, model=model)  # type: ignore
        data = parse_critic_json(txt)
        # normalize expected keys
        if "similarity_score" not in data:
            m = re.search(r"similarity[^0-9]*([0-9]+(\.[0-9]+)?)", txt, re.IGNORECASE)
            data["similarity_score"] = float(m.group(1)) if m else 0.0
        data.setdefault("keeps_style", None)
        data.setdefault("notes", txt.strip())
        data.setdefault("suggested_mutations", [])
        return data
    except Exception as e:
        return {"similarity_score": None, "keeps_style": None, "notes": f"style critic error: {e}", "suggested_mutations": []}


# -------------------- Gallery + report --------------------

def novelty_heuristic(ent: float, edge: float, cr: float) -> float:
    return 0.55 * ent + 2.0 * edge + 1.5 * (1.0 - cr)


def build_html(items: List[Dict[str, Any]]) -> str:
    rows = []
    for it in items:
        params_pre = json.dumps(it["params"], indent=2)
        critic = it.get("critic", {}) or {}
        desc = critic.get("description", "")
        score = critic.get("novelty_score")
        exc = critic.get("excitement_score")
        var = critic.get("variety_score")
        tags = ", ".join(critic.get("tags", []) or [])
        novelty_val = score if isinstance(score, (int, float)) else it["heuristic_novelty"]
        excitement_val = exc if isinstance(exc, (int, float)) else it.get("heuristic_excitement", 0.0)
        variety_val = var if isinstance(var, (int, float)) else it.get("heuristic_variety", 0.0)
        rows.append(
            f"""
            <div class="card">
              <img src="{it['rel_path']}" loading="lazy" />
              <div class="meta">
                <div><b>{it['family']}</b> — id {it['id']}</div>
                <div>Novelty: {novelty_val:.2f} · Excitement: {excitement_val:.2f} · Variety: {variety_val:.2f}</div>
                <div>Entropy: {it['entropy']:.2f} · Edge: {it['edge_density']:.3f} · PNG/Raw: {it['compression_ratio']:.3f}</div>
                <div>Tags: {tags}</div>
                <pre>{params_pre}</pre>
                <div class="desc">{desc}</div>
              </div>
            </div>
            """
        )
    cards = "\n".join(rows)
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Novel Fractal Gallery</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 18px; background:#0b0b0d; color:#eee; }}
    h1 {{ font-size: 20px; }}
    .grid {{ display:grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 12px; }}
    .card {{ background:#15151a; border:1px solid #222; border-radius:8px; overflow:hidden; }}
    img {{ width:100%; height:auto; display:block; }}
    .meta {{ padding:8px 10px; font-size:12px; line-height:1.35; }}
    pre {{ background:#0f0f12; padding:8px; border-radius:6px; overflow:auto; max-height:200px; }}
    .desc {{ margin-top:6px; opacity:.9; }}
  </style>
</head>
<body>
  <h1>Novel Fractal Gallery</h1>
  <p>Generated {len(items)} candidates. Sorted by novelty.</p>
  <div class="grid">{cards}</div>
</body>
</html>"""


async def main_async(args: argparse.Namespace) -> None:
    ensure_dirs()
    rng = random.Random(args.seed)

    items: List[Dict[str, Any]] = []
    palettes = ["gray", "hsv", "duotone"]

    # Population of genomes (family + params)
    population: List[Dict[str, Any]] = []
    if args.focus_families:
        families = [f.strip() for f in args.focus_families.split(",") if f.strip() in FAMILY_REGISTRY]
        if not families:
            families = list(FAMILY_REGISTRY.keys())
    else:
        families = list(FAMILY_REGISTRY.keys())
    for _ in range(args.population):
        fam = rng.choice(families)
        population.append({"family": fam, "params": FAMILY_REGISTRY[fam]["sample"](rng)})

    # Load reference images by id from last summary if requested
    reference_paths: List[str] = []
    if args.reference_ids:
        try:
            with open(SUMMARY_PATH, "r", encoding="utf-8") as f:
                prev = json.load(f)
            id_set = {int(x) for x in args.reference_ids.split(",") if x.strip().isdigit()}
            for it in prev:
                if int(it.get("id", -1)) in id_set and os.path.exists(it.get("path", "")):
                    reference_paths.append(it["path"])
        except Exception:
            reference_paths = []

    global_id = 0

    def heuristic_scores(gray: np.ndarray, rgb: np.ndarray) -> Tuple[float, float, float]:
        ent = shannon_entropy(gray)
        edge = edge_density(gray)
        cr = compression_ratio(rgb)
        heur_nov = novelty_heuristic(ent, edge, cr)
        heur_exc = 0.7 * edge + 0.3 * ent
        heur_var = ent
        return heur_nov, heur_exc, heur_var

    def total_score(it: Dict[str, Any], fam_counts: Dict[str, int], tag_counts: Dict[str, int]) -> float:
        critic = it.get("critic", {}) or {}
        ns = critic.get("novelty_score")
        es = critic.get("excitement_score")
        vs = critic.get("variety_score")
        ss = (it.get("style_critic", {}) or {}).get("similarity_score")
        hn = it.get("heuristic_novelty", 0.0)
        he = it.get("heuristic_excitement", 0.0)
        hv = it.get("heuristic_variety", 0.0)
        n = float(ns) if isinstance(ns, (int, float)) else hn
        e = float(es) if isinstance(es, (int, float)) else he
        v = float(vs) if isinstance(vs, (int, float)) else hv
        base = args.w_novelty * n + args.w_excitement * e + args.w_variety * v
        if isinstance(ss, (int, float)):
            base += args.w_style * float(ss)
        # Diversity bonus: prefer rare families and tags in current archive
        fam_bonus = 0.6 / math.sqrt(1 + fam_counts.get(it["family"], 0))
        bonus = fam_bonus
        for t in critic.get("tags", []) or []:
            bonus += 0.15 / math.sqrt(1 + tag_counts.get(t, 0))
        return base + bonus

    for gen in range(args.generations):
        gen_items: List[Dict[str, Any]] = []
        for genome in population:
            family = genome["family"]
            params = genome["params"]
            field = generate_candidate(args.size, family, params)
            gray = normalize_to_uint8(field)
            pal = rng.choice(palettes)
            rgb = apply_palette(gray, pal, rng)
            out_name = f"g{gen:02d}_{global_id:04d}_{family}.png"
            out_path = os.path.join(IMAGES_DIR, out_name)
            save_image(rgb, out_path)

            hn, he, hv = heuristic_scores(gray, rgb)
            gen_items.append(
                {
                    "id": global_id,
                    "generation": gen,
                    "family": family,
                    "params": params,
                    "palette": pal,
                    "path": out_path,
                    "entropy": shannon_entropy(gray),
                    "edge_density": edge_density(gray),
                    "compression_ratio": compression_ratio(rgb),
                    "heuristic_novelty": hn,
                    "heuristic_excitement": he,
                    "heuristic_variety": hv,
                    "parent_id": genome.get("parent_id"),
                }
            )
            global_id += 1

        # Critique all items this generation
        if critic_available():
            sem = asyncio.Semaphore(args.max_concurrency)

            async def wrapped(it: Dict[str, Any]) -> None:
                async with sem:
                    it["critic"] = await critique_one(it["path"], args.model)

            await asyncio.gather(*(wrapped(it) for it in gen_items))
        else:
            for it in gen_items:
                it["critic"] = {
                    "novelty_score": None,
                    "excitement_score": None,
                    "variety_score": None,
                    "description": "critic unavailable",
                    "tags": [],
                }

        # Optional style critic against references
        if reference_paths and critic_available():
            sem2 = asyncio.Semaphore(max(1, args.max_concurrency // 2))

            async def wrapped_style(it: Dict[str, Any]) -> None:
                async with sem2:
                    it["style_critic"] = await critique_style(reference_paths, it["path"], args.model)

            await asyncio.gather(*(wrapped_style(it) for it in gen_items))
        else:
            for it in gen_items:
                it["style_critic"] = {"similarity_score": None}

        items.extend(gen_items)

        # Selection with diversity
        fam_counts: Dict[str, int] = {}
        tag_counts: Dict[str, int] = {}
        for it in items:
            fam_counts[it["family"]] = fam_counts.get(it["family"], 0) + 1
            for t in (it.get("critic", {}) or {}).get("tags", []) or []:
                tag_counts[t] = tag_counts.get(t, 0) + 1

        for it in gen_items:
            it["total_score"] = total_score(it, fam_counts, tag_counts)

        gen_items.sort(key=lambda x: x["total_score"], reverse=True)
        elites = gen_items[: args.elite]

        # Build next generation
        next_pop: List[Dict[str, Any]] = []
        for e in elites:
            next_pop.append(
                {
                    "family": e["family"],
                    "params": e["params"],
                    "parent_id": e["id"],
                    "feedback": e.get("critic", {}),
                }
            )

        # Add mutated offspring from elites
        while len(next_pop) < args.population - args.random_each_gen:
            parent = rng.choice(elites)
            fam = parent["family"]
            fb = parent.get("critic", {}) or {}
            style_fb = parent.get("style_critic", {}) or {}
            if isinstance(style_fb, dict) and style_fb.get("suggested_mutations"):
                fb = dict(fb)
                fb["suggested_mutations"] = style_fb.get("suggested_mutations")
            child_params = FAMILY_REGISTRY[fam]["mutate"](rng, parent["params"], fb)
            next_pop.append({"family": fam, "params": child_params, "parent_id": parent["id"]})

        # Add a few random explorers
        for _ in range(args.random_each_gen):
            fam = rng.choice(families)
            next_pop.append({"family": fam, "params": FAMILY_REGISTRY[fam]["sample"](rng)})

        population = next_pop

    # Final sort for report
    fam_counts_final: Dict[str, int] = {}
    tag_counts_final: Dict[str, int] = {}
    for it in items:
        fam_counts_final[it["family"]] = fam_counts_final.get(it["family"], 0) + 1
        for t in (it.get("critic", {}) or {}).get("tags", []) or []:
            tag_counts_final[t] = tag_counts_final.get(t, 0) + 1
    for it in items:
        it["total_score"] = total_score(it, fam_counts_final, tag_counts_final)

    items.sort(key=lambda x: x["total_score"], reverse=True)

    for it in items:
        it["rel_path"] = os.path.relpath(it["path"], OUTPUT_ROOT)

    with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(build_html(items))

    print(f"Wrote gallery to {REPORT_PATH}")


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Autonomous novel fractal gallery experiment.")
    p.add_argument("--size", type=int, default=512, help="Image size (square).")
    p.add_argument("--seed", type=int, default=0, help="RNG seed.")
    p.add_argument("--model", type=str, default=DEFAULT_MODEL, help="OpenRouter VLM model.")
    p.add_argument("--max-concurrency", type=int, default=4, help="Parallel VLM calls.")
    p.add_argument("--generations", type=int, default=6, help="Number of VLM-guided iterations.")
    p.add_argument("--population", type=int, default=18, help="Candidates per generation.")
    p.add_argument("--elite", type=int, default=6, help="Elites kept each generation.")
    p.add_argument("--random-each-gen", type=int, default=3, help="Random explorers per generation.")
    p.add_argument("--w-novelty", type=float, default=1.0, help="Weight for novelty_score.")
    p.add_argument("--w-excitement", type=float, default=1.2, help="Weight for excitement_score.")
    p.add_argument("--w-variety", type=float, default=0.9, help="Weight for variety_score.")
    p.add_argument("--w-style", type=float, default=1.1, help="Weight for style similarity to references.")
    p.add_argument("--focus-families", type=str, default="", help="Comma-separated families to focus on.")
    p.add_argument("--reference-ids", type=str, default="", help="Comma-separated IDs from previous run to use as style references.")
    return p


def main() -> None:
    args = build_argparser().parse_args()
    t0 = time.time()
    asyncio.run(main_async(args))
    print(f"Done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
