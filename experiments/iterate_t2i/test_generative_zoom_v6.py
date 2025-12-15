import os
import sys
import json
import shutil
import numpy as np
import argparse
from pathlib import Path
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "backend"))

from backend import render_tiles
from backend.renderer_utils import load_renderer
from unittest.mock import MagicMock, patch
import io

class MockComfyUIClientV6:
    def __init__(self, server_address, client_id, **kwargs):
        self.server_address = server_address
        self.client_id = client_id
        self.uploaded_files = {}
        self.last_prompt_type = None
        self.last_input_image = None
        self.last_mask_image = None
        print(f"[MockV6] Initialized for {server_address}")

    def upload_image(self, filepath, **kwargs):
        print(f"[MockV6] Uploading {filepath}")
        name = Path(filepath).name
        self.uploaded_files[name] = filepath
        return name

    def queue_prompt(self, workflow):
        if "100" in workflow:
            ctx_name = workflow["100"]["inputs"].get("image")
            self.last_input_image = self.uploaded_files.get(ctx_name)
            print(f"[MockV6] Detected Context Image: {ctx_name}")
        
        if "101" in workflow:
            mask_name = workflow["101"]["inputs"].get("image")
            self.last_mask_image = self.uploaded_files.get(mask_name)
            print(f"[MockV6] Detected Mask Image: {mask_name}")
            
        if "104" in workflow: # Differential Diffusion
            self.last_prompt_type = "diff_diffusion"
            print("[MockV6] Queueing Differential Diffusion")
        else:
            self.last_prompt_type = "t2i"
            print("[MockV6] Queueing T2I")
        return "mock_prompt_id"

    def wait_for_prompt(self, prompt_id, **kwargs):
        pass

    def get_history(self, prompt_id):
        return {prompt_id: {"outputs": {"9": {"images": [{"filename": "mock_out.png"}]}}}}

    def get_image_data(self, image_ref):
        if self.last_prompt_type == "t2i":
            img = Image.new("RGB", (256, 256))
            pixels = img.load()
            for y in range(256):
                for x in range(256):
                    if x < 128 and y < 128: col = (255, 0, 0)
                    elif x >= 128 and y < 128: col = (0, 255, 0)
                    elif x < 128 and y >= 128: col = (0, 0, 255)
                    else: col = (255, 255, 0)
                    pixels[x, y] = col
            return self._img_to_bytes(img)
            
        elif self.last_prompt_type == "diff_diffusion":
            if self.last_input_image:
                ctx = Image.open(self.last_input_image).convert("RGB")
                # Crop center 256
                output = ctx.crop((128, 128, 384, 384))
                return self._img_to_bytes(output)
        return b""

    def _img_to_bytes(self, img):
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

DATASET_ID = "generative_infinity_zoom_v6"
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
            if not p.exists(): return None
            tiles[(x, y)] = Image.open(p).convert("RGB")
    
    ts = 256
    canvas = Image.new("RGB", (ts * 2, ts * 2))
    canvas.paste(tiles[(1,1)], (0, 0))
    canvas.paste(tiles[(2,1)], (ts, 0))
    canvas.paste(tiles[(1,2)], (0, ts))
    canvas.paste(tiles[(2,2)], (ts, ts))
    return canvas

def generate_html_report(report_text, score, img_stitched, img_crop):
    html = f"""
    <html>
    <head><title>Generative Zoom V6 Analysis</title></head>
    <body style="font-family: sans-serif; max-width: 800px; margin: 0 auto; padding: 20px;">
        <h1>Generative Zoom V6 Analysis</h1>
        <p><strong>Experiment:</strong> Soft Inpainting via Differential Diffusion.</p>
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
    with open("artifacts/gen_zoom_v6_debug/report.html", "w") as f:
        f.write(html)
    print("\n[Report] Generated report.html in artifacts/gen_zoom_v6_debug/")

def run_test(args):
    try:
        setup_dataset()
        if args.clean:
            shutil.rmtree(DATASET_DIR / "0", ignore_errors=True)
            shutil.rmtree(DATASET_DIR / "1", ignore_errors=True)
            shutil.rmtree(DATASET_DIR / "2", ignore_errors=True)
        
        print("\n--- Step 1: Rendering Level 0 (Root) ---")
        with open(DATASET_DIR / "config.json") as f: conf = json.load(f)
        renderer = load_renderer(conf["renderer"], conf["tile_size"], conf["renderer_args"], dataset_path=str(DATASET_DIR))
        render_tiles.render_tasks(renderer, [(0, 0, 0, str(DATASET_DIR))], num_workers=0)

        print("\n--- Step 2: Rendering Level 1 (Children) ---")
        tasks_l1 = [(1, x, y, str(DATASET_DIR)) for x in [0,1] for y in [0,1]]
        render_tiles.render_tasks(renderer, tasks_l1, num_workers=0)

        print("\n--- Step 3: Rendering Level 2 (Center Quad) ---")
        tasks_l2 = [
            (2, 1, 1, str(DATASET_DIR)), (2, 2, 1, str(DATASET_DIR)),
            (2, 1, 2, str(DATASET_DIR)), (2, 2, 2, str(DATASET_DIR))
        ]
        render_tiles.render_tasks(renderer, tasks_l2, num_workers=0)

        print("--- Step 4: Analysis ---")
        stitched_l2 = stitch_center_quad_l2()
        
        if not stitched_l2:
            print("Failed to stitch L2 center.")
            return

        debug_dir = Path("artifacts/gen_zoom_v6_debug")
        debug_dir.mkdir(parents=True, exist_ok=True)
        stitched_l2.save(debug_dir / "level_2_center.png")
        
        seam_crop = stitched_l2.crop((192, 192, 320, 320))
        seam_crop_lg = seam_crop.resize((512, 512), Image.Resampling.NEAREST)
        seam_crop_lg.save(debug_dir / "level_2_seam_detail.png")

        if os.environ.get("OPENROUTER_API_KEY"):
            try:
                from backend.tools.analyze_image import analyze_images
                import asyncio
                print("\nRunning AI VLM Analysis on L2 Seam Detail...")
                prompt = (
                    "This is a magnified view of the intersection where 4 generated image tiles meet (Level 2 Deep Zoom). "
                    "Rate the quality of the stitching on a scale of 0 to 10 (10 = Perfect, Seamless). "
                    "Provide the score as 'SCORE: X/10'. "
                    "Then explain your reasoning. Look for sharp lines, color discontinuities, or broken textures."
                )
                report = asyncio.run(analyze_images([str(debug_dir / "level_2_seam_detail.png")], prompt))
                print("\n--- VLM Report ---")
                print(report)
                
                score = 0
                import re
                match = re.search(r"SCORE:\s*(\d+(\.\d+)?)/10", report, re.IGNORECASE)
                if match:
                    score = float(match.group(1))
                
                generate_html_report(report, score, "level_2_center.png", "level_2_seam_detail.png")
                
            except Exception as e:
                print(f"AI Analysis failed: {e}")

    except Exception as e:
        if hasattr(e, "details"):
            print(f"ComfyUI Error Details: {json.dumps(e.details, indent=2)}")
        raise e

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()

    if args.mock:
        print("Running in MOCK mode.")
        with patch('backend.comfyui_client.ComfyUIClient', side_effect=MockComfyUIClientV6):
            run_test(args)
    else:
        print("Running in REAL mode.")
        run_test(args)

if __name__ == "__main__":
    main()
