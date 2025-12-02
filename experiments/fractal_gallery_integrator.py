import argparse
import asyncio
import json
import math
import os
import sys
import time
from typing import Dict, List, Tuple

import numpy as np
from PIL import Image

# Match the gallery setup: disable numba caching and pin cache dir
os.environ["NUMBA_DISABLE_CACHING"] = "1"
os.environ.setdefault("NUMBA_CACHE_DIR", os.path.join(os.getcwd(), ".numba_cache"))
# Force single-threaded runs for timing consistency
os.environ.setdefault("NUMBA_NUM_THREADS", "1")

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from experiments.fractal_gallery import GALLERY_ITEMS  # noqa: E402
from backend.fractal_renderer import FractalShadesRenderer, fs  # noqa: E402
from backend.tools.analyze_image import analyze_images  # noqa: E402

INTEGRATOR_ROOT = os.path.join("artifacts", "gallery_integrator")
ORIGINAL_DIR = os.path.join(INTEGRATOR_ROOT, "originals")
TILE_DIR = os.path.join(INTEGRATOR_ROOT, "tiles")
COMPOSITE_DIR = os.path.join(INTEGRATOR_ROOT, "recomposed")
DOWNSCALE_DIR = os.path.join(INTEGRATOR_ROOT, "downscaled")
SUMMARY_PATH = os.path.join(INTEGRATOR_ROOT, "integration_summary.json")

DEFAULT_MODEL = "qwen/qwen3-vl-8b-instruct"

TILE_ORDER = [
    ("nw", "top-left"),
    ("ne", "top-right"),
    ("sw", "bottom-left"),
    ("se", "bottom-right"),
]


def ensure_dirs() -> None:
    for d in [INTEGRATOR_ROOT, ORIGINAL_DIR, TILE_DIR, COMPOSITE_DIR, DOWNSCALE_DIR]:
        os.makedirs(d, exist_ok=True)


def split_into_quads(img: Image.Image) -> Dict[str, Image.Image]:
    """Split an image into four quadrants, keeping any odd trailing row/column on the eastern/southern tiles."""
    w, h = img.size
    mid_x, mid_y = w // 2, h // 2
    boxes = {
        "nw": (0, 0, mid_x, mid_y),
        "ne": (mid_x, 0, w, mid_y),
        "sw": (0, mid_y, mid_x, h),
        "se": (mid_x, mid_y, w, h),
    }
    return {k: img.crop(v) for k, v in boxes.items()}


def composite_from_tiles(tiles: Dict[str, Image.Image], size: Tuple[int, int], mode: str) -> Image.Image:
    """Reassemble tiles into a full-size image to emulate the quad tile stitch."""
    out = Image.new(mode, size)
    mid_x, mid_y = size[0] // 2, size[1] // 2
    positions = {
        "nw": (0, 0),
        "ne": (mid_x, 0),
        "sw": (0, mid_y),
        "se": (mid_x, mid_y),
    }
    for key, tile in tiles.items():
        out.paste(tile, positions[key])
    return out


def compare_images(a: Image.Image, b: Image.Image) -> Dict[str, float]:
    """Return simple difference metrics between two images of identical size."""
    if a.size != b.size:
        raise ValueError(f"Image sizes differ: {a.size} vs {b.size}")
    a_arr = np.asarray(a, dtype=np.float32)
    b_arr = np.asarray(b, dtype=np.float32)
    diff = a_arr - b_arr
    mae = float(np.mean(np.abs(diff)))
    rmse = float(math.sqrt(np.mean(diff ** 2)))
    max_diff = int(np.max(np.abs(diff)))
    return {"mae": mae, "rmse": rmse, "max_diff": max_diff}


def save_tiles(stem: str, tiles: Dict[str, Image.Image]) -> List[str]:
    paths = []
    for key, _ in TILE_ORDER:
        path = os.path.join(TILE_DIR, f"{stem}_tile_{key}.png")
        tiles[key].save(path)
        paths.append(path)
    return paths


def save_recompositions(stem: str, composite: Image.Image, downscale_factor: float = 0.5) -> Tuple[str, str]:
    composite_path = os.path.join(COMPOSITE_DIR, f"{stem}_recomposed.png")
    composite.save(composite_path)

    new_w = max(1, int(composite.width * downscale_factor))
    new_h = max(1, int(composite.height * downscale_factor))
    downscaled = composite.resize((new_w, new_h), Image.Resampling.LANCZOS)
    downscale_path = os.path.join(DOWNSCALE_DIR, f"{stem}_recomposed_downscaled.png")
    downscaled.save(downscale_path)
    return composite_path, downscale_path


def build_prompt(item: Dict[str, str], metrics: Dict[str, float]) -> str:
    return (
        "You are QA for a quad-tile renderer. You get 5 images: "
        "Image #1 is the reference fractal. Images #2-#5 are the quadrants "
        "in order: top-left, top-right, bottom-left, bottom-right. "
        "Look for seams, color mismatches, or misalignment when the tiles are reassembled. "
        "Give a brief verdict with a 0-10 confidence score that the tiles recreate the reference, "
        "and note any visible issues. "
        f"Context: {item['title']} – {item.get('desc', '')}. "
        f"Numeric checks (for reference only): rmse={metrics['rmse']:.4f}, mae={metrics['mae']:.4f}, max_diff={metrics['max_diff']}."
    )


async def run_llm_analysis(image_paths: List[str], prompt: str, model: str) -> str:
    return await analyze_images(image_paths, prompt, model)


def render_item(renderer: FractalShadesRenderer, item: Dict, supersampling: str) -> Tuple[str, float]:
    t0 = time.perf_counter()
    path = renderer.render(filename=item["filename"], supersampling=supersampling, **item["params"])
    elapsed = time.perf_counter() - t0
    return path, elapsed


def main() -> None:
    parser = argparse.ArgumentParser(description="Fractal Gallery Integrator (quad tile + analysis).")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="OpenRouter model slug for image analysis.")
    parser.add_argument("--supersampling", default="2x2", help="Supersampling setting forwarded to the renderer.")
    parser.add_argument("--skip-llm", action="store_true", help="Skip LLM analysis even if an API key is present.")
    parser.add_argument("--limit", type=int, default=None, help="Render only the first N gallery items.")
    parser.add_argument("--start", type=int, default=0, help="Start index (0-based) within the gallery list.")
    parser.add_argument("--verbosity", type=int, default=0, help="Renderer verbosity.")
    args = parser.parse_args()

    ensure_dirs()

    renderer = FractalShadesRenderer(ORIGINAL_DIR, verbosity=args.verbosity)
    # Override the renderer default to keep runs single-threaded for timing
    fs.settings.enable_multithreading = False

    results = []
    openrouter_key = os.getenv("OPENROUTER_API_KEY")

    processed = 0
    for idx, item in enumerate(GALLERY_ITEMS):
        if idx < args.start:
            continue
        if args.limit is not None and processed >= args.limit:
            break
        processed += 1

        print(f"\n[{idx + 1}/{len(GALLERY_ITEMS)}] Rendering {item['title']} (single-threaded)...")
        full_path, duration = render_item(renderer, item, args.supersampling)
        stem, _ = os.path.splitext(os.path.basename(full_path))

        with Image.open(full_path) as base_img:
            base_rgb = base_img.convert("RGB")
            tiles = split_into_quads(base_rgb)
            tile_paths = save_tiles(stem, tiles)

            composite = composite_from_tiles(tiles, base_rgb.size, base_rgb.mode)
            composite_path, downscale_path = save_recompositions(stem, composite)

            composite_metrics = compare_images(base_rgb, composite)
            with Image.open(downscale_path) as down_img:
                down_rgb = down_img.convert("RGB")
                downscaled_metrics = compare_images(
                    base_rgb.resize(down_rgb.size, Image.Resampling.LANCZOS),
                    down_rgb
                )

        llm_report = None
        if openrouter_key and not args.skip_llm:
            prompt = build_prompt(item, composite_metrics)
            try:
                llm_report = asyncio.run(run_llm_analysis([full_path, *tile_paths], prompt, args.model))
            except Exception as e:
                llm_report = f"LLM analysis failed: {e}"
        elif not openrouter_key and not args.skip_llm:
            llm_report = "Skipped: OPENROUTER_API_KEY not set."

        item_result = {
            "title": item["title"],
            "filename": item["filename"],
            "duration_s": duration,
            "paths": {
                "full": full_path,
                "tiles": tile_paths,
                "composite": composite_path,
                "downscaled": downscale_path,
            },
            "metrics": {
                "composite": composite_metrics,
                "downscaled": downscaled_metrics,
            },
            "llm_report": llm_report,
        }
        results.append(item_result)

        print(
            f"Done in {duration:.2f}s | RMSE={composite_metrics['rmse']:.4f}, "
            f"MAE={composite_metrics['mae']:.4f}, MaxDiff={composite_metrics['max_diff']}"
        )
        if llm_report:
            print(f"LLM verdict: {llm_report}")

    with open(SUMMARY_PATH, "w") as f:
        json.dump(results, f, indent=2)

    total_time = sum(r["duration_s"] for r in results)
    print(f"\nIntegration run complete. Rendered {len(results)} items in {total_time:.2f}s.")
    print(f"Summary saved to {SUMMARY_PATH}")


if __name__ == "__main__":
    main()
