import json
import math
import subprocess
from pathlib import Path

# Logical tile size used for viewport math. Image resolution can differ.
LOGICAL_TILE_SIZE = 512
# The frontend adapts to the window size, but for generation we must cover the *maximum expected* viewport.
VIEWPORT_WIDTH = 1920
VIEWPORT_HEIGHT = 1080


def _add_globals(cam):
    out = dict(cam)
    out.setdefault('zoomOffset', 0.0)
    lvl = out['level'] + out.get('zoomOffset', 0.0)
    factor = 1.0 / (2 ** out['level'])
    out['globalLevel'] = lvl
    out['globalX'] = (out['tileX'] + out['offsetX']) * factor
    out['globalY'] = (out['tileY'] + out['offsetY']) * factor
    return out


def get_viewport_bounds_at_level(camera, target_level):
    gx = camera['globalX']
    gy = camera['globalY']
    target_factor = 2 ** target_level
    cam_x_t = gx * target_factor
    cam_y_t = gy * target_factor
    cam_total_level = camera['level'] + camera['zoomOffset']
    scale = 2 ** (cam_total_level - target_level)
    tile_size_on_screen = LOGICAL_TILE_SIZE * scale
    tiles_w = VIEWPORT_WIDTH / tile_size_on_screen
    tiles_h = VIEWPORT_HEIGHT / tile_size_on_screen
    min_x = cam_x_t - tiles_w / 2
    max_x = cam_x_t + tiles_w / 2
    min_y = cam_y_t - tiles_h / 2
    max_y = cam_y_t + tiles_h / 2
    return min_x, max_x, min_y, max_y


def get_visible_tiles(camera, margin=1):
    visible = set()
    levels = [camera['level']]
    if camera['zoomOffset'] > 0.001:
        levels.append(camera['level'] + 1)
    for lvl in levels:
        if lvl < 0:
            continue
        min_x, max_x, min_y, max_y = get_viewport_bounds_at_level(camera, lvl)
        tx_min = math.floor(min_x - margin)
        tx_max = math.floor(max_x + margin)
        ty_min = math.floor(min_y - margin)
        ty_max = math.floor(max_y + margin)
        limit = 2 ** lvl
        for x in range(tx_min, tx_max + 1):
            for y in range(ty_min, ty_max + 1):
                if 0 <= x < limit and 0 <= y < limit:
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
