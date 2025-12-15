import argparse
import io
import json
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageFilter

# Ensure repo root is importable
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.comfyui_client import ComfyUIClient, first_image_ref_from_history  # noqa: E402


@dataclass(frozen=True)
class CropSpec:
    x: int
    y: int
    width: int
    height: int


def _load_workflow(path: Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _get_crop_spec(workflow: Dict) -> CropSpec:
    node = workflow.get("103") or {}
    inputs = node.get("inputs") or {}
    return CropSpec(
        x=int(inputs.get("x", 0)),
        y=int(inputs.get("y", 0)),
        width=int(inputs.get("width", 512)),
        height=int(inputs.get("height", 512)),
    )


def _guess_canvas_size(crop: CropSpec) -> Tuple[int, int]:
    # Our workflows use symmetric padding: crop at (pad, pad) from a square canvas.
    # Use (width+2*pad, height+2*pad).
    return crop.width + 2 * crop.x, crop.height + 2 * crop.y


def _font(size: int) -> ImageFont.ImageFont:
    # Try common macOS font paths; fall back to default.
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/Library/Fonts/Arial.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size=size)
            except Exception:
                pass
    return ImageFont.load_default()


def _make_ctx_image(canvas_w: int, canvas_h: int, crop: CropSpec, digit: str) -> Image.Image:
    img = Image.new("RGB", (canvas_w, canvas_h), color=(190, 190, 190))
    d = ImageDraw.Draw(img)

    # Mark the crop region with a subtle frame so we can visually debug alignment.
    d.rectangle(
        [crop.x, crop.y, crop.x + crop.width - 1, crop.y + crop.height - 1],
        outline=(80, 80, 80),
        width=2,
    )

    # Add a small orientation marker in the canvas top-left.
    d.rectangle([0, 0, 20, 20], fill=(255, 0, 0))

    # Put a big digit inside the crop region.
    font = _font(size=max(48, crop.width // 2))
    text = str(digit)
    bbox = d.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    cx = crop.x + crop.width // 2 - tw // 2
    cy = crop.y + crop.height // 2 - th // 2
    d.text((cx, cy), text, fill=(0, 0, 0), font=font)

    return img


def _make_mask_image(
    canvas_w: int,
    canvas_h: int,
    crop: CropSpec,
    *,
    inpaint_rect_in_crop: Tuple[int, int, int, int],
    alpha_inpaint: int,
    alpha_else: int,
    blur_radius: int,
) -> Image.Image:
    """
    Make an RGBA mask image so ComfyUI LoadImage outputs a mask from the alpha channel.
    We only use alpha; RGB can be black.
    """
    mask = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, alpha_else))
    d = ImageDraw.Draw(mask)

    # inpaint_rect_in_crop is in output/crop coordinates; map to canvas.
    l, t, r, b = inpaint_rect_in_crop
    canvas_rect = [crop.x + l, crop.y + t, crop.x + r, crop.y + b]
    d.rectangle(canvas_rect, fill=(0, 0, 0, alpha_inpaint))

    if blur_radius > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    return mask


def _crop_ctx_to_output(ctx: Image.Image, crop: CropSpec) -> Image.Image:
    return ctx.crop((crop.x, crop.y, crop.x + crop.width, crop.y + crop.height))


def _mean_rgb(img: Image.Image, rect: Tuple[int, int, int, int]) -> Tuple[float, float, float]:
    l, t, r, b = rect
    region = img.crop((l, t, r, b)).convert("RGB")
    pixels = list(region.getdata())
    if not pixels:
        return (0.0, 0.0, 0.0)
    rs = sum(p[0] for p in pixels)
    gs = sum(p[1] for p in pixels)
    bs = sum(p[2] for p in pixels)
    n = len(pixels)
    return (rs / n, gs / n, bs / n)


def _mean_abs_diff(a: Image.Image, b: Image.Image, rect: Tuple[int, int, int, int]) -> float:
    l, t, r, bottom = rect
    ra = a.crop((l, t, r, bottom)).convert("RGB")
    rb = b.crop((l, t, r, bottom)).convert("RGB")
    diff = ImageChops.difference(ra, rb)
    pixels = list(diff.getdata())
    if not pixels:
        return 0.0
    return sum((p[0] + p[1] + p[2]) / 3.0 for p in pixels) / len(pixels)


def _run(
    client: ComfyUIClient,
    workflow: Dict,
    *,
    ctx_path: Path,
    mask_path: Path,
    prompt_text: str,
    denoise: float,
    steps: int,
    cfg: float,
    out_path: Path,
    save_node: str = "9",
) -> None:
    wf = json.loads(json.dumps(workflow))

    # Upload ctx/mask and patch LoadImage nodes (100/101)
    ctx_name = client.upload_image(ctx_path)
    mask_name = client.upload_image(mask_path)
    if "100" in wf:
        wf["100"]["inputs"]["image"] = ctx_name
    if "101" in wf:
        wf["101"]["inputs"]["image"] = mask_name

    # Patch prompt node (6) uses "prompt" key in our qwen-image-edit workflows.
    if "6" in wf:
        wf["6"]["inputs"]["prompt"] = prompt_text

    # Patch sampler settings.
    if "3" in wf:
        wf["3"]["inputs"]["seed"] = random.randint(1, 10**14)
        wf["3"]["inputs"]["denoise"] = float(denoise)
        wf["3"]["inputs"]["steps"] = int(steps)
        wf["3"]["inputs"]["cfg"] = float(cfg)

    prompt_id = client.queue_prompt(wf)
    client.wait_for_prompt(prompt_id, timeout_s=1200)
    history = client.get_history(prompt_id)
    data = history.get(prompt_id, {})
    img_ref = first_image_ref_from_history(data, preferred_node=save_node)
    if not img_ref:
        raise RuntimeError(f"No image returned for prompt {prompt_id}")
    raw = client.get_image_data(img_ref)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(raw)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="127.0.0.1:8000")
    ap.add_argument("--workflow", default="experiments/iterate_t2i/workflows/genzoom_inpaint_diffdiff_workflow.json")
    ap.add_argument("--outdir", default="artifacts/diagnostics_inpaint")
    args = ap.parse_args()

    workflow_path = Path(args.workflow)
    if not workflow_path.exists():
        raise SystemExit(f"Workflow not found: {workflow_path}")
    wf = _load_workflow(workflow_path)
    crop = _get_crop_spec(wf)
    canvas_w, canvas_h = _guess_canvas_size(crop)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # Inpaint rect in output coordinates: center square.
    box_size = crop.width // 2
    left = crop.width // 2 - box_size // 2
    top = crop.height // 2 - box_size // 2
    inpaint_rect = (left, top, left + box_size, top + box_size)

    # Diagnostics:
    # 1) Mask polarity test (alpha=0 inpaint) + red fill prompt.
    # 2) Mask polarity inverted (alpha=255 inpaint) + red fill prompt.
    # 3) Prompt+image conditioning test: start with digit 7, ask for 8 (using whichever mask seemed right).

    tests = [
        {
            "name": "mask_alpha0_inpaint_red",
            "digit": "7",
            "alpha_inpaint": 0,
            "alpha_else": 255,
            "prompt": "In the masked region ONLY: fill it with a solid pure red color. Keep everything else unchanged.",
        },
        {
            "name": "mask_alpha255_inpaint_red",
            "digit": "7",
            "alpha_inpaint": 255,
            "alpha_else": 0,
            "prompt": "In the masked region ONLY: fill it with a solid pure red color. Keep everything else unchanged.",
        },
    ]

    # Common sampler settings: strong enough to show the effect but not too slow.
    denoise = 0.9
    steps = 8
    cfg = 6.0
    blur_radius = max(4, crop.width // 32)

    client_id = f"diagnose-{os.getpid()}-{random.randint(1000, 9999)}"
    client = ComfyUIClient(args.server, client_id)
    try:
        results = []
        for t in tests:
            ctx = _make_ctx_image(canvas_w, canvas_h, crop, digit=t["digit"])
            mask = _make_mask_image(
                canvas_w,
                canvas_h,
                crop,
                inpaint_rect_in_crop=inpaint_rect,
                alpha_inpaint=t["alpha_inpaint"],
                alpha_else=t["alpha_else"],
                blur_radius=blur_radius,
            )

            ctx_path = outdir / f"{t['name']}_ctx.png"
            mask_path = outdir / f"{t['name']}_mask.png"
            out_path = outdir / f"{t['name']}_out.png"

            ctx.save(ctx_path)
            mask.save(mask_path)

            t0 = time.perf_counter()
            _run(
                client,
                wf,
                ctx_path=ctx_path,
                mask_path=mask_path,
                prompt_text=t["prompt"],
                denoise=denoise,
                steps=steps,
                cfg=cfg,
                out_path=out_path,
            )
            dt = time.perf_counter() - t0

            out_img = Image.open(io.BytesIO(out_path.read_bytes())).convert("RGB")
            ctx_crop = _crop_ctx_to_output(ctx, crop).convert("RGB")

            mean_in = _mean_rgb(out_img, inpaint_rect)
            mean_outside = _mean_abs_diff(out_img, ctx_crop, (0, 0, crop.width, crop.height))
            results.append((t["name"], dt, mean_in, mean_outside))

        # Decide which polarity produced a "redder" inpaint area.
        def redness(m):
            r, g, b = m
            return r - (g + b) / 2.0

        pick = max(results, key=lambda x: redness(x[2]))[0]

        # 3rd run: digit increment test using the picked polarity.
        alpha_inpaint = 0 if "alpha0" in pick else 255
        alpha_else = 255 if alpha_inpaint == 0 else 0
        ctx = _make_ctx_image(canvas_w, canvas_h, crop, digit="7")
        mask = _make_mask_image(
            canvas_w,
            canvas_h,
            crop,
            inpaint_rect_in_crop=inpaint_rect,
            alpha_inpaint=alpha_inpaint,
            alpha_else=alpha_else,
            blur_radius=blur_radius,
        )
        ctx_path = outdir / "digit_increment_ctx.png"
        mask_path = outdir / "digit_increment_mask.png"
        out_path = outdir / "digit_increment_out.png"
        ctx.save(ctx_path)
        mask.save(mask_path)

        t0 = time.perf_counter()
        _run(
            client,
            wf,
            ctx_path=ctx_path,
            mask_path=mask_path,
            prompt_text="In the masked region ONLY: replace the digit 7 with the digit 8. Keep everything else unchanged.",
            denoise=0.8,
            steps=10,
            cfg=7.0,
            out_path=out_path,
        )
        dt = time.perf_counter() - t0

        summary = {
            "workflow": str(workflow_path),
            "server": args.server,
            "crop": crop.__dict__,
            "canvas": {"w": canvas_w, "h": canvas_h},
            "inpaint_rect": {"l": inpaint_rect[0], "t": inpaint_rect[1], "r": inpaint_rect[2], "b": inpaint_rect[3]},
            "mask_blur_radius": blur_radius,
            "mask_polarity_pick": pick,
            "runs": [
                {"name": n, "seconds": round(s, 2), "mean_rgb_inpaint": [round(v, 1) for v in m], "mean_abs_diff_full": round(d, 2)}
                for (n, s, m, d) in results
            ]
            + [{"name": "digit_increment", "seconds": round(dt, 2)}],
            "outputs_dir": str(outdir),
        }

        (outdir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary, indent=2))
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
