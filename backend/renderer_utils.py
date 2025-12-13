import importlib
import inspect
import os
import json
import sys
import tempfile
from typing import Any, Dict

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

class RecursiveParentRendererWrapper:
    def __init__(self, real_renderer, dataset_path):
        self.real_renderer = real_renderer
        self.dataset_path = dataset_path

    def __getattr__(self, name):
        return getattr(self.real_renderer, name)

    def render(self, level, x, y):
        # 1. Ensure parent exists if level > 0
        if level > 0:
            parent_level = level - 1
            parent_x = x // 2
            parent_y = y // 2
            
            parent_dir = os.path.join(self.dataset_path, str(parent_level), str(parent_x))
            parent_path = os.path.join(parent_dir, f"{parent_y}{TILE_EXTENSION}")
            
            # Check if parent exists
            if not os.path.exists(parent_path):
                # Recursive call to generate parent
                parent_img = self.render(parent_level, parent_x, parent_y)
                
                os.makedirs(parent_dir, exist_ok=True)
                
                # Atomic Write Pattern to prevent race conditions
                try:
                    # Create temp file in the same dir to ensure same filesystem (for rename)
                    fd, temp_path = tempfile.mkstemp(dir=parent_dir, suffix=TILE_EXTENSION)
                    os.close(fd)
                    
                    parent_img.save(temp_path, format=TILE_FORMAT, **TILE_WEBP_PARAMS)
                    
                    # Atomic replace
                    os.replace(temp_path, parent_path)
                except OSError as e:
                    # Clean up temp file if it still exists
                    if 'temp_path' in locals() and os.path.exists(temp_path):
                        os.remove(temp_path)
                    
                    # If rename failed because another thread beat us to it (target exists), that's fine.
                    # Otherwise, re-raise the error.
                    if not os.path.exists(parent_path):
                        raise e

        # 2. Render actual tile
        return self.real_renderer.render(level, x, y)

def load_renderer(renderer_path: str, tile_size: int, renderer_kwargs: Dict[str, Any], dataset_path: str = None):
    """
    Load and instantiate a renderer class given a module path string of the form
    'module.submodule:ClassName' or 'module.submodule.ClassName'.
    
    If dataset_path is provided, wraps the renderer to enforce recursive parent generation.
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

