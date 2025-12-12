import os
import sys
import math
import argparse

import numpy as np
from PIL import Image

DATA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def load_tile(dataset_id: str, level: int, x: int, y: int) -> Image.Image:
    path = os.path.join(DATA_ROOT, "datasets", dataset_id, str(level), str(x), f"{y}.webp")
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    return Image.open(path).convert("RGB")


def compare(a: Image.Image, b: Image.Image) -> dict:
    if a.size != b.size:
        b = b.resize(a.size, Image.Resampling.BOX)
    aa = np.asarray(a, dtype=np.float32)
    bb = np.asarray(b, dtype=np.float32)
    diff = aa - bb
    mae = float(np.mean(np.abs(diff)))
    rmse = float(math.sqrt(float(np.mean(diff * diff))))
    max_diff = int(np.max(np.abs(diff)))
    return {"mae": mae, "rmse": rmse, "max_diff": max_diff}


def downsample2_u8(img_u8: np.ndarray) -> np.ndarray:
    a = img_u8.astype(np.uint16)
    s = a[0::2, 0::2] + a[1::2, 0::2] + a[0::2, 1::2] + a[1::2, 1::2]
    return ((s + 2) // 4).astype(np.uint8)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="hybrid_orbit_switch_id3")
    ap.add_argument("--save-debug", action="store_true")
    args = ap.parse_args()

    l0 = load_tile(args.dataset, 0, 0, 0)

    tl = load_tile(args.dataset, 1, 0, 0)
    tr = load_tile(args.dataset, 1, 1, 0)
    bl = load_tile(args.dataset, 1, 0, 1)
    br = load_tile(args.dataset, 1, 1, 1)

    size = l0.size[0]
    big = Image.new("RGB", (size * 2, size * 2))
    big.paste(tl, (0, 0))
    big.paste(tr, (size, 0))
    big.paste(bl, (0, size))
    big.paste(br, (size, size))

    # Downsample composite to compare against level 0.
    # Use an integer exact 2x BOX downsample (round-to-nearest), so the check is deterministic
    # across platforms and matches the renderer's L0 quantization path.
    big_u8 = np.asarray(big, dtype=np.uint8)
    down_u8 = downsample2_u8(big_u8)
    down = Image.fromarray(down_u8, mode="RGB")

    metrics = compare(l0, down)
    print(metrics)

    if args.save_debug:
        out_dir = os.path.join(DATA_ROOT, "artifacts", "hybrid_orbit_switch_id3_validation")
        os.makedirs(out_dir, exist_ok=True)
        l0.save(os.path.join(out_dir, "level0.webp"))
        big.save(os.path.join(out_dir, "level1_composite.webp"))
        down.save(os.path.join(out_dir, "level1_down.webp"))
        # Diff visualization
        a = np.asarray(l0, dtype=np.int16)
        b = np.asarray(down, dtype=np.int16)
        d = np.clip(np.abs(a - b) * 8, 0, 255).astype(np.uint8)
        Image.fromarray(d, mode="RGB").save(os.path.join(out_dir, "diff_x8.png"))


if __name__ == "__main__":
    sys.exit(main())
