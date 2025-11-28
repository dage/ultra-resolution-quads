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


def get_visible_tiles(camera, margin=1):
    visible = set()
    base_level = math.floor(camera['globalLevel'])
    levels = [base_level]
    if camera['globalLevel'] - base_level > 1e-3:
        levels.append(base_level + 1)
        
    # Fixed Radius Sampling
    # 1920x1080 view with 512px tiles requires ~2.2 radius to cover corners.
    # We use 3.0 to be safe and include margins.
    RADIUS = 3.0
    
    for lvl in levels:
        if lvl < 0:
            continue
            
        # Camera Center in Target Level Coordinates
        limit = 2 ** lvl
        cam_x = camera['x'] * limit
        cam_y = camera['y'] * limit
        
        # Scan bounding box of radius
        min_x = math.floor(cam_x - RADIUS)
        max_x = math.ceil(cam_x + RADIUS)
        min_y = math.floor(cam_y - RADIUS)
        max_y = math.ceil(cam_y + RADIUS)
        
        for x in range(min_x, max_x + 1):
            for y in range(min_y, max_y + 1):
                if 0 <= x < limit and 0 <= y < limit:
                    # Check distance from camera center to tile center
                    dist = math.hypot(x + 0.5 - cam_x, y + 0.5 - cam_y)
                    # Allow tiles where any part is within radius
                    # Tile radius is ~0.707. So dist < RADIUS + 0.707
                    if dist < RADIUS:
                        visible.add((lvl, x, y))
    return visible


_active_path = None
_active_options = None
_project_root = Path(__file__).resolve().parents[1]
_node_cli = _project_root / "shared" / "camera_path_cli.js"


def set_camera_path(path, internal_resolution=2000, tension=0.0):
    """
    Register the active path. Sampling is delegated to the shared JS implementation
    via `shared/camera_path_cli.js` to keep frontend and backend identical.
    """
    global _active_path, _active_options
    _active_path = path
    _active_options = {"resolution": internal_resolution, "tension": tension}


def _sample_with_node(progress_list):
    if _active_path is None:
        raise RuntimeError("No active path set. Call set_camera_path first.")
    payload = {
        "path": _active_path,
        "progress": progress_list,
        "options": _active_options or {},
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
    return [_add_globals(cam) for cam in data.get("cameras", [])]


def camera_at_progress(progress):
    """
    Sample a single progress value by delegating to the JS sampler.
    """
    cams = _sample_with_node([progress])
    return cams[0] if cams else None


def cameras_at_progresses(progresses):
    """
    Sample a batch of progress values in a single Node invocation.
    """
    return _sample_with_node(list(progresses))
