#!/usr/bin/env python3
"""
Render a small, standardized tile set for a dataset and evaluate seam quality.

This is intended to be the "one command" evaluation step for future iteration agents:
- Renders: L0 root and all L1 (2×2 quad).
- Produces artifacts: stitched L1 center, seam crop at the tile intersection, metrics JSON, and optional VLM report.

Usage:
  python experiments/iterate_t2i/evaluate_dataset.py --dataset generative_infinity_zoom_v9 --clean

Override renderer args (e.g. model swap) without editing config.json:
  python experiments/iterate_t2i/evaluate_dataset.py \\
    --dataset generative_infinity_zoom_v9 \\
    --renderer-args '{"unet_name":"my_new_unet.safetensors"}'
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from PIL import Image, ImageChops


REPO_ROOT = Path(__file__).resolve().parents[2]
import sys

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))

from backend import render_tiles  # noqa: E402
from backend.renderer_utils import load_renderer  # noqa: E402


def _mean_abs_diff_rgb(a: Image.Image, b: Image.Image) -> float:
    if a.size != b.size:
        raise ValueError(f"Images must match size: {a.size} vs {b.size}")
    diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
    px = list(diff.getdata())
    if not px:
        return 0.0
    return sum((p[0] + p[1] + p[2]) / 3.0 for p in px) / len(px)


def _seam_metrics_for_quad(tl: Image.Image, tr: Image.Image, bl: Image.Image, br: Image.Image, *, strip: int = 8) -> Dict[str, float]:
    ts = tl.size[0]
    if any(img.size != (ts, ts) for img in (tr, bl, br)):
        raise ValueError("All quad tiles must share the same size")
    if strip <= 0 or strip >= ts:
        raise ValueError("strip must be in (0, tile_size)")

    # Vertical seams (left vs right)
    v_top = _mean_abs_diff_rgb(tl.crop((ts - strip, 0, ts, ts)), tr.crop((0, 0, strip, ts)))
    v_bottom = _mean_abs_diff_rgb(bl.crop((ts - strip, 0, ts, ts)), br.crop((0, 0, strip, ts)))

    # Horizontal seams (top vs bottom)
    h_left = _mean_abs_diff_rgb(tl.crop((0, ts - strip, ts, ts)), bl.crop((0, 0, ts, strip)))
    h_right = _mean_abs_diff_rgb(tr.crop((0, ts - strip, ts, ts)), br.crop((0, 0, ts, strip)))

    avg = (v_top + v_bottom + h_left + h_right) / 4.0
    return {
        "strip_px": float(strip),
        "vertical_top_mad": float(v_top),
        "vertical_bottom_mad": float(v_bottom),
        "horizontal_left_mad": float(h_left),
        "horizontal_right_mad": float(h_right),
        "seam_mad_avg": float(avg),
    }


def _stitch_quad(dataset_dir: Path, *, level: int, x0: int, y0: int) -> Tuple[Image.Image, Dict[Tuple[int, int], Path]]:
    tiles: Dict[Tuple[int, int], Image.Image] = {}
    paths: Dict[Tuple[int, int], Path] = {}
    for dx in (0, 1):
        for dy in (0, 1):
            x = x0 + dx
            y = y0 + dy
            p = dataset_dir / str(level) / str(x) / f"{y}.webp"
            if not p.exists():
                raise FileNotFoundError(f"Missing tile: {p}")
            paths[(x, y)] = p
            tiles[(x, y)] = Image.open(p).convert("RGB")

    ts = tiles[(x0, y0)].size[0]
    canvas = Image.new("RGB", (ts * 2, ts * 2))
    canvas.paste(tiles[(x0, y0)], (0, 0))
    canvas.paste(tiles[(x0 + 1, y0)], (ts, 0))
    canvas.paste(tiles[(x0, y0 + 1)], (0, ts))
    canvas.paste(tiles[(x0 + 1, y0 + 1)], (ts, ts))
    return canvas, paths


def _generate_html_report(
    *,
    dataset_id: str,
    score: float,
    report_text: str,
    rel_center_path: str,
    rel_seam_path: str,
    out_path: Path,
) -> None:
    html = f"""
<html>
<head><title>{dataset_id} Evaluation</title></head>
<body style="font-family: sans-serif; max-width: 900px; margin: 0 auto; padding: 20px;">
  <h1>{dataset_id} Evaluation</h1>
  <h2>Score: <span style="color: {'green' if score >= 8 else 'red'}">{score}/10</span></h2>
  <h3>1. Stitched L1 Quad</h3>
  <img src="{rel_center_path}" style="max-width: 100%; border: 1px solid #ccc;">
  <h3>2. Seam Detail (Magnified)</h3>
  <img src="{rel_seam_path}" style="max-width: 100%; border: 1px solid #ccc;">
  <h3>3. AI Critique</h3>
  <pre style="white-space: pre-wrap; background: #f0f0f0; padding: 10px;">{report_text}</pre>
</body>
</html>
"""
    out_path.write_text(html, encoding="utf-8")


class _MockComfyUIClient:
    """
    Minimal in-process stand-in for ComfyUIClient.

    - T2I: returns a deterministic quadrant pattern image
    - Img2Img/Inpaint: returns the center crop of the uploaded context canvas
      (guesses tile_size as the largest power-of-two <= canvas size).
    """

    def __init__(self, server_address: str, client_id: str, request_timeout_s: float = 60.0):  # noqa: ARG002
        self.server_address = server_address
        self.client_id = client_id
        self._uploads: Dict[str, Path] = {}
        self._last_workflow: Optional[Dict[str, Any]] = None
        self._last_prompt_id = "mock_prompt_id"

    def close(self) -> None:
        return

    def upload_image(self, filepath: Path, *, overwrite: bool = True) -> str:  # noqa: ARG002
        name = filepath.name
        self._uploads[name] = Path(filepath)
        return name

    def queue_prompt(self, workflow: Dict[str, Any]) -> str:
        self._last_workflow = json.loads(json.dumps(workflow))
        return self._last_prompt_id

    def wait_for_prompt(self, prompt_id: str, timeout_s: float) -> None:  # noqa: ARG002
        return

    def get_history(self, prompt_id: str) -> Dict[str, Any]:  # noqa: ARG002
        return {
            self._last_prompt_id: {
                "outputs": {
                    "9": {"images": [{"filename": "mock_out.png", "subfolder": "", "type": "output"}]},
                }
            }
        }

    def _guess_tile_size(self, canvas_w: int, canvas_h: int) -> int:
        n = min(canvas_w, canvas_h)
        p = 1
        while p * 2 <= n:
            p *= 2
        return p

    def get_image_data(self, image_ref) -> bytes:  # noqa: ANN001
        # If we have a context canvas uploaded (node "100" by convention), produce a center crop.
        wf = self._last_workflow or {}
        ctx_name = None
        node100 = wf.get("100") if isinstance(wf, dict) else None
        if isinstance(node100, dict):
            inputs = node100.get("inputs") or {}
            if isinstance(inputs, dict):
                ctx_name = inputs.get("image")

        if isinstance(ctx_name, str) and ctx_name in self._uploads and self._uploads[ctx_name].exists():
            ctx = Image.open(self._uploads[ctx_name]).convert("RGB")
            ts = self._guess_tile_size(*ctx.size)
            pad = max(0, (ctx.size[0] - ts) // 2)
            out = ctx.crop((pad, pad, pad + ts, pad + ts))
        else:
            # Default: deterministic smooth gradient (helps sanity-check that seams are low).
            out = Image.new("RGB", (1024, 1024))
            px = out.load()
            for y in range(1024):
                for x in range(1024):
                    r = int(255 * x / 1023)
                    g = int(255 * y / 1023)
                    b = int(255 * (x ^ y) / 1023)
                    px[x, y] = (r, g, b)

        buf = io.BytesIO()
        out.save(buf, format="PNG")
        return buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True, help="Dataset id under datasets/<id>/")
    ap.add_argument("--clean", action="store_true", help="Delete levels 0/1 before rendering.")
    ap.add_argument("--workers", type=int, default=0, help="0=main process (debug), 1+=process pool.")
    ap.add_argument("--renderer-args", default="{}", help="JSON dict merged into config renderer_args (CLI overrides).")
    ap.add_argument("--strip", type=int, default=8, help="Seam strip width in pixels for deterministic metric.")
    ap.add_argument("--crop", type=int, default=128, help="Crop size around the 4-tile intersection (pixels).")
    ap.add_argument("--outdir", default=None, help="Defaults to artifacts/eval_<dataset>/")
    ap.add_argument("--mock", action="store_true", help="Run without a live ComfyUI server (deterministic mock).")
    args = ap.parse_args()

    dataset_id = args.dataset
    dataset_dir = REPO_ROOT / "datasets" / dataset_id
    config_path = dataset_dir / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"Missing {config_path}")

    try:
        override_args = json.loads(args.renderer_args)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON passed to --renderer-args: {exc}") from exc
    if not isinstance(override_args, dict):
        raise SystemExit("--renderer-args must decode to a JSON object (dictionary).")

    conf = json.loads(config_path.read_text(encoding="utf-8"))
    tile_size = int(conf["tile_size"])
    renderer_path = conf["renderer"]
    renderer_kwargs = dict(conf.get("renderer_args") or {})
    renderer_kwargs.update(override_args)

    if args.clean:
        for level in ("0", "1"):
            shutil.rmtree(dataset_dir / level, ignore_errors=True)

    if args.mock:
        from unittest.mock import patch

        with patch("backend.comfyui_client.ComfyUIClient", _MockComfyUIClient):
            renderer = load_renderer(renderer_path, tile_size, renderer_kwargs, dataset_path=str(dataset_dir))
            tasks = [
                (0, 0, 0, str(dataset_dir)),
                *( (1, x, y, str(dataset_dir)) for x in (0, 1) for y in (0, 1) ),
            ]
            render_tiles.render_tasks(renderer, tasks, num_workers=0)
    else:
        renderer = load_renderer(renderer_path, tile_size, renderer_kwargs, dataset_path=str(dataset_dir))

        # Render a fixed, minimal set of tiles (L0 + L1).
        tasks = [
            (0, 0, 0, str(dataset_dir)),
            *( (1, x, y, str(dataset_dir)) for x in (0, 1) for y in (0, 1) ),
        ]
        render_tiles.render_tasks(renderer, tasks, num_workers=int(args.workers))

    outdir = Path(args.outdir) if args.outdir else (REPO_ROOT / "artifacts" / f"eval_{dataset_id}")
    outdir.mkdir(parents=True, exist_ok=True)

    stitched, paths = _stitch_quad(dataset_dir, level=1, x0=0, y0=0)
    center_path = outdir / "level_1_center.png"
    stitched.save(center_path)

    # Crop around the true intersection at (tile_size, tile_size) in stitched coords.
    crop = int(args.crop)
    cx = tile_size
    cy = tile_size
    seam_crop = stitched.crop((cx - crop // 2, cy - crop // 2, cx + crop // 2, cy + crop // 2))
    seam_detail = seam_crop.resize((512, 512), Image.Resampling.NEAREST)
    seam_path = outdir / "level_1_seam_detail.png"
    seam_detail.save(seam_path)

    # Deterministic seam metrics from the 4 constituent tiles.
    tl = Image.open(paths[(0, 0)]).convert("RGB")
    tr = Image.open(paths[(1, 0)]).convert("RGB")
    bl = Image.open(paths[(0, 1)]).convert("RGB")
    br = Image.open(paths[(1, 1)]).convert("RGB")
    metrics = _seam_metrics_for_quad(tl, tr, bl, br, strip=int(args.strip))

    result: Dict[str, Any] = {
        "dataset": dataset_id,
        "tile_size": tile_size,
        "renderer": renderer_path,
        "renderer_args_overrides": override_args,
        "artifacts": {
            "level_1_center": str(center_path),
            "level_1_seam_detail": str(seam_path),
        },
        "metrics": metrics,
        "vlm": None,
    }

    if os.environ.get("OPENROUTER_API_KEY"):
        from backend.tools.analyze_image import analyze_images  # noqa: E402
        import asyncio  # noqa: E402

        prompt = (
            "This is a magnified view of the intersection where 4 generated image tiles meet (Level 1, 2×2 quad). "
            "Rate the quality of the stitching on a scale of 0 to 10 (10 = Perfect, Seamless). "
            "Provide the score as 'SCORE: X/10'. "
            "Then explain your reasoning. Look for sharp lines, color discontinuities, or broken textures."
        )
        report_text = asyncio.run(analyze_images([str(seam_path)], prompt))
        score = 0.0
        m = re.search(r"SCORE:\\s*(\\d+(\\.\\d+)?)/10", report_text, re.IGNORECASE)
        if m:
            score = float(m.group(1))

        report_path = outdir / "report.html"
        _generate_html_report(
            dataset_id=dataset_id,
            score=score,
            report_text=report_text,
            rel_center_path=center_path.name,
            rel_seam_path=seam_path.name,
            out_path=report_path,
        )
        result["vlm"] = {"score": score, "report": report_text, "report_path": str(report_path)}

    summary_path = outdir / "summary.json"
    summary_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({"summary": str(summary_path), "metrics": metrics, "vlm": result["vlm"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
