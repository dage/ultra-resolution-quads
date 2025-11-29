import json
import math
import subprocess
from pathlib import Path

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
        return float(cam['x']), float(cam['y'])
    if 'globalX' in cam and 'globalY' in cam:
        return float(cam['globalX']), float(cam['globalY'])
    # Fallback to center
    return 0.5, 0.5


def _add_globals(cam):
    out = dict(cam)
    gl = out.get('globalLevel')
    if gl is None:
        gl = out.get('level', 0) + out.get('zoomOffset', 0.0)
    out['globalLevel'] = gl
    out['level'] = math.floor(gl)
    out['zoomOffset'] = gl - out['level']
    gx, gy = _extract_global_xy(out)
    out['x'] = gx
    out['y'] = gy
    out['globalX'] = gx
    out['globalY'] = gy
    return out


_active_path = None
_active_options = None
_viewport_settings = {"width": 1920, "height": 1080}
_tile_size = 512

_project_root = Path(__file__).resolve().parents[1]
_node_cli = _project_root / "shared" / "camera_path_cli.js"


def set_camera_path(path, internal_resolution=2000, tension=0.0, viewport_width=1920, viewport_height=1080, tile_size=512):
    """
    Register the active path. Sampling is delegated to the shared JS implementation.
    """
    global _active_path, _active_options, _viewport_settings, _tile_size
    _active_path = path
    _active_options = {"resolution": internal_resolution, "tension": tension}
    _viewport_settings = {"width": viewport_width, "height": viewport_height}
    _tile_size = tile_size


def _sample_with_node(progress_list):
    if _active_path is None:
        raise RuntimeError("No active path set. Call set_camera_path first.")
    payload = {
        "path": _active_path,
        "progress": progress_list,
        "options": _active_options or {},
        "viewport": _viewport_settings,
        "tileSize": _tile_size
    }
    try:
        proc = subprocess.run(
            ["node", str(_node_cli)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"camera_path_cli failed: {exc.stderr}") from exc
    data = json.loads(proc.stdout)
    
    cameras = [_add_globals(cam) for cam in data.get("cameras", [])]
    # We might get 'tiles' back if we asked for a batch, but this function is primarily for cameras.
    # However, we can cache the tiles if returned.
    return cameras, data.get("tiles", [])


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
