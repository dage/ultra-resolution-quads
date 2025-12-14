import importlib
import inspect
import os
import json
import sys
import tempfile
from typing import Any, Dict, List, Optional, Set, Tuple

# Add project root to path to find constants
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.constants import TILE_EXTENSION, TILE_FORMAT, TILE_WEBP_PARAMS

def calculate_max_iter(level, base=2000, increment=200):
    """
    Calculates the maximum iterations for a given zoom level.
    Formula: max_iter = base + (level * increment)
    
    Args:
        level (int): The current zoom level.
        base (int): The base number of iterations at level 0. Default 2000.
        increment (int): The number of iterations to add per level. Default 200.
        
    Returns:
        int: The calculated maximum iterations.
    """
    return base + (int(level) * increment)

def _tile_path(dataset_path: str, level: int, x: int, y: int) -> str:
    return os.path.join(dataset_path, str(level), str(x), f"{y}{TILE_EXTENSION}")


def _atomic_save_image(img, dst_path: str) -> None:
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(dst_path), suffix=TILE_EXTENSION)
    os.close(fd)
    try:
        img.save(tmp_path, format=TILE_FORMAT, **TILE_WEBP_PARAMS)
        try:
            os.replace(tmp_path, dst_path)
        except OSError:
            # If another worker beat us to it (or the target is temporarily locked),
            # prefer keeping the existing file rather than failing the whole render.
            if not os.path.exists(dst_path):
                raise
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


class RecursiveParentRendererWrapper:
    """
    Dependency-aware wrapper for tile renderers.

    Default behavior matches the previous implementation: ensure the direct parent exists
    (level-1, x//2, y//2) before rendering (level, x, y).

    Optional renderer hook for generalization:
      - required_tiles(level, x, y) -> list[(dep_level, dep_x, dep_y)]
        (alias: get_required_tiles)

    Contract (to keep recursion safe):
      - dependencies must be for strictly lower levels: dep_level < level
    """

    def __init__(self, real_renderer, dataset_path: str):
        self.real_renderer = real_renderer
        self.dataset_path = dataset_path

    def __getattr__(self, name):
        return getattr(self.real_renderer, name)

    def _default_required_tiles(self, level: int, x: int, y: int) -> List[Tuple[int, int, int]]:
        if level <= 0:
            return []
        return [(level - 1, x // 2, y // 2)]

    def _validate_tile_coords(self, level: int, x: int, y: int) -> None:
        if level < 0:
            raise ValueError(f"Invalid required tile level: {level}")
        if x < 0 or y < 0:
            raise ValueError(f"Invalid required tile coords: level={level} x={x} y={y}")
        limit = (1 << int(level)) - 1
        if x > limit or y > limit:
            raise ValueError(f"Invalid required tile coords: level={level} x={x} y={y} (limit={limit})")

    def _required_tiles(self, level: int, x: int, y: int) -> List[Tuple[int, int, int]]:
        fn = getattr(self.real_renderer, "required_tiles", None)
        if not callable(fn):
            fn = getattr(self.real_renderer, "get_required_tiles", None)

        if not callable(fn):
            return self._default_required_tiles(level, x, y)

        raw = fn(int(level), int(x), int(y)) or []
        out: List[Tuple[int, int, int]] = []
        seen: Set[Tuple[int, int, int]] = set()
        for dep_level, dep_x, dep_y in raw:
            dl = int(dep_level)
            dx = int(dep_x)
            dy = int(dep_y)
            if dl >= int(level):
                raise ValueError(
                    f"{self.real_renderer.__class__.__name__}.required_tiles returned non-lower dependency "
                    f"({dl},{dx},{dy}) for tile ({level},{x},{y}); require dep_level < level to avoid cycles."
                )
            self._validate_tile_coords(dl, dx, dy)
            key = (dl, dx, dy)
            if key in seen:
                continue
            seen.add(key)
            out.append(key)
        return out

    def _ensure_tile_on_disk(self, level: int, x: int, y: int, *, stack: Set[Tuple[int, int, int]]) -> None:
        path = _tile_path(self.dataset_path, level, x, y)
        if os.path.exists(path):
            return
        img = self._render_with_stack(level, x, y, stack=stack)
        if os.path.exists(path):
            return
        _atomic_save_image(img, path)

    def _render_with_stack(self, level: int, x: int, y: int, *, stack: Set[Tuple[int, int, int]]):
        key = (int(level), int(x), int(y))
        if key in stack:
            raise RuntimeError(f"Dependency cycle detected while rendering tile {key}")
        stack.add(key)
        try:
            for dep_level, dep_x, dep_y in self._required_tiles(int(level), int(x), int(y)):
                self._ensure_tile_on_disk(dep_level, dep_x, dep_y, stack=stack)
            return self.real_renderer.render(int(level), int(x), int(y))
        finally:
            stack.remove(key)

    def render(self, level, x, y):
        return self._render_with_stack(int(level), int(x), int(y), stack=set())

def load_renderer(
    renderer_path: str,
    tile_size: int,
    renderer_kwargs: Dict[str, Any],
    dataset_path: str = None,
):
    """
    Load and instantiate a renderer class given a module path string of the form
    'module.submodule:ClassName' or 'module.submodule.ClassName'.
    
    If dataset_path is provided, wraps the renderer to enforce dependency policies
    (defaults to the legacy "direct parent required" behavior).
    """
    if ':' in renderer_path:
        module_path, class_name = renderer_path.split(':', 1)
    elif '.' in renderer_path:
        module_path, class_name = renderer_path.rsplit('.', 1)
    else:
        raise ValueError("Renderer path must be in the form 'module:ClassName' or 'module.ClassName'.")

    module = importlib.import_module(module_path)
    renderer_cls = getattr(module, class_name)

    kwargs = dict(renderer_kwargs or {})
    try:
        sig = inspect.signature(renderer_cls)
        if 'tile_size' in sig.parameters and 'tile_size' not in kwargs:
            kwargs['tile_size'] = tile_size
    except (TypeError, ValueError):
        # Builtins or C extensions may not support signature inspection
        pass

    try:
        instance = renderer_cls(**kwargs)
        if dataset_path:
            return RecursiveParentRendererWrapper(instance, dataset_path)
        return instance
    except TypeError as exc:
        raise TypeError(f"Failed to instantiate renderer '{renderer_path}' with args {kwargs}: {exc}") from exc

def format_time(seconds: float) -> str:
    """
    Formats a duration in seconds into a short string like '1h 20m 3s' or '45s'.
    """
    if seconds <= 0:
        return "0s"
    
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    
    parts = []
    if h > 0:
        parts.append(f"{h}h")
    if m > 0:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    
    return " ".join(parts)

def generate_tile_manifest(dataset_dir):
    """
    Scans the dataset directory for all existing .webp tiles and writes a 'tiles.json'
    manifest file containing a flat list of "level/x/y" strings.
    This allows the frontend to know exactly which tiles exist without 404s.
    """
    if not os.path.exists(dataset_dir):
        return

    manifest_path = os.path.join(dataset_dir, 'tiles.json')
    tiles = []
    
    # Walk the directory
    # Structure is dataset_dir/level/x/y.webp
    for root, dirs, files in os.walk(dataset_dir):
        for file in files:
            if file.endswith(TILE_EXTENSION):
                try:
                    # root should be .../dataset_id/level/x
                    # file is y.webp
                    parts = root.split(os.sep)
                    x = parts[-1]
                    level = parts[-2]
                    y = file.replace(TILE_EXTENSION, "")
                    
                    # Verify structure (simple check)
                    if level.isdigit() and x.isdigit() and y.isdigit():
                        tiles.append(f"{level}/{x}/{y}")
                except IndexError:
                    # Unexpected directory structure, skip
                    pass
    
    with open(manifest_path, 'w') as f:
        json.dump(tiles, f)
