import os
import sys
import time
import queue
import threading
import json
import logging
import importlib
import inspect
import io
import asyncio
from typing import Dict, Optional, Any
from dataclasses import dataclass, field
from fastapi import FastAPI, Response, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, ImageDraw, ImageFont

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.constants import TILE_EXTENSION, TILE_FORMAT, TILE_WEBP_PARAMS
from backend.renderer_utils import load_renderer

# Constants
DATA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LiveRenderer")

app = FastAPI()

# Allow CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@dataclass
class Job:
    id: str
    dataset: str
    level: int
    x: int
    y: int
    status: str = "PENDING"  # PENDING, RENDERING, DONE, ERROR
    progress: int = 0
    error_msg: str = ""
    created_at: float = field(default_factory=time.time)
    result_path: Optional[str] = None
    last_activity: float = field(default_factory=time.time)

class JobManager:
    def __init__(self):
        self.jobs: Dict[str, Job] = {}
        self.queue: queue.Queue = queue.Queue()
        self.completed_count = 0
        self.lock = threading.Lock()

    def request_job(self, dataset, level, x, y) -> Job:
        job_id = f"{dataset}|{level}|{x}|{y}"
        with self.lock:
            if job_id in self.jobs:
                # If job was done long ago (clean up logic?), for now just return it
                return self.jobs[job_id]
            
            job = Job(id=job_id, dataset=dataset, level=level, x=x, y=y)
            self.jobs[job_id] = job
            self.queue.put(job)
            return job

    def get_job(self, job_id) -> Optional[Job]:
        with self.lock:
            return self.jobs.get(job_id)

    def mark_rendering(self, job_id):
        with self.lock:
            if job_id in self.jobs:
                self.jobs[job_id].status = "RENDERING"
                self.jobs[job_id].last_activity = time.time()

    def update_progress(self, job_id, progress):
        with self.lock:
            if job_id in self.jobs:
                self.jobs[job_id].progress = progress
                self.jobs[job_id].last_activity = time.time()

    def complete_job(self, job_id, path):
        with self.lock:
            if job_id in self.jobs:
                self.jobs[job_id].status = "DONE"
                self.jobs[job_id].progress = 100
                self.jobs[job_id].result_path = path
                self.jobs[job_id].last_activity = time.time()
                self.completed_count += 1

    def fail_job(self, job_id, msg):
        with self.lock:
            if job_id in self.jobs:
                self.jobs[job_id].status = "ERROR"
                self.jobs[job_id].error_msg = msg
                self.jobs[job_id].last_activity = time.time()

    def get_status(self):
        with self.lock:
            pending = self.queue.qsize()
            active = False
            # Check if any job is actively rendering
            for j in self.jobs.values():
                if j.status == "RENDERING":
                    active = True
                    break
            return {
                "pending": pending,
                "active": active,
                "completed_count": self.completed_count
            }

job_manager = JobManager()
RENDER_LOCK = threading.Lock()

# Cache renderers: dataset_id -> renderer_instance
renderer_cache = {}

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

# --- Worker ---

def render_worker():
    logger.info("RenderWorker started.")
    while True:
        job = job_manager.queue.get()
        try:
            # Check if tile already exists (double check)
            tile_path = os.path.join(DATA_ROOT, 'datasets', job.dataset, str(job.level), str(job.x), f"{job.y}{TILE_EXTENSION}")
            if os.path.exists(tile_path):
                logger.info(f"Job {job.id}: Tile already exists on disk.")
                job_manager.complete_job(job.id, tile_path)
            else:
                with RENDER_LOCK:
                    logger.info(f"Job {job.id}: Starting render...")
                    job_manager.mark_rendering(job.id)
                    
                    # Ensure dirs
                    os.makedirs(os.path.dirname(tile_path), exist_ok=True)
                    
                    renderer = get_renderer(job.dataset)
                    
                    # Render
                    # Simulate progress if needed, but for now we just render.
                    # Ideally capture stdout if the renderer prints progress.
                    # Since we are in the same process, stdout capture is tricky with threads.
                    # For now, we set progress to 50% immediately.
                    job_manager.update_progress(job.id, 50)
                    
                    t0 = time.time()
                    img = renderer.render(job.level, job.x, job.y)
                    img.save(tile_path, format=TILE_FORMAT, **TILE_WEBP_PARAMS)
                    duration = time.time() - t0
                    
                    logger.info(f"Job {job.id}: Finished in {duration:.2f}s")
                    job_manager.complete_job(job.id, tile_path)

        except Exception as e:
            logger.error(f"Job {job.id} failed: {e}", exc_info=True)
            job_manager.fail_job(job.id, str(e))
        finally:
            job_manager.queue.task_done()

# Start Worker
worker_thread = threading.Thread(target=render_worker, daemon=True)
worker_thread.start()

# --- Image Generators ---

def create_progress_image(text, progress_pct, width=512, height=512):
    img = Image.new('RGB', (width, height), (30, 30, 30))
    draw = ImageDraw.Draw(img)
    
    # Draw progress bar
    bar_width = width * 0.8
    bar_height = 20
    x_start = (width - bar_width) / 2
    y_start = (height - bar_height) / 2
    
    draw.rectangle([x_start, y_start, x_start + bar_width, y_start + bar_height], outline=(200, 200, 200), width=2)
    fill_width = bar_width * (progress_pct / 100.0)
    draw.rectangle([x_start, y_start, x_start + fill_width, y_start + bar_height], fill=(0, 255, 100))
    
    # Draw text
    # Default font
    draw.text((x_start, y_start - 30), text, fill=(255, 255, 255))
    
    return img

def create_error_image(msg, width=512, height=512):
    img = Image.new('RGB', (width, height), (100, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.text((20, height/2), f"Error: {msg}", fill=(255, 255, 255))
    return img

def image_to_bytes(img):
    buf = io.BytesIO()
    img.save(buf, format="WEBP")
    return buf.getvalue()

# --- Endpoints ---

@app.get("/queue-status")
def get_queue_status():
    return job_manager.get_status()

@app.get("/live/{dataset}/{level}/{x}/{y}.webp")
async def get_live_tile(dataset: str, level: int, x: int, y: int):
    # Request Job (Always queue, even if exists, to ensure UI consistency)
    job = job_manager.request_job(dataset, level, x, y)
    
    async def mjpeg_generator():
        boundary = "frame"
        
        while True:
            # Check job status
            current_job = job_manager.get_job(job.id)
            
            if current_job.status == "DONE":
                # Yield final image
                try:
                    with open(current_job.result_path, "rb") as f:
                        final_bytes = f.read()
                    yield (
                        f"--{boundary}\r\n".encode() + 
                        b"Content-Type: image/webp\r\n\r\n" + final_bytes + b"\r\n"
                    )
                except Exception as e:
                    logger.error(f"Failed to read result file: {e}")
                break
            
            elif current_job.status == "ERROR":
                err_img = create_error_image(current_job.error_msg)
                err_bytes = image_to_bytes(err_img)
                yield (
                    f"--{boundary}\r\n".encode() + 
                    b"Content-Type: image/webp\r\n\r\n" + err_bytes + b"\r\n"
                )
                break
                
            else:
                # Yield progress
                status_text = f"Queue Pos: ?" 
                # Calculating queue pos is expensive O(N), simplify
                if current_job.status == "RENDERING":
                    status_text = f"Rendering... {current_job.progress}%"
                else:
                    status_text = "Pending..."
                
                prog_img = create_progress_image(status_text, current_job.progress)
                prog_bytes = image_to_bytes(prog_img)
                
                yield (
                    f"--{boundary}\r\n".encode() + 
                    b"Content-Type: image/webp\r\n\r\n" + prog_bytes + b"\r\n"
                )
                
                await asyncio.sleep(0.1)

    return StreamingResponse(
        mjpeg_generator(), 
        media_type="multipart/x-mixed-replace;boundary=frame"
    )

if __name__ == "__main__":
    import uvicorn
    print("Starting Uvicorn server on port 8000...")
    try:
        uvicorn.run(app, host="0.0.0.0", port=8000)
    except Exception as e:
        print(f"Uvicorn failed: {e}")

