import os
import sys
import json
import shutil
import argparse
from pathlib import Path
from PIL import Image

# Add repo root and backend to sys.path
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "backend"))

from backend import render_tiles
from backend.renderer_utils import load_renderer


DATASET_ID = "generative_infinity_zoom_v9"
DATASET_DIR = Path("datasets") / DATASET_ID


def setup_dataset():
    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    if not (DATASET_DIR / "config.json").exists():
        print("Error: config.json missing.")
        sys.exit(1)


def stitch_center_quad_l2():
    tiles = {}
    for x in [1, 2]:
        for y in [1, 2]:
            p = DATASET_DIR / "2" / str(x) / f"{y}.webp"
            if not p.exists():
                return None
            tiles[(x, y)] = Image.open(p).convert("RGB")

    ts = 512
    canvas = Image.new("RGB", (ts * 2, ts * 2))
    canvas.paste(tiles[(1, 1)], (0, 0))
    canvas.paste(tiles[(2, 1)], (ts, 0))
    canvas.paste(tiles[(1, 2)], (0, ts))
    canvas.paste(tiles[(2, 2)], (ts, ts))
    return canvas


def generate_html_report(report_text, score, img_stitched, img_crop):
    html = f"""
    <html>
    <head><title>Generative Zoom V9 Analysis</title></head>
    <body style="font-family: sans-serif; max-width: 800px; margin: 0 auto; padding: 20px;">
        <h1>Generative Zoom V9 Analysis</h1>
        <p><strong>Experiment:</strong> Border-ring preserved + interior inpaint (512px tiles).</p>
        <h2>Score: <span style="color: {'green' if score >= 8 else 'red'}">{score}/10</span></h2>
        <h3>1. Stitched Center (Full)</h3>
        <img src="{img_stitched}" style="max-width: 100%; border: 1px solid #ccc;">
        <h3>2. Seam Detail (Blown Up)</h3>
        <img src="{img_crop}" style="max-width: 100%; border: 1px solid #ccc;">
        <h3>3. AI Critique</h3>
        <pre style="white-space: pre-wrap; background: #f0f0f0; padding: 10px;">{report_text}</pre>
    </body>
    </html>
    """
    out_dir = Path("artifacts/gen_zoom_v9_debug")
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "report.html", "w") as f:
        f.write(html)
    print("\n[Report] Generated report.html in artifacts/gen_zoom_v9_debug/")


def run_test(args):
    setup_dataset()
    if args.clean:
        shutil.rmtree(DATASET_DIR / "0", ignore_errors=True)
        shutil.rmtree(DATASET_DIR / "1", ignore_errors=True)
        shutil.rmtree(DATASET_DIR / "2", ignore_errors=True)

    print("\n--- Step 1: Rendering Level 0 (Root) ---")
    with open(DATASET_DIR / "config.json") as f:
        conf = json.load(f)
    renderer = load_renderer(conf["renderer"], conf["tile_size"], conf["renderer_args"], dataset_path=str(DATASET_DIR))
    render_tiles.render_tasks(renderer, [(0, 0, 0, str(DATASET_DIR))], num_workers=0)

    print("\n--- Step 2: Rendering Level 1 (Children) ---")
    tasks_l1 = [(1, x, y, str(DATASET_DIR)) for x in [0, 1] for y in [0, 1]]
    render_tiles.render_tasks(renderer, tasks_l1, num_workers=0)

    print("\n--- Step 3: Rendering Level 2 (Center Quad) ---")
    # Render in an order that ensures neighbors exist when possible (no same-level deps enforced).
    tasks_l2 = [
        (2, 1, 1, str(DATASET_DIR)),
        (2, 2, 1, str(DATASET_DIR)),
        (2, 1, 2, str(DATASET_DIR)),
        (2, 2, 2, str(DATASET_DIR)),
    ]
    render_tiles.render_tasks(renderer, tasks_l2, num_workers=0)

    print("--- Step 4: Analysis ---")
    stitched_l2 = stitch_center_quad_l2()
    if not stitched_l2:
        print("Failed to stitch L2 center.")
        return

    debug_dir = Path("artifacts/gen_zoom_v9_debug")
    debug_dir.mkdir(parents=True, exist_ok=True)
    stitched_l2.save(debug_dir / "level_2_center.png")

    seam_crop = stitched_l2.crop((448, 448, 576, 576))
    seam_crop_lg = seam_crop.resize((512, 512), Image.Resampling.NEAREST)
    seam_crop_lg.save(debug_dir / "level_2_seam_detail.png")

    if os.environ.get("OPENROUTER_API_KEY"):
        from backend.tools.analyze_image import analyze_images
        import asyncio
        import re

        print("\nRunning AI VLM Analysis on L2 Seam Detail...")
        prompt = (
            "This is a magnified view of the intersection where 4 generated image tiles meet (Level 2 Deep Zoom). "
            "Rate the quality of the stitching on a scale of 0 to 10 (10 = Perfect, Seamless). "
            "Provide the score as 'SCORE: X/10'. "
            "Then explain your reasoning. Look for sharp lines, color discontinuities, or broken textures."
        )
        report = asyncio.run(analyze_images([str(debug_dir / 'level_2_seam_detail.png')], prompt))
        print("\n--- VLM Report ---")
        print(report)

        score = 0.0
        match = re.search(r"SCORE:\\s*(\\d+(\\.\\d+)?)/10", report, re.IGNORECASE)
        if match:
            score = float(match.group(1))

        generate_html_report(report, score, "level_2_center.png", "level_2_seam_detail.png")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()

    print("Running in REAL mode.")
    run_test(args)


if __name__ == "__main__":
    main()
