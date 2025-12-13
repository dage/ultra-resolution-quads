import os
import sys
import time
import threading
import json
import logging
import io
import re
from contextlib import asynccontextmanager
from typing import Dict
from fastapi import FastAPI, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.constants import TILE_EXTENSION, TILE_FORMAT, TILE_WEBP_PARAMS
from backend.renderer_utils import load_renderer, generate_tile_manifest

# Constants
DATA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
MAX_CONCURRENT_RENDERS = 10

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LiveRenderer")

# Global state
last_manifest_update = 0
manifest_update_interval = 60  # seconds

# Global semaphore to cap CPU-bound renders and avoid overload
render_semaphore = threading.BoundedSemaphore(MAX_CONCURRENT_RENDERS)

# Cache renderers: dataset_id -> renderer_instance
renderer_cache = {}
active_renders = 0
active_lock = threading.Lock()

# Progress tracking: thread_id -> {"progress": float, "updated": float}
render_progress: Dict[int, Dict[str, float]] = {}
progress_lock = threading.Lock()

class ProgressHandler(logging.Handler):
    """
    Intercepts fractalshades logs to track render progress.
    Log format expected: "Image output: 1 / 36"
    """
    def emit(self, record):
        try:
            msg = record.getMessage()
            if "Image output:" in msg:
                match = re.search(r"Image output:\s*(\d+)\s*/\s*(\d+)", msg)
                if match:
                    current = int(match.group(1))
                    total = int(match.group(2))
                    if total > 0:
                        with progress_lock:
                            render_progress[threading.get_ident()] = {
                                "progress": current / total,
                                "updated": time.time(),
                            }
        except Exception:
            pass  # Fail silently to avoid interrupting render

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize logging handler and manifest updater
    fs_logger = logging.getLogger("fractalshades.core")
    fs_logger.setLevel(logging.INFO)
    progress_handler = ProgressHandler()
    fs_logger.addHandler(progress_handler)
    
    # Start manifest updater in background
    stop_event = threading.Event()
    
    def updater_loop():
        global last_manifest_update
        while not stop_event.is_set():
            time.sleep(manifest_update_interval)
            try:
                datasets_to_update = list(renderer_cache.keys())
                if not datasets_to_update:
                    continue

                logger.info(f"Running scheduled manifest update for: {datasets_to_update}")
                for ds_id in datasets_to_update:
                    ds_dir = os.path.join(DATA_ROOT, 'datasets', ds_id)
                    generate_tile_manifest(ds_dir)
                
                last_manifest_update = time.time()
                
            except Exception as e:
                logger.error(f"Error in manifest updater loop: {e}")

    updater_thread = threading.Thread(target=updater_loop, daemon=True)
    updater_thread.start()
    
    yield
    
    # Shutdown
    stop_event.set()
    # updater_thread.join() # Optional

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_renderer(dataset_id):
    if dataset_id in renderer_cache:
        return renderer_cache[dataset_id]
    
    config_path = os.path.join(DATA_ROOT, 'datasets', dataset_id, 'config.json')
    if not os.path.exists(config_path):
        raise ValueError(f"Dataset config not found: {config_path}")
    
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    renderer_path = config.get('renderer')
    tile_size = config.get('tile_size', 512)
    renderer_kwargs = config.get('renderer_args', {})
    
    logger.info(f"Loading renderer for {dataset_id}: {renderer_path}")
    dataset_path = os.path.join(DATA_ROOT, 'datasets', dataset_id)
    renderer = load_renderer(renderer_path, tile_size, renderer_kwargs, dataset_path=dataset_path)
    renderer_cache[dataset_id] = renderer
    return renderer

@app.get("/status")
def status():
    # Provide a lightweight health + activity snapshot.
    with active_lock:
        current_active = active_renders
    
    # Calculate progress using the most recent render update to reflect a single task.
    with progress_lock:
        progress_entries = list(render_progress.values())

    progress_str = None
    if current_active > 0 and progress_entries:
        latest = max(progress_entries, key=lambda p: p.get("updated", 0))
        progress_str = f"{int(latest.get('progress', 0) * 100)}%"

    return {
        "up": True,
        "active_renders": current_active,
        "max_concurrent": MAX_CONCURRENT_RENDERS,
        "busy": current_active >= MAX_CONCURRENT_RENDERS,
        "last_manifest_update": last_manifest_update,
        "progress": progress_str
    }

# --- Endpoints ---

@app.get("/live/{dataset}/{level}/{x}/{y}.webp")
def get_live_tile(dataset: str, level: int, x: int, y: int):
    global active_renders
    """
    Stateless endpoint for live tiles:
    1) Serve from disk if present.
    2) Acquire semaphore (non-blocking) to render.
    3) Render synchronously, save to disk, and return image.
    """
    tile_path = os.path.join(DATA_ROOT, 'datasets', dataset, str(level), str(x), f"{y}{TILE_EXTENSION}")

    # Fast path: serve cached tile
    if os.path.exists(tile_path):
        try:
            with open(tile_path, "rb") as f:
                return Response(content=f.read(), media_type="image/webp")
        except Exception as e:
            logger.error(f"Error reading existing tile: {e}")
            raise HTTPException(status_code=500, detail="File read error")

    if not render_semaphore.acquire(blocking=False):
        raise HTTPException(status_code=503, detail="Server busy (max concurrent renders reached)")

    with active_lock:
        active_renders_count = active_renders + 1
        active_renders = active_renders_count

    # Initialize progress for this thread
    tid = threading.get_ident()
    with progress_lock:
        render_progress[tid] = {"progress": 0.0, "updated": time.time()}

    try:
        os.makedirs(os.path.dirname(tile_path), exist_ok=True)

        renderer = get_renderer(dataset)

        t0 = time.time()
        logger.info(f"Rendering {dataset} {level}/{x}/{y}...")

        img = renderer.render(level, x, y)

        buf = io.BytesIO()
        img.save(buf, format=TILE_FORMAT, **TILE_WEBP_PARAMS)
        img_bytes = buf.getvalue()

        with open(tile_path, "wb") as f:
            f.write(img_bytes)

        duration = time.time() - t0
        logger.info(f"Finished {dataset} {level}/{x}/{y} in {duration:.2f}s")

        return Response(content=img_bytes, media_type="image/webp")

    except Exception as e:
        logger.error(f"Render failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Mark this render as complete before cleanup so the last poll can show 100%
        with progress_lock:
            if tid in render_progress:
                render_progress[tid] = {"progress": 1.0, "updated": time.time()}

        with active_lock:
            active_renders_count = max(0, active_renders - 1)
            active_renders = active_renders_count
        render_semaphore.release()

        # Cleanup progress entry after counters are updated
        with progress_lock:
            if tid in render_progress:
                del render_progress[tid]

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("BACKEND_PORT", 8002))
    print(f"Starting Stateless Live Renderer (Max {MAX_CONCURRENT_RENDERS} concurrent) on port {port}...")
    try:
        uvicorn.run(app, host="0.0.0.0", port=port)
    except Exception as e:
        print(f"Uvicorn failed: {e}")
