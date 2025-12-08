import os
import sys
import time
import threading
import json
import logging
import io
from fastapi import FastAPI, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.constants import TILE_EXTENSION, TILE_FORMAT, TILE_WEBP_PARAMS
from backend.renderer_utils import load_renderer

# Constants
DATA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
MAX_CONCURRENT_RENDERS = 10

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LiveRenderer")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global semaphore to cap CPU-bound renders and avoid overload
render_semaphore = threading.BoundedSemaphore(MAX_CONCURRENT_RENDERS)

# Cache renderers: dataset_id -> renderer_instance
renderer_cache = {}
active_renders = 0
active_lock = threading.Lock()

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
    renderer = load_renderer(renderer_path, tile_size, renderer_kwargs)
    renderer_cache[dataset_id] = renderer
    return renderer

# Backward-compat endpoint to silence legacy queue polling.
# Frontend no longer consumes this; returning empty status avoids noisy 404 logs.
@app.get("/queue-status")
def queue_status():
    # Provide a lightweight health + activity snapshot.
    with active_lock:
        current = active_renders
    return {
        "up": True,
        "active_renders": current,
        "max_concurrent": MAX_CONCURRENT_RENDERS,
        "busy": current >= MAX_CONCURRENT_RENDERS,
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
        with active_lock:
            active_renders_count = max(0, active_renders - 1)
            active_renders = active_renders_count
        render_semaphore.release()

if __name__ == "__main__":
    import uvicorn
    print(f"Starting Stateless Live Renderer (Max {MAX_CONCURRENT_RENDERS} concurrent)...")
    try:
        uvicorn.run(app, host="0.0.0.0", port=8000)
    except Exception as e:
        print(f"Uvicorn failed: {e}")
