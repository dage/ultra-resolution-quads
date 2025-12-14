import os
import sys
import json
import shutil
import numpy as np
import argparse
from pathlib import Path
from PIL import Image

# Add project root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
# Add backend to path so internal imports in render_tiles work (e.g. import camera_utils)
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../backend')))

from backend import render_tiles
from backend.renderer_utils import load_renderer

# --- Mock ComfyUI Client for testing without server ---
from unittest.mock import MagicMock, patch
import io

class MockComfyUIClient:
    def __init__(self, server_address, client_id, **kwargs):
        self.server_address = server_address
        self.client_id = client_id
        self.uploaded_files = {} # filename -> path
        self.last_prompt_type = None
        self.last_input_image = None
        print(f"[MockComfyUI] Initialized for {server_address}")

    def upload_image(self, filepath, **kwargs):
        print(f"[MockComfyUI] Uploading {filepath}")
        name = Path(filepath).name
        self.uploaded_files[name] = filepath
        return name

    def queue_prompt(self, workflow):
        # Check if it's T2I or Img2Img
        if "18" in workflow:
            # Img2Img - get input image
            input_node = workflow.get("17", {})
            img_name = input_node.get("inputs", {}).get("image")
            self.last_input_image = self.uploaded_files.get(img_name)
            self.last_prompt_type = "img2img"
            print(f"[MockComfyUI] Queueing Img2Img with input: {img_name}")
        else:
            self.last_prompt_type = "t2i"
            print("[MockComfyUI] Queueing T2I")
        return "mock_prompt_id"

    def wait_for_prompt(self, prompt_id, **kwargs):
        pass

    def get_history(self, prompt_id):
        return {prompt_id: {"outputs": {"9": {"images": [{"filename": "mock_out.png"}]}}}}

    def get_image_data(self, image_ref):
        if self.last_prompt_type == "t2i":
            # Generate a deterministic gradient pattern for Root
            img = Image.new("RGB", (1024, 1024))
            # Create a simple quadrant pattern to easily verify cropping
            # TL: Red, TR: Green, BL: Blue, BR: Yellow
            # But we want smooth content for realism, though solid blocks make verification trivial.
            # Let's use solid blocks for robust logic testing.
            # 512x512 blocks.
            pixels = img.load()
            for y in range(1024):
                for x in range(1024):
                    if x < 512 and y < 512: col = (255, 0, 0) # Red
                    elif x >= 512 and y < 512: col = (0, 255, 0) # Green
                    elif x < 512 and y >= 512: col = (0, 0, 255) # Blue
                    else: col = (255, 255, 0) # Yellow
                    pixels[x, y] = col
            
            # Add some text to ensure orientation is correct
            from PIL import ImageDraw
            d = ImageDraw.Draw(img)
            d.text((256, 256), "TL", fill=(255,255,255))
            d.text((768, 256), "TR", fill=(0,0,0))
            d.text((256, 768), "BL", fill=(255,255,255))
            d.text((768, 768), "BR", fill=(0,0,0))
            
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
            
        elif self.last_prompt_type == "img2img":
            # Read the input crop and upscale it
            if not self.last_input_image or not Path(self.last_input_image).exists():
                print(f"Error: Input image {self.last_input_image} missing!")
                # Return random noise if fail
                return Image.new("RGB", (1024, 1024)).tobytes()
                
            with Image.open(self.last_input_image) as input_img:
                # Input should be 512x512
                # Upscale to 1024x1024 (Nearest neighbor to preserve sharp block edges for verification)
                output = input_img.resize((1024, 1024), Image.Resampling.NEAREST)
                
                buf = io.BytesIO()
                output.save(buf, format="PNG")
                return buf.getvalue()
        
        return b""

DATASET_ID = "generative_infinity_zoom"
DATASET_DIR = Path("datasets") / DATASET_ID

def setup_dataset():
    """Ensure config exists."""
    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    if not (DATASET_DIR / "config.json").exists():
        print("Error: config.json missing. Please ensure the plan files are applied.")
        sys.exit(1)

def stitch_level_1():
    """Load the 4 tiles of Level 1 and stitch them into a 2x2 grid (2048x2048)."""
    tiles = {}
    for x in [0, 1]:
        for y in [0, 1]:
            p = DATASET_DIR / "1" / str(x) / f"{y}.webp"
            if not p.exists():
                print(f"Missing tile 1/{x}/{y}")
                return None
            tiles[(x, y)] = Image.open(p).convert("RGB")
    
    ts = tiles[(0,0)].size[0] # Should be 1024
    canvas = Image.new("RGB", (ts * 2, ts * 2))
    canvas.paste(tiles[(0,0)], (0, 0))
    canvas.paste(tiles[(1,0)], (ts, 0))
    canvas.paste(tiles[(0,1)], (0, ts))
    canvas.paste(tiles[(1,1)], (ts, ts))
    return canvas

def compare_images(img_a, img_b):
    """Compute simple MSE/RMSE between two images."""
    if img_a.size != img_b.size:
        img_b = img_b.resize(img_a.size, Image.Resampling.LANCZOS)
    
    arr_a = np.array(img_a).astype(np.float32)
    arr_b = np.array(img_b).astype(np.float32)
    
    diff = arr_a - arr_b
    mse = np.mean(diff ** 2)
    rmse = np.sqrt(mse)
    return mse, rmse

def run_test(args):
    setup_dataset()
    
    if args.clean:
        print("Cleaning previous render output...")
        shutil.rmtree(DATASET_DIR / "0", ignore_errors=True)
        shutil.rmtree(DATASET_DIR / "1", ignore_errors=True)
    
    print("\n--- Step 1: Rendering Level 0 (Root) ---")
    with open(DATASET_DIR / "config.json") as f:
        conf = json.load(f)
        
    renderer = load_renderer(
        conf["renderer"], 
        conf["tile_size"], 
        conf["renderer_args"], 
        dataset_path=str(DATASET_DIR)
    )
    
    render_tiles.render_tasks(renderer, [(0, 0, 0, str(DATASET_DIR))], num_workers=0)

    print("\n--- Step 2: Rendering Level 1 (Children) ---")
    tasks = [
        (1, 0, 0, str(DATASET_DIR)),
        (1, 1, 0, str(DATASET_DIR)),
        (1, 0, 1, str(DATASET_DIR)),
        (1, 1, 1, str(DATASET_DIR))
    ]
    render_tiles.render_tasks(renderer, tasks, num_workers=0)

    print("\n--- Step 3: Analysis ---")
    l0_path = DATASET_DIR / "0" / "0" / "0.webp"
    if not l0_path.exists():
        print("Level 0 tile missing, cannot compare.")
        return

    l0_img = Image.open(l0_path).convert("RGB")
    stitched_l1 = stitch_level_1()
    
    if not stitched_l1:
        print("Failed to stitch Level 1.")
        return

    l1_down = stitched_l1.resize((1024, 1024), Image.Resampling.LANCZOS)
    
    debug_dir = Path("artifacts/gen_zoom_debug")
    debug_dir.mkdir(parents=True, exist_ok=True)
    l0_img.save(debug_dir / "level_0_ref.png")
    l1_down.save(debug_dir / "level_1_composite.png")
    
    mse, rmse = compare_images(l0_img, l1_down)
    print(f"Consistency Check (L0 vs Downsampled L1):")
    print(f"MSE: {mse:.2f}")
    print(f"RMSE: {rmse:.2f}")
    print(f"Saved debug images to {debug_dir}")
    
    try:
        from backend.tools.analyze_image import analyze_images
        import asyncio
        if os.environ.get("OPENROUTER_API_KEY"):
            print("\nRunning AI VLM Analysis...")
            prompt = "Compare these two images. Do they look structurally identical?"
            report = asyncio.run(analyze_images(
                [str(debug_dir / "level_0_ref.png"), str(debug_dir / "level_1_composite.png")],
                prompt
            ))
            print("VLM Verdict:")
            print(report)
    except Exception as e:
        print(f"AI analysis skipped: {e}")

def main():
    parser = argparse.ArgumentParser(description="Test Generative Zoom Logic")
    parser.add_argument("--mock", action="store_true", help="Use Mock ComfyUI client")
    parser.add_argument("--clean", action="store_true", help="Delete previous tiles before running")
    args = parser.parse_args()

    if args.mock:
        print("Running in MOCK mode.")
        with patch('backend.comfyui_client.ComfyUIClient', side_effect=MockComfyUIClient):
            run_test(args)
    else:
        print("Running in REAL mode (using config.json for ComfyUI address).")
        try:
            run_test(args)
        except Exception as e:
            print(f"\n[Error] Failed to run with real ComfyUI: {e}")
            print("Tip: Run with --mock to verify logic without a server.")
            if "ConnectionRefused" in str(e) or "Cannot connect" in str(e):
                sys.exit(1)
            raise e

if __name__ == "__main__":
    main()