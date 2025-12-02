import argparse
import asyncio
import json
import math
import os
import sys
import time
from decimal import Decimal, getcontext
from typing import Dict, List, Tuple, Any

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
SUMMARY_PATH = os.path.join(INTEGRATOR_ROOT, "integration_summary.json")
REPORT_PATH = os.path.join(INTEGRATOR_ROOT, "report.html")

DEFAULT_MODEL = "qwen/qwen3-vl-8b-instruct"

# Order: NW, NE, SW, SE
TILE_ORDER = ["nw", "ne", "sw", "se"]


def ensure_dirs() -> None:
    for d in [INTEGRATOR_ROOT, ORIGINAL_DIR, TILE_DIR, COMPOSITE_DIR]:
        os.makedirs(d, exist_ok=True)


def get_quadrant_params(item_params: Dict[str, Any], quad_key: str) -> Dict[str, Any]:
    """
    Calculates the parameters (x, y, dx, nx) for a specific quadrant.
    Moves the camera to the center of the quadrant and zooms in by 2x.
    """
    # Setup precision
    prec = item_params.get("precision", 15)
    getcontext().prec = prec + 10
    
    x_str = str(item_params.get("x", "0.0"))
    y_str = str(item_params.get("y", "0.0"))
    dx_str = str(item_params.get("dx", "1.0"))
    
    x = Decimal(x_str)
    y = Decimal(y_str)
    dx = Decimal(dx_str)
    
    nx = item_params.get("nx", 800)
    ratio = float(item_params.get("xy_ratio", 1.0))
    theta_deg = float(item_params.get("theta_deg", 0.0))
    skew = item_params.get("skew_params", None)
    
    # Target tile params: 2x zoom means dx is halved
    tile_dx = dx / Decimal(2)
    tile_nx = nx // 2
    
    # Screen space offsets for the quadrants (u, v)
    # u: horizontal (right), v: vertical (up). 
    # Range [-0.5, 0.5] corresponds to full width/height (normalized).
    # Quadrant centers are at +/- 0.25.
    
    qs = {
        "nw": (-0.25, 0.25),
        "ne": (0.25, 0.25),
        "sw": (-0.25, -0.25),
        "se": (0.25, -0.25)
    }
    
    u_scale, v_scale = qs[quad_key]
    
    # Adjust v for aspect ratio.
    # If ratio=2.0, height is half width. The vertical offset in 'width units' is halved.
    v_scale = v_scale / ratio
    
    u = Decimal(u_scale)
    v = Decimal(v_scale)
    
    if skew:
        s00 = Decimal(str(skew.get("skew_00", 1.0)))
        s01 = Decimal(str(skew.get("skew_01", 0.0)))
        s10 = Decimal(str(skew.get("skew_10", 0.0)))
        s11 = Decimal(str(skew.get("skew_11", 1.0)))
        
        d_re = dx * (s00 * u + s01 * v)
        d_im = dx * (s10 * u + s11 * v)
    else:
        # Standard Rotation
        theta_rad = Decimal(math.radians(theta_deg))
        cos_t = Decimal(math.cos(theta_rad))
        sin_t = Decimal(math.sin(theta_rad))
        
        d_re = dx * (u * cos_t - v * sin_t)
        d_im = dx * (u * sin_t + v * cos_t)
        
    tile_x = x + d_re
    tile_y = y + d_im
    
    new_params = item_params.copy()
    new_params["x"] = f"{tile_x:.{prec}f}"
    new_params["y"] = f"{tile_y:.{prec}f}"
    new_params["dx"] = f"{tile_dx:.{prec}e}"
    new_params["nx"] = tile_nx
    
    # Ensure we don't pass conflicting args if they were in params (e.g. if params had fixed 'nx')
    # (Already handled by overwriting)
    
    return new_params


def composite_from_tiles(tiles: Dict[str, Image.Image], full_nx: int, xy_ratio: float) -> Image.Image:
    """Reassemble tiles into a full-size image."""
    full_h = int(full_nx / xy_ratio)
    mid_x = full_nx // 2
    mid_y = full_h // 2
    
    # Check if full_h is odd. If so, alignment might be tricky.
    # We'll assume even for now as most galleries are 800px.
    
    out = Image.new("RGB", (full_nx, full_h))
    
    # The tiles should be roughly (mid_x, mid_y) in size.
    # Standard layout:
    # NW | NE
    # -------
    # SW | SE
    
    # Paste positions
    # NW: 0, 0
    # NE: mid_x, 0
    # SW: 0, mid_y
    # SE: mid_x, mid_y
    
    positions = {
        "nw": (0, 0),
        "ne": (mid_x, 0),
        "sw": (0, mid_y),
        "se": (mid_x, mid_y),
    }
    
    for key, tile in tiles.items():
        # Resize if necessary (e.g. if rounding errors in nx/ratio caused 1px diff)
        # But usually we render them at calculated size.
        out.paste(tile, positions[key])
        
    return out


def compare_images(ref: Image.Image, composite: Image.Image) -> Dict[str, float]:
    """Return simple difference metrics."""
    # Ensure sizes match
    if ref.size != composite.size:
        # If off by 1 pixel due to rounding, crop/resize ref to match composite
        # This can happen with odd aspect ratios
        print(f"Warning: Size mismatch Ref {ref.size} vs Composite {composite.size}. Resizing Ref.")
        ref = ref.resize(composite.size, Image.Resampling.LANCZOS)
        
    a_arr = np.asarray(ref, dtype=np.float32)
    b_arr = np.asarray(composite, dtype=np.float32)
    diff = a_arr - b_arr
    
    mae = float(np.mean(np.abs(diff)))
    rmse = float(math.sqrt(np.mean(diff ** 2)))
    max_diff = int(np.max(np.abs(diff)))
    
    return {"mae": mae, "rmse": rmse, "max_diff": max_diff}


def build_prompt(item: Dict[str, str], metrics: Dict[str, float]) -> str:
    return (
        "You are QA for a quad-tile renderer. You are comparing a 'Reference' image "
        "rendered in one pass vs a 'Composite' image stitched from 4 independently rendered tiles. "
        "Image #1 is the Reference. Image #2 is the Composite. "
        "Look for seams (cross shape in middle), color shifts, or misalignment. "
        "Give a verdict (0-10) on how perfectly the tiles recreate the reference. "
        f"Context: {item['title']}. "
        f"Metrics: RMSE={metrics['rmse']:.2f}, MaxDiff={metrics['max_diff']}."
    )


async def run_llm_analysis(image_paths: List[str], prompt: str, model: str) -> str:
    return await analyze_images(image_paths, prompt, model)


def get_relative_path(path: str, start: str) -> str:
    try:
        rel = os.path.relpath(path, start)
        return rel
    except ValueError:
        return path


def generate_html_report(json_path: str, report_path: str, artifacts_dir: str) -> None:
    if not os.path.exists(json_path):
        print(f"Error: {json_path} not found.")
        return

    with open(json_path, "r") as f:
        data = json.load(f)

    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Fractal Integration Report</title>
        <style>
            body { font-family: sans-serif; margin: 20px; background: #f4f4f4; }
            .container { max_width: 1200px; margin: 0 auto; }
            .card { background: white; margin-bottom: 30px; padding: 20px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }
            h1 { text-align: center; color: #333; }
            h2 { margin-top: 0; color: #444; border-bottom: 2px solid #eee; padding-bottom: 10px; }
            .metrics { display: flex; gap: 20px; margin-bottom: 15px; font-weight: bold; color: #555; }
            .metric { background: #eee; padding: 5px 10px; border-radius: 4px; }
            .images { display: flex; gap: 20px; justify-content: center; flex-wrap: wrap; }
            .image-box { text-align: center; }
            img { max-width: 100%; height: auto; border: 1px solid #ddd; border-radius: 4px; max-height: 400px; }
            .llm-report { margin-top: 15px; background: #f9f9f9; padding: 15px; border-left: 4px solid #007bff; white-space: pre-wrap; }
            .pass { color: green; }
            .fail { color: red; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Fractal Integration Test Report</h1>
    """

    for item in data:
        title = item.get("title", "Unknown")
        metrics = item.get("metrics", {})
        rmse = metrics.get("rmse", -1)
        max_diff = metrics.get("max_diff", -1)
        llm_report = item.get("llm_report", "No report")
        paths = item.get("paths", {})
        
        ref_path = paths.get("ref")
        comp_path = paths.get("composite")
        
        # Make paths relative to the report file
        ref_rel = get_relative_path(ref_path, artifacts_dir) if ref_path else ""
        comp_rel = get_relative_path(comp_path, artifacts_dir) if comp_path else ""

        # Simple heuristic for status color
        status_class = "pass" if rmse < 50 else "fail" # Arbitrary threshold based on recent runs

        html += f"""
            <div class="card">
                <h2>{title}</h2>
                <div class="metrics">
                    <span class="metric {status_class}">RMSE: {rmse:.4f}</span>
                    <span class="metric">MaxDiff: {max_diff}</span>
                </div>
                <div class="images">
                    <div class="image-box">
                        <h3>Reference</h3>
                        <a href="{ref_rel}" target="_blank"><img src="{ref_rel}" alt="Reference"></a>
                    </div>
                    <div class="image-box">
                        <h3>Composite</h3>
                        <a href="{comp_rel}" target="_blank"><img src="{comp_rel}" alt="Composite"></a>
                    </div>
                </div>
                <div class="llm-report"><strong>LLM Analysis:</strong><br>{llm_report}</div>
            </div>
        """

    html += """
        </div>
    </body>
    </html>
    """

    with open(report_path, "w") as f:
        f.write(html)
    
    print(f"Report generated at: {report_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fractal Gallery Integrator (Independent Tile Test).")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="OpenRouter model slug.")
    parser.add_argument("--supersampling", default="2x2", help="Supersampling setting.")
    parser.add_argument("--skip-llm", action="store_true", help="Skip LLM.")
    parser.add_argument("--limit", type=int, default=None, help="Limit items.")
    parser.add_argument("--start", type=int, default=0, help="Start index.")
    parser.add_argument("--verbosity", type=int, default=0, help="Verbosity.")
    parser.add_argument("--no-report", action="store_true", help="Disable HTML report generation.")
    args = parser.parse_args()

    ensure_dirs()

    # Separate renderers for full vs tiles (to avoid directory conflict/race conditions if parallelized later)
    renderer = FractalShadesRenderer(ORIGINAL_DIR, verbosity=args.verbosity)
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

        title = item["title"]
        print(f"\n[{idx + 1}/{len(GALLERY_ITEMS)}] Processing {title}...")
        
        # 1. Render Reference (Full)
        t0 = time.perf_counter()
        ref_path = renderer.render(filename=item["filename"], supersampling=args.supersampling, **item["params"])
        t_ref = time.perf_counter() - t0
        print(f"  Reference rendered in {t_ref:.2f}s")
        
        # 2. Render 4 Tiles Independently
        tile_paths = []
        tiles_obj = {}
        t_tiles = 0
        
        stem, _ = os.path.splitext(os.path.basename(ref_path))
        
        print("  Rendering tiles:", end=" ", flush=True)
        for q in TILE_ORDER:
            print(q, end=".. ", flush=True)
            q_params = get_quadrant_params(item["params"], q)
            q_filename = f"{stem}_{q}.png"
            
            # Use TILE_DIR
            # We need to temporarily point the renderer or move the file
            # FractalShadesRenderer takes output_dir in init. 
            # Let's just render to ORIGINAL_DIR then move.
            
            t_start = time.perf_counter()
            # We must override filename to avoid overwrite
            path = renderer.render(filename=q_filename, supersampling=args.supersampling, **q_params)
            t_tiles += (time.perf_counter() - t_start)
            
            # Move to TILE_DIR
            final_tile_path = os.path.join(TILE_DIR, q_filename)
            if os.path.exists(final_tile_path):
                os.remove(final_tile_path)
            os.rename(path, final_tile_path)
            
            tile_paths.append(final_tile_path)
            tiles_obj[q] = Image.open(final_tile_path).convert("RGB")
            
        print(f"Done ({t_tiles:.2f}s).")
        
        # 3. Composite
        with Image.open(ref_path) as ref_img:
            ref_rgb = ref_img.convert("RGB")
            ratio = float(item["params"].get("xy_ratio", 1.0))
            nx = item["params"].get("nx", 800)
            
            composite = composite_from_tiles(tiles_obj, nx, ratio)
            composite_path = os.path.join(COMPOSITE_DIR, f"{stem}_composite.png")
            composite.save(composite_path)
            
            # 4. Compare
            metrics = compare_images(ref_rgb, composite)
            print(f"  Metrics: RMSE={metrics['rmse']:.4f}, MaxDiff={metrics['max_diff']}")
            
            # Clean up images
            ref_rgb.close()
            for t in tiles_obj.values(): t.close()

        # 5. LLM
        llm_report = None
        if openrouter_key and not args.skip_llm:
            prompt = build_prompt(item, metrics)
            try:
                # Analyze Ref and Composite
                llm_report = asyncio.run(run_llm_analysis([ref_path, composite_path], prompt, args.model))
            except Exception as e:
                llm_report = f"LLM analysis failed: {e}"
        elif not openrouter_key and not args.skip_llm:
            llm_report = "Skipped: No API Key."
            
        if llm_report:
            print(f"  LLM: {llm_report}")
            
        results.append({
            "title": title,
            "metrics": metrics,
            "llm_report": llm_report,
            "paths": {"ref": ref_path, "composite": composite_path, "tiles": tile_paths}
        })

    with open(SUMMARY_PATH, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nCompleted {len(results)} items. Summary at {SUMMARY_PATH}")
    
    if not args.no_report:
        generate_html_report(SUMMARY_PATH, REPORT_PATH, INTEGRATOR_ROOT)

if __name__ == "__main__":
    main()
