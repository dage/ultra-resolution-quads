import os
import sys
import json
import time
import random
import io
from pathlib import Path
from PIL import Image

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

import backend.comfyui_client

from backend.comfyui_client import first_image_ref_from_history



class GenerativeInfiniteZoomRenderer:

    def __init__(self, tile_size=1024, **kwargs):

        self.tile_size = tile_size

        self.dataset_root = kwargs.get('dataset_path') # Injected by load_renderer if available

        if not self.dataset_root:

             # Fallback to local dir

             self.dataset_root = os.path.abspath(os.path.dirname(__file__))



        self.comfy_server = kwargs.get('comfy_server', '127.0.0.1:8188')

        

        # Prompts

        self.prompt_t2i = kwargs.get('prompt_t2i', "abstract texture")

        self.prompt_img2img = kwargs.get('prompt_img2img', "add detail")

        self.denoise = kwargs.get('denoise', 0.25)



        # Load Workflows

        # We assume the workflows are stored in experiments/ or adjacent

        # __file__ is datasets/generative_infinity_zoom/render.py

        # parents[0] = generative_infinity_zoom

        # parents[1] = datasets

        # parents[2] = project root

        repo_root = Path(__file__).resolve().parents[2]

        self.wf_t2i_path = repo_root / "experiments" / "iterate_t2i" / "workflows" / "z_image_turbo_t2i_workflow.json"

        self.wf_i2i_path = repo_root / "experiments" / "iterate_t2i" / "workflows" / "comfyui_hallucination_test_comfyui_workflow.json"

        

        # Verify workflows exist - absolute fallback

        if not self.wf_t2i_path.exists():

             self.wf_t2i_path = Path(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../experiments/iterate_t2i/workflows/z_image_turbo_t2i_workflow.json')))

        if not self.wf_i2i_path.exists():

             self.wf_i2i_path = Path(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../experiments/iterate_t2i/workflows/comfyui_hallucination_test_comfyui_workflow.json')))



        if not self.wf_t2i_path.exists():

            raise FileNotFoundError(f"T2I workflow not found at {self.wf_t2i_path}")



        with open(self.wf_t2i_path, 'r') as f: self.wf_t2i = json.load(f)

        with open(self.wf_i2i_path, 'r') as f: self.wf_i2i = json.load(f)



        # Unique client per renderer instance (for multiprocess safety if enabled)

        self.client_id = f"genzoom-{os.getpid()}-{random.randint(1000, 9999)}"

        self.client = backend.comfyui_client.ComfyUIClient(self.comfy_server, self.client_id)



    def supports_multithreading(self):

        # Disabled to protect ComfyUI queue, but code is thread-safe

        return False



    def _run_workflow(self, workflow, image_input_path=None):

        """Generic runner for a prepared workflow dict."""

        

        # 1. Upload Input Image if needed (for Img2Img)

        if image_input_path:

            comfy_name = self.client.upload_image(Path(image_input_path))


            # Patch LoadImage node (ID 17 in hallucination workflow)
            if "17" in workflow:
                workflow["17"]["inputs"]["image"] = comfy_name
        
        # 2. Randomize Seed (Node 3 is KSampler in both)
        if "3" in workflow:
            workflow["3"]["inputs"]["seed"] = random.randint(1, 10**14)

        # 3. Queue and Wait
        # User indicates generation can take 3-4 minutes. Setting timeout to 10 minutes to be safe.
        prompt_id = self.client.queue_prompt(workflow)
        self.client.wait_for_prompt(prompt_id, timeout_s=600)
        
        # 4. Download Result
        history = self.client.get_history(prompt_id)
        data = history.get(prompt_id, {})
        # Node 9 is SaveImage in both
        img_ref = first_image_ref_from_history(data, preferred_node="9")
        
        if not img_ref:
            raise RuntimeError(f"No image returned for prompt {prompt_id}")
            
        raw = self.client.get_image_data(img_ref)
        return Image.open(io.BytesIO(raw)).convert("RGB")

    def render(self, level, x, y):
        # --- Level 0: Root Generation (Text-to-Image) ---
        if level == 0:
            print(f"[GenZoom] Generating Root L0 with T2I...")
            wf = json.loads(json.dumps(self.wf_t2i))
            # Patch Prompt (Node 6)
            if "6" in wf: wf["6"]["inputs"]["text"] = self.prompt_t2i
            return self._run_workflow(wf)

        # --- Level > 0: Recursive Zoom (Image-to-Image) ---
        # 1. Calculate Parent Logic
        parent_level = level - 1
        parent_x = x // 2
        parent_y = y // 2
        
        # Resolve Parent Path (Assumes standard dataset structure)
        # Note: self.dataset_root is passed by render_tiles.py
        parent_path = Path(self.dataset_root) / str(parent_level) / str(parent_x) / f"{parent_y}.webp"
        
        # Check extensions if webp not found (render_tiles usually saves as webp but let's be robust)
        if not parent_path.exists():
            for ext in ['.png', '.jpg']:
                alt = parent_path.with_suffix(ext)
                if alt.exists():
                    parent_path = alt
                    break
        
        if not parent_path.exists():
            # This should be handled by the RecursiveParentRendererWrapper in backend,
            # but if we are running standalone or it failed:
            raise FileNotFoundError(f"Parent tile missing: {parent_path}")

        # 2. Crop Quadrant (512x512) from Parent (1024x1024)
        with Image.open(parent_path) as parent_img:
            parent_img = parent_img.convert("RGB")
            
            # Quadrant arithmetic
            # If x is even, we are on the Left (0). If odd, Right (512).
            # If y is even, we are on Top (0). If odd, Bottom (512).
            # The logic: x%2 gives 0 or 1.
            # x=0 (left) -> 0. x=1 (right) -> 512.
            left = (x % 2) * 512
            top  = (y % 2) * 512
            
            quadrant = parent_img.crop((left, top, left + 512, top + 512))
            
            # Save quadrant to temp file for upload
            # Use a unique temp name to avoid collisions
            temp_path = Path(self.dataset_root) / f"temp_crop_{level}_{x}_{y}_{os.getpid()}.png"
            temp_path.parent.mkdir(parents=True, exist_ok=True)
            quadrant.save(temp_path)

        try:
            # 3. Run Upscale Workflow
            print(f"[GenZoom] Rendering L{level} ({x},{y}) via Img2Img...")
            wf = json.loads(json.dumps(self.wf_i2i))
            
            # Patch Prompt & Denoise
            if "6" in wf: wf["6"]["inputs"]["text"] = self.prompt_img2img
            if "3" in wf: wf["3"]["inputs"]["denoise"] = self.denoise
            
            # Run
            result_img = self._run_workflow(wf, image_input_path=temp_path)
            
            # Verify output size
            if result_img.size != (1024, 1024):
                print(f"Warning: Workflow output size {result_img.size} != 1024x1024. Resizing.")
                result_img = result_img.resize((1024, 1024), Image.Resampling.LANCZOS)
                
            return result_img
            
        finally:
            if temp_path.exists():
                temp_path.unlink()
