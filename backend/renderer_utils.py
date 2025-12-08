import importlib
import inspect
import os
from typing import Any, Dict

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

def load_renderer(renderer_path: str, tile_size: int, renderer_kwargs: Dict[str, Any]):
    """
    Load and instantiate a renderer class given a module path string of the form
    'module.submodule:ClassName' or 'module.submodule.ClassName'.
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
        return renderer_cls(**kwargs)
    except TypeError as exc:
        raise TypeError(f"Failed to instantiate renderer '{renderer_path}' with args {kwargs}: {exc}") from exc
