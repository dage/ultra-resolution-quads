#!/usr/bin/env python3
"""
Model benchmark harness for ComfyUI inpaint workflows.

Goal: quickly compare candidate UNET/CLIP combos on *controlled, repeatable* tasks where a
"better model" should predictably score better:
  - task A: mask-localized color fill (sanity check; should be perfect)
  - task B: pattern continuation inside an inpaint hole (should preserve border + continue lines)

This produces deterministic numeric metrics (no VLM required), plus optional VLM critique.

Usage:
  set -a; source .env; set +a
  python experiments/iterate_t2i/benchmark_models.py \\
    --server 127.0.0.1:8000 \\
    --workflow experiments/iterate_t2i/workflows/genzoom_inpaint_diffdiff_workflow.json \\
    --models z_image_turbo-Q5_K_S.gguf,z_image_turbo-Q8_0.gguf
"""

from __future__ import annotations

import argparse
import io
import json
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageChops, ImageDraw, ImageFilter

REPO_ROOT = Path(__file__).resolve().parents[2]
import sys

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.comfyui_client import ComfyUIClient, first_image_ref_from_history  # noqa: E402


@dataclass(frozen=True)
class CropSpec:
    x: int
    y: int
    width: int
    height: int


def load_workflow(path: Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


def get_crop_spec(workflow: Dict) -> CropSpec:
    node = workflow.get("103") or {}
    inputs = node.get("inputs") or {}
    return CropSpec(
        x=int(inputs.get("x", 0)),
        y=int(inputs.get("y", 0)),
        width=int(inputs.get("width", 512)),
        height=int(inputs.get("height", 512)),
    )


def guess_canvas_size(crop: CropSpec) -> Tuple[int, int]:
    return crop.width + 2 * crop.x, crop.height + 2 * crop.y


def make_mask_rgba(canvas_w: int, canvas_h: int, crop: CropSpec, hole: Tuple[int, int, int, int]) -> Image.Image:
    """
    Current best guess for our Comfy wiring:
    - alpha=0 => inpaint region
    - alpha=255 => keep
    """
    mask = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 255))
    d = ImageDraw.Draw(mask)
    l, t, r, b = hole
    d.rectangle([crop.x + l, crop.y + t, crop.x + r, crop.y + b], fill=(0, 0, 0, 0))
    mask = mask.filter(ImageFilter.GaussianBlur(radius=max(2, crop.width // 64)))
    return mask


def pattern_canvas(canvas_w: int, canvas_h: int, crop: CropSpec) -> Image.Image:
    """A deterministic synthetic texture with lines crossing into the crop area."""
    img = Image.new("RGB", (canvas_w, canvas_h), color=(200, 200, 200))
    d = ImageDraw.Draw(img)

    # A few thick lines that cross the crop region.
    for i in range(0, max(canvas_w, canvas_h), 32):
        d.line([(0, i), (canvas_w, i + 16)], fill=(90, 90, 90), width=6)
        d.line([(i, 0), (i + 16, canvas_h)], fill=(120, 120, 120), width=4)

    # Outline the crop region.
    d.rectangle([crop.x, crop.y, crop.x + crop.width - 1, crop.y + crop.height - 1], outline=(20, 20, 20), width=2)
    return img


def crop_to_output(img: Image.Image, crop: CropSpec) -> Image.Image:
    return img.crop((crop.x, crop.y, crop.x + crop.width, crop.y + crop.height))


def mean_abs_diff(a: Image.Image, b: Image.Image, rect: Tuple[int, int, int, int]) -> float:
    l, t, r, bottom = rect
    ra = a.crop((l, t, r, bottom)).convert("RGB")
    rb = b.crop((l, t, r, bottom)).convert("RGB")
    diff = ImageChops.difference(ra, rb)
    px = list(diff.getdata())
    if not px:
        return 0.0
    return sum((p[0] + p[1] + p[2]) / 3.0 for p in px) / len(px)


def laplacian_sharpness(img: Image.Image) -> float:
    # Cheap sharpness proxy: mean absolute response of a Laplacian-like kernel on grayscale.
    g = img.convert("L")
    # 3x3 Laplacian kernel
    k = ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1, offset=0)
    resp = g.filter(k)
    px = list(resp.getdata())
    return sum(abs(v) for v in px) / len(px) if px else 0.0


def run_once(
    client: ComfyUIClient,
    workflow: Dict,
    *,
    ctx_path: Path,
    mask_path: Path,
    prompt: str,
    unet_name: Optional[str],
    clip_name: Optional[str],
    denoise: float,
    steps: int,
    cfg: float,
    save_node: str = "9",
) -> Image.Image:
    wf = json.loads(json.dumps(workflow))

    # Patch model filenames if requested.
    if unet_name and "13" in wf:
        wf["13"]["inputs"]["unet_name"] = unet_name
    if clip_name and "16" in wf:
        wf["16"]["inputs"]["clip_name"] = clip_name

    ctx_name = client.upload_image(ctx_path)
    mask_name = client.upload_image(mask_path)
    wf["100"]["inputs"]["image"] = ctx_name
    wf["101"]["inputs"]["image"] = mask_name

    wf["6"]["inputs"]["prompt"] = prompt
    wf["3"]["inputs"]["seed"] = random.randint(1, 10**14)
    wf["3"]["inputs"]["denoise"] = float(denoise)
    wf["3"]["inputs"]["steps"] = int(steps)
    wf["3"]["inputs"]["cfg"] = float(cfg)

    prompt_id = client.queue_prompt(wf)
    client.wait_for_prompt(prompt_id, timeout_s=1200)
    hist = client.get_history(prompt_id)
    data = hist.get(prompt_id, {})
    img_ref = first_image_ref_from_history(data, preferred_node=save_node)
    if not img_ref:
        raise RuntimeError(f"No image returned for prompt {prompt_id}")
    raw = client.get_image_data(img_ref)
    return Image.open(io.BytesIO(raw)).convert("RGB")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="127.0.0.1:8000")
    ap.add_argument("--workflow", default="experiments/iterate_t2i/workflows/genzoom_inpaint_diffdiff_workflow.json")
    ap.add_argument("--models", required=True, help="Comma-separated unet filenames to test (node 13 unet_name).")
    ap.add_argument("--clip", default=None, help="Optional override for node 16 clip_name.")
    ap.add_argument("--outdir", default="artifacts/model_bench")
    args = ap.parse_args()

    wf_path = Path(args.workflow)
    wf = load_workflow(wf_path)
    crop = get_crop_spec(wf)
    canvas_w, canvas_h = guess_canvas_size(crop)

    # Use a fixed inpaint hole in output coords: center square.
    hole_size = crop.width // 2
    hole = (
        crop.width // 2 - hole_size // 2,
        crop.height // 2 - hole_size // 2,
        crop.width // 2 + hole_size // 2,
        crop.height // 2 + hole_size // 2,
    )

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    clip_name = args.clip

    client = ComfyUIClient(args.server, f"bench-{os.getpid()}-{random.randint(1000,9999)}")
    try:
        rows: List[Dict] = []
        for model in models:
            model_dir = outdir / model.replace("/", "_")
            model_dir.mkdir(parents=True, exist_ok=True)

            # Task B: pattern continuation (compare against original context crop, hole region only).
            ctx = pattern_canvas(canvas_w, canvas_h, crop)
            mask = make_mask_rgba(canvas_w, canvas_h, crop, hole)
            ctx_path = model_dir / "ctx.png"
            mask_path = model_dir / "mask.png"
            ctx.save(ctx_path)
            mask.save(mask_path)

            prompt = (
                "Continue the existing line pattern naturally inside the masked region. "
                "Do not change the surrounding border pixels."
            )

            t0 = time.perf_counter()
            out_img = run_once(
                client,
                wf,
                ctx_path=ctx_path,
                mask_path=mask_path,
                prompt=prompt,
                unet_name=model,
                clip_name=clip_name,
                denoise=0.7,
                steps=12,
                cfg=4.0,
                save_node="9",
            )
            dt = time.perf_counter() - t0

            out_path = model_dir / "out.png"
            out_img.save(out_path)

            # Metrics:
            # - interior_diff: how much the hole area differs from the original (should be >0; indicates it changed)
            # - border_drift: how much the whole crop drifted (should be low)
            # - sharpness: higher is better (avoid blur)
            ctx_crop = crop_to_output(ctx, crop)
            interior_diff = mean_abs_diff(out_img, ctx_crop, hole)
            border_drift = mean_abs_diff(out_img, ctx_crop, (0, 0, crop.width, crop.height))
            sharp = laplacian_sharpness(out_img)

            rows.append(
                {
                    "unet": model,
                    "seconds": round(dt, 2),
                    "interior_diff": round(interior_diff, 2),
                    "border_drift": round(border_drift, 2),
                    "sharpness": round(sharp, 2),
                    "output": str(out_path),
                }
            )

        summary_path = outdir / "summary.json"
        summary_path.write_text(json.dumps({"workflow": str(wf_path), "rows": rows}, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"workflow": str(wf_path), "rows": rows, "summary": str(summary_path)}, indent=2))
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
