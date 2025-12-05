import json
import math
import subprocess
from decimal import Decimal
from pathlib import Path

# Logical tile size used for viewport math. Image resolution can differ.
LOGICAL_TILE_SIZE = 512
# The frontend adapts to the window size, but for generation we must cover the *maximum expected* viewport.
VIEWPORT_WIDTH = 1920
VIEWPORT_HEIGHT = 1080


def _coerce_decimal(value, default="0.5"):
    """
    Convert a value (float, int, Decimal, or string) to Decimal while tolerating
    invalid inputs by falling back to a sane default.
    """
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def _extract_global_xy(cam):
    """
    Resolve a camera dict to normalized global coords (x, y) in [0, 1).
    Supports legacy tile/offset/globalX fields for backward compatibility.
    """
    if 'x' in cam and 'y' in cam:
        return _coerce_decimal(cam['x']), _coerce_decimal(cam['y'])
    if 'globalX' in cam and 'globalY' in cam:
        return _coerce_decimal(cam['globalX']), _coerce_decimal(cam['globalY'])
    # Fallback to center
    return _coerce_decimal(0.5), _coerce_decimal(0.5)


def _add_globals(cam):
    out = dict(cam)
    gl = out.get('globalLevel')
    if gl is None:
        gl = out.get('level', 0) + out.get('zoomOffset', 0.0)
    out['globalLevel'] = gl
    out['level'] = math.floor(gl)
    out['zoomOffset'] = gl - out['level']
    gx_dec, gy_dec = _extract_global_xy(out)
    out['x'] = float(gx_dec)
    out['y'] = float(gy_dec)
    out['globalX'] = out['x']
    out['globalY'] = out['y']
    out['x_str'] = format(gx_dec.normalize(), 'f') if isinstance(gx_dec, Decimal) else str(gx_dec)
    out['y_str'] = format(gy_dec.normalize(), 'f') if isinstance(gy_dec, Decimal) else str(gy_dec)
    return out


_active_path = None
_active_options = None
_viewport_settings = {"width": 1920, "height": 1080}
_tile_size = 512

_project_root = Path(__file__).resolve().parents[1]
_node_cli = _project_root / "shared" / "camera_path_cli.js"


def set_camera_path(path, viewport_width=1920, viewport_height=1080, tile_size=512):
    """
    Register the active path. Sampling is delegated to the shared JS implementation.
    """
    global _active_path, _active_options, _viewport_settings, _tile_size
    _active_path = path
    _active_options = {}
    _viewport_settings = {"width": viewport_width, "height": viewport_height}
    _tile_size = tile_size


import json
import math
import subprocess
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
import os

# Logical tile size used for viewport math. Image resolution can differ.
LOGICAL_TILE_SIZE = 512
# The frontend adapts to the window size, but for generation we must cover the *maximum expected* viewport.
VIEWPORT_WIDTH = 1920
VIEWPORT_HEIGHT = 1080


def _extract_global_xy(cam):
    """
    Resolve a camera dict to normalized global coords (x, y) in [0, 1).
    Supports legacy tile/offset/globalX fields for backward compatibility.
    """
    if 'x' in cam and 'y' in cam:
        return _coerce_decimal(cam['x']), _coerce_decimal(cam['y'])
    if 'globalX' in cam and 'globalY' in cam:
        return _coerce_decimal(cam['globalX']), _coerce_decimal(cam['globalY'])
    # Fallback to center
    return _coerce_decimal(0.5), _coerce_decimal(0.5)


def _add_globals(cam):
    out = dict(cam)
    gl = out.get('globalLevel')
    if gl is None:
        gl = out.get('level', 0) + out.get('zoomOffset', 0.0)
    out['globalLevel'] = gl
    out['level'] = math.floor(gl)
    out['zoomOffset'] = gl - out['level']
    gx_dec, gy_dec = _extract_global_xy(out)
    out['x'] = float(gx_dec)
    out['y'] = float(gy_dec)
    out['globalX'] = out['x']
    out['globalY'] = out['y']
    out['x_str'] = format(gx_dec.normalize(), 'f') if isinstance(gx_dec, Decimal) else str(gx_dec)
    out['y_str'] = format(gy_dec.normalize(), 'f') if isinstance(gy_dec, Decimal) else str(gy_dec)
    return out


_active_path = None
_active_options = None
_viewport_settings = {"width": 1920, "height": 1080}
_tile_size = 512

_project_root = Path(__file__).resolve().parents[1]
_node_cli = _project_root / "shared" / "camera_path_cli.js"


def set_camera_path(path, viewport_width=1920, viewport_height=1080, tile_size=512):
    """
    Register the active path. Sampling is delegated to the shared JS implementation.
    """
    global _active_path, _active_options, _viewport_settings, _tile_size
    _active_path = path
    _active_options = {}
    _viewport_settings = {"width": viewport_width, "height": viewport_height}
    _tile_size = tile_size

def get_samples_for_path(path, viewport_settings, tile_size, progress_list):
    """
    Pure function to sample path using Node CLI with explicit arguments.
    Useful for multiprocessing where global state isn't shared.
    """
    payload = {
        "path": path,
        "progress": progress_list,
        "options": {},
        "viewport": viewport_settings,
        "tileSize": tile_size
    }
    try:
        proc = subprocess.run(
            ["node", str(_node_cli)],
            input=json.dumps(payload),
            text=True,
            stdout=subprocess.PIPE,
            stderr=None, 
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"camera_path_cli failed with return code {exc.returncode}") from exc
    
    if not proc.stdout.strip():
        raise RuntimeError("camera_path_cli returned empty output")

    data = json.loads(proc.stdout)
    
    cameras = [_add_globals(cam) for cam in data.get("cameras", [])]
    return cameras, data.get("tiles", [])

def _sample_with_node(progress_list):
    if _active_path is None:
        raise RuntimeError("No active path set. Call set_camera_path first.")
    return get_samples_for_path(_active_path, _viewport_settings, _tile_size, progress_list)


def camera_at_progress(progress):
    """
    Sample a single progress value by delegating to the JS sampler.
    """
    cams, _ = _sample_with_node([progress])
    return cams[0] if cams else None


def cameras_at_progresses(progresses):
    """
    Sample a batch of progress values. Returns (cameras, tiles).
    """
    return _sample_with_node(list(progresses))

def _parallel_worker(args):
    # Unpack arguments for the worker
    path, viewport, tile_size, chunk = args
    return get_samples_for_path(path, viewport, tile_size, chunk)

def cameras_at_progresses_parallel(progresses, path, viewport_width, viewport_height, tile_size, num_workers=8):
    """
    Sample a batch of progress values in parallel using multiple Node processes.
    """
    chunk_size = math.ceil(len(progresses) / num_workers)
    chunks = [progresses[i:i + chunk_size] for i in range(0, len(progresses), chunk_size)]
    
    viewport = {"width": viewport_width, "height": viewport_height}
    
    # Prepare args for each worker
    worker_args = [(path, viewport, tile_size, chunk) for chunk in chunks]
    
    all_cameras = []
    all_tiles = []
    
    print(f"Distributing {len(progresses)} samples across {len(chunks)} workers...")
    
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        results = list(executor.map(_parallel_worker, worker_args))
        
    for cams, tiles in results:
        all_cameras.extend(cams)
        all_tiles.extend(tiles)
        
    return all_cameras, all_tiles
