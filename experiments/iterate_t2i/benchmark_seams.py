#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from comfy_runner import load_bindings, load_workflow, run_dir, run_i2i, run_t2i
from models_catalog import MODEL_SPECS, get_model_spec


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

    v_top = _mean_abs_diff_rgb(tl.crop((ts - strip, 0, ts, ts)), tr.crop((0, 0, strip, ts)))
    v_bottom = _mean_abs_diff_rgb(bl.crop((ts - strip, 0, ts, ts)), br.crop((0, 0, strip, ts)))
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


def _quadrant_from_parent(parent: Image.Image, *, tile_size: int, x: int, y: int) -> Image.Image:
    if parent.size != (tile_size, tile_size):
        parent = parent.resize((tile_size, tile_size), Image.Resampling.LANCZOS)
    half = tile_size // 2
    left = (x % 2) * half
    top = (y % 2) * half
    quad = parent.crop((left, top, left + half, top + half))
    return quad.resize((tile_size, tile_size), Image.Resampling.LANCZOS)


def _build_canvas_and_mask(
    *,
    tile_size: int,
    pad: int,
    center_tile: Image.Image,
    neighbors: Dict[Tuple[int, int], Image.Image],
    inpaint_region: str,
    border_ring: int,
    mask_blur: int,
    inpaint_alpha: int,
) -> Tuple[Image.Image, Image.Image]:
    canvas_size = tile_size + 2 * pad
    canvas = Image.new("RGB", (canvas_size, canvas_size), color=(0, 0, 0))

    # Paste available neighbor tiles into the canvas at the correct offsets.
    # neighbors keys are dx,dy relative to center tile (-1,0,+1).
    for (dx, dy), img in neighbors.items():
        if img.size != (tile_size, tile_size):
            img = img.resize((tile_size, tile_size), Image.Resampling.LANCZOS)
        paste_x = pad + dx * tile_size
        paste_y = pad + dy * tile_size
        canvas.paste(img, (int(paste_x), int(paste_y)))

    # Center tile seed in the middle.
    if center_tile.size != (tile_size, tile_size):
        center_tile = center_tile.resize((tile_size, tile_size), Image.Resampling.LANCZOS)
    canvas.paste(center_tile, (pad, pad))

    mask = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 255))
    draw = ImageDraw.Draw(mask)
    if inpaint_region == "full_tile":
        rect = [pad, pad, pad + tile_size, pad + tile_size]
    else:
        br = int(border_ring)
        rect = [pad + br, pad + br, pad + tile_size - br, pad + tile_size - br]
    draw.rectangle(rect, fill=(0, 0, 0, int(inpaint_alpha)))
    if mask_blur > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(radius=int(mask_blur)))

    return canvas, mask


def _stitch_quad(tl: Image.Image, tr: Image.Image, bl: Image.Image, br: Image.Image) -> Image.Image:
    ts = tl.size[0]
    canvas = Image.new("RGB", (ts * 2, ts * 2))
    canvas.paste(tl, (0, 0))
    canvas.paste(tr, (ts, 0))
    canvas.paste(bl, (0, ts))
    canvas.paste(br, (ts, ts))
    return canvas


def _write_report(outdir: Path, *, model: str, metrics: Optional[Dict[str, Any]], vlm: Optional[Dict[str, Any]]) -> None:
    def esc(s: Any) -> str:
        text = "" if s is None else str(s)
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
        )

    metrics_rows = ""
    if isinstance(metrics, dict):
        metrics_rows = "".join(f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>" for k, v in metrics.items())

    score = None
    report_text = None
    if isinstance(vlm, dict):
        score = vlm.get("score")
        report_text = vlm.get("report")

    html = f"""\
<html>
<head>
  <meta charset="utf-8" />
  <title>iterate_t2i seam benchmark</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif; max-width: 980px; margin: 0 auto; padding: 20px;">
  <h1>iterate_t2i seam benchmark</h1>
  <p>Model: <code>{esc(model)}</code></p>
  <h2>L0 seed</h2>
  <img src="level_0.png" style="max-width: 100%; border: 1px solid #ccc;">
  <h2>L1 stitched quad</h2>
  <img src="level_1_center.png" style="max-width: 100%; border: 1px solid #ccc;">
  <h2>Seam detail</h2>
  <img src="level_1_seam_detail.png" style="max-width: 100%; border: 1px solid #ccc;">
  <h2>Deterministic metrics</h2>
  {("<table style=\"border-collapse: collapse; width: 100%;\"><thead><tr><th style=\"border:1px solid #ddd; padding:8px; text-align:left;\">metric</th><th style=\"border:1px solid #ddd; padding:8px; text-align:left;\">value</th></tr></thead><tbody>"
    + metrics_rows
    + "</tbody></table>") if metrics_rows else "<p><i>No metrics</i></p>"}
  <h2>VLM critique (optional)</h2>
  {("<p>Score: <b>" + esc(score) + "/10</b></p>") if score is not None else "<p><i>Not run.</i></p>"}
  {("<pre style=\"white-space: pre-wrap; background: #f6f6f6; padding: 12px; border: 1px solid #ddd;\">"+esc(report_text)+"</pre>") if report_text else ""}
</body>
</html>
"""
    (outdir / "report.html").write_text(html, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None, help=f"Optional convenience model key: {', '.join(sorted(MODEL_SPECS))}")
    ap.add_argument("--server", default="127.0.0.1:8000")
    ap.add_argument("--mock", action="store_true", help="Run without a live ComfyUI server (deterministic output).")
    ap.add_argument("--t2i-workflow", default=None, help="Path to a ComfyUI T2I workflow JSON (required if --model not provided).")
    ap.add_argument("--i2i-workflow", default=None, help="Path to a ComfyUI I2I/inpaint workflow JSON (required if --model not provided).")
    ap.add_argument("--bindings", default="experiments/iterate_t2i/workflow_bindings_default.json")
    ap.add_argument("--unet", default=None, help="Optional UNet filename override.")
    ap.add_argument("--clip", default=None, help="Optional CLIP filename override.")
    ap.add_argument("--vae", default=None, help="Optional VAE filename override.")
    ap.add_argument("--tile-size", type=int, default=512)
    ap.add_argument("--pad", type=int, default=128)
    ap.add_argument("--mask-blur", type=int, default=8)
    ap.add_argument("--inpaint-region", choices=["full_tile", "interior_only"], default="interior_only")
    ap.add_argument("--border-ring", type=int, default=51)
    ap.add_argument("--inpaint-alpha", type=int, choices=[0, 255], default=0)
    ap.add_argument("--denoise", type=float, default=None, help="Defaults to model spec i2i_denoise when --model is used.")
    ap.add_argument("--steps-t2i", type=int, default=None, help="Defaults to model spec t2i_steps when --model is used.")
    ap.add_argument("--cfg-t2i", type=float, default=None, help="Defaults to model spec t2i_cfg when --model is used.")
    ap.add_argument("--steps-i2i", type=int, default=None, help="Defaults to model spec i2i_steps when --model is used.")
    ap.add_argument("--cfg-i2i", type=float, default=None, help="Defaults to model spec i2i_cfg when --model is used.")
    ap.add_argument("--strip", type=int, default=8)
    ap.add_argument("--crop", type=int, default=128)
    ap.add_argument("--prompt-t2i", default="organic biological texture, intricate veins, microscopic, 8k, sharp focus")
    ap.add_argument("--prompt-i2i", default="Generate the missing center part of this image. Ensure seamless blending. Preserve border consistency.")
    ap.add_argument("--outdir", default=None)
    args = ap.parse_args()

    if args.model:
        spec = get_model_spec(str(args.model))
        t2i_workflow = spec.t2i_workflow
        i2i_workflow = spec.i2i_workflow
        bindings_path = spec.bindings_file or args.bindings
        unet = spec.unet_name
        clip = spec.clip_name
        vae = spec.vae_name
        steps_t2i = args.steps_t2i if args.steps_t2i is not None else spec.t2i_steps
        cfg_t2i = args.cfg_t2i if args.cfg_t2i is not None else spec.t2i_cfg
        steps_i2i = args.steps_i2i if args.steps_i2i is not None else spec.i2i_steps
        cfg_i2i = args.cfg_i2i if args.cfg_i2i is not None else spec.i2i_cfg
        denoise = args.denoise if args.denoise is not None else spec.i2i_denoise
        model_label = spec.key
    else:
        if not args.t2i_workflow or not args.i2i_workflow:
            raise SystemExit("Provide --model <key> or both --t2i-workflow and --i2i-workflow.")
        t2i_workflow = str(args.t2i_workflow)
        i2i_workflow = str(args.i2i_workflow)
        bindings_path = str(args.bindings)
        unet = args.unet
        clip = args.clip
        vae = args.vae
        steps_t2i = args.steps_t2i
        cfg_t2i = args.cfg_t2i
        steps_i2i = args.steps_i2i
        cfg_i2i = args.cfg_i2i
        denoise = (args.denoise if args.denoise is not None else 0.35)
        model_label = "custom"

    outdir = Path(args.outdir) if args.outdir else run_dir(kind=f"benchmark_{model_label}")
    outdir.mkdir(parents=True, exist_ok=True)

    wf_t2i = load_workflow(t2i_workflow)
    wf_i2i = load_workflow(i2i_workflow)
    b_t2i = load_bindings(bindings_path, kind="t2i")
    b_i2i = load_bindings(bindings_path, kind="i2i")

    # 1) Generate L0
    l0 = run_t2i(
        server=str(args.server),
        workflow=wf_t2i,
        bindings=b_t2i,
        prompt=str(args.prompt_t2i),
        steps=steps_t2i,
        cfg=cfg_t2i,
        unet=unet,
        clip=clip,
        vae=vae,
        mock=bool(args.mock),
    )
    if l0.size != (int(args.tile_size), int(args.tile_size)):
        l0 = l0.resize((int(args.tile_size), int(args.tile_size)), Image.Resampling.LANCZOS)
    (outdir / "level_0.png").write_bytes(_img_bytes_png(l0))

    # 2) Generate L1 tiles in deterministic order, using already generated neighbors for context.
    tiles: Dict[Tuple[int, int], Image.Image] = {}
    tmp_ctx = outdir / "_tmp_ctx.png"
    tmp_mask = outdir / "_tmp_mask.png"

    for y in (0, 1):
        for x in (0, 1):
            center_seed = _quadrant_from_parent(l0, tile_size=int(args.tile_size), x=x, y=y)
            neighbors: Dict[Tuple[int, int], Image.Image] = {}
            for dx, dy in ((-1, 0), (0, -1), (-1, -1), (1, 0), (0, 1), (1, 1), (1, -1), (-1, 1)):
                nx, ny = x + dx, y + dy
                if (nx, ny) in tiles:
                    neighbors[(dx, dy)] = tiles[(nx, ny)]

            canvas, mask = _build_canvas_and_mask(
                tile_size=int(args.tile_size),
                pad=int(args.pad),
                center_tile=center_seed,
                neighbors=neighbors,
                inpaint_region=str(args.inpaint_region),
                border_ring=int(args.border_ring),
                mask_blur=int(args.mask_blur),
                inpaint_alpha=int(args.inpaint_alpha),
            )

            canvas.save(tmp_ctx)
            mask.save(tmp_mask)

            out = run_i2i(
                server=str(args.server),
                workflow=wf_i2i,
                bindings=b_i2i,
                ctx_path=tmp_ctx,
                mask_path=tmp_mask,
                prompt=str(args.prompt_i2i),
                denoise=float(denoise),
                steps=steps_i2i,
                cfg=cfg_i2i,
                unet=unet,
                clip=clip,
                vae=vae,
                mock=bool(args.mock),
            )

            if out.size != (int(args.tile_size), int(args.tile_size)):
                out = out.resize((int(args.tile_size), int(args.tile_size)), Image.Resampling.LANCZOS)
            tiles[(x, y)] = out

    # 3) Save tiles + stitched + seam crop + metrics
    tl, tr, bl, br = tiles[(0, 0)], tiles[(1, 0)], tiles[(0, 1)], tiles[(1, 1)]
    for (x, y), img in tiles.items():
        img.save(outdir / f"l1_{x}_{y}.png")

    stitched = _stitch_quad(tl, tr, bl, br)
    stitched.save(outdir / "level_1_center.png")

    crop = int(args.crop)
    ts = int(args.tile_size)
    seam_crop = stitched.crop((ts - crop // 2, ts - crop // 2, ts + crop // 2, ts + crop // 2))
    seam_detail = seam_crop.resize((512, 512), Image.Resampling.NEAREST)
    seam_detail.save(outdir / "level_1_seam_detail.png")

    metrics = _seam_metrics_for_quad(tl, tr, bl, br, strip=int(args.strip))

    summary = {
        "model": model_label,
        "timestamp": time.strftime("%Y%m%d_%H%M%S"),
        "artifacts_dir": str(outdir),
        "metrics": metrics,
        "vlm": None,
    }
    (outdir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    _write_report(outdir, model=model_label, metrics=metrics, vlm=None)

    # Cleanup temps
    for p in (tmp_ctx, tmp_mask):
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass

    print(str(outdir))
    return 0


def _img_bytes_png(img: Image.Image) -> bytes:
    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


if __name__ == "__main__":
    raise SystemExit(main())
