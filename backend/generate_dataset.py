import argparse
import importlib
import inspect
import json
import os
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Dict

# Add project root to path to find renderers
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import camera_utils

DATA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

_renderer_instance = None

def ensure_dirs(path):
    os.makedirs(path, exist_ok=True)

def _init_renderer_worker(renderer):
    """Initializer for ProcessPool workers; shares the renderer instance via pickling."""
    global _renderer_instance
    _renderer_instance = renderer


def _render_tile(args):
    level, x, y, base_path = args

    level_path = os.path.join(base_path, str(level), str(x))
    ensure_dirs(level_path)
    img_path = os.path.join(level_path, f"{y}.png")

    if os.path.exists(img_path):
        return False

    if _renderer_instance is None:
        raise RuntimeError("Renderer instance not initialized in worker")

    img = _renderer_instance.render(level, x, y)
    img.save(img_path)
    return True

def update_index(dataset_id, name, description):
    index_path = os.path.join(DATA_ROOT, 'datasets', 'index.json')
    ensure_dirs(os.path.dirname(index_path))
    
    data = {"datasets": []}
    if os.path.exists(index_path):
        try:
            with open(index_path, 'r') as f:
                data = json.load(f)
        except json.JSONDecodeError:
            pass
    
    # Update or Append
    found = False
    for ds in data['datasets']:
        if ds['id'] == dataset_id:
            ds['name'] = name
            ds['description'] = description
            found = True
            break
    
    if not found:
        data['datasets'].append({
            "id": dataset_id,
            "name": name,
            "description": description
        })
        
    with open(index_path, 'w') as f:
        json.dump(data, f, indent=2)

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


def load_paths(dataset_id: str):
    """Load camera paths for a dataset; assumes the JSON file already exists."""
    path_file = os.path.join(DATA_ROOT, 'datasets', dataset_id, 'paths.json')
    if not os.path.exists(path_file):
        raise FileNotFoundError(f"paths.json not found for dataset '{dataset_id}' at {path_file}")

    with open(path_file, 'r') as f:
        data = json.load(f)

    paths = data.get('paths', [])
    if not isinstance(paths, list):
        raise ValueError(f"paths.json for dataset '{dataset_id}' must contain a list under the 'paths' key.")
    return paths

def generate_full_pyramid(renderer, dataset_id, max_level):
    base_path = os.path.join(DATA_ROOT, 'datasets', dataset_id, 'tiles')
    
    for level in range(max_level + 1):
        num_tiles = 2 ** level
        print(f"Generating Level {level} ({num_tiles}x{num_tiles} tiles)...")
        
        level_path = os.path.join(base_path, str(level))
        ensure_dirs(level_path)
        
        for x in range(num_tiles):
            x_path = os.path.join(level_path, str(x))
            ensure_dirs(x_path)
            for y in range(num_tiles):
                img = renderer.render(level, x, y)
                img_path = os.path.join(x_path, f"{y}.png")
                img.save(img_path)

import camera_utils

def generate_tiles_along_path(renderer, dataset_id, paths, margin=1, steps=2000):
    print(f"Generating tiles along paths for {dataset_id}...")
    base_path = os.path.join(DATA_ROOT, 'datasets', dataset_id, 'tiles')
    
    required_tiles = set()  # (level, x, y)
    
    for path_obj in paths:
        keyframes = path_obj.get('keyframes', [])
        if len(keyframes) < 2:
            continue

        progresses = [s / steps for s in range(steps + 1)]
        camera_utils.set_camera_path(path_obj, internal_resolution=max(steps, 2000), tension=0.0)
        cams = camera_utils.cameras_at_progresses(progresses)
        for cam in cams:
            if cam is None:
                continue
            visible = camera_utils.get_visible_tiles(cam, margin=margin)
            required_tiles.update(visible)

    print(f"Identified {len(required_tiles)} unique tiles to generate.")
    
    tasks = []
    for (level, x, y) in required_tiles:
        img_path = os.path.join(base_path, str(level), str(x), f"{y}.png")
        if not os.path.exists(img_path):
            tasks.append((level, x, y, base_path))

    tasks.sort(key=lambda t: (t[0], t[1], t[2]))

    if not tasks:
        print("No new tiles needed for path mode.")
        return 0

    generated = 0
    
    use_multiprocessing = True
    if hasattr(renderer, 'supports_multithreading') and not renderer.supports_multithreading():
        use_multiprocessing = False
        print("Renderer does not support multithreading. Switching to single-process mode.")

    if use_multiprocessing:
        print(f"Rendering {len(tasks)} missing tiles with 8 workers...")
        try:
            with ProcessPoolExecutor(max_workers=8, initializer=_init_renderer_worker, initargs=(renderer,)) as executor:
                for idx, created in enumerate(executor.map(_render_tile, tasks), 1):
                    if idx % 100 == 0:
                        print(f"Rendering {idx}/{len(tasks)}...")
                    if created:
                        generated += 1
        except Exception as e:
            print(f"Parallel rendering failed ({e}); falling back to single-process mode...")
            use_multiprocessing = False

    if not use_multiprocessing:
        print(f"Rendering {len(tasks)} tiles in single process...")
        _init_renderer_worker(renderer)
        for idx, task in enumerate(tasks, 1):
            created = _render_tile(task)
            if idx % 100 == 0:
                print(f"Rendering {idx}/{len(tasks)}...")
            if created:
                generated += 1
    
    print(f"Path generation complete. Generated {generated} tiles.")
    return generated


def main():
    parser = argparse.ArgumentParser(description="Generate datasets for Ultra-Resolution Quads")
    parser.add_argument('--dataset', required=True, help='Dataset ID (e.g. debug_quadtile, mandelbrot_deep)')
    parser.add_argument('--renderer', required=True, help='Renderer class path, e.g. renderers.mandelbrot_renderer:MandelbrotDeepZoomRenderer')
    parser.add_argument('--renderer_args', default="{}", help='JSON dict of kwargs passed to the renderer constructor')
    parser.add_argument('--name', default=None, help='Dataset display name (defaults to dataset id)')
    parser.add_argument('--description', default="", help='Dataset description')
    parser.add_argument('--max_level', type=int, default=4, help='Max level to generate')
    parser.add_argument('--mode', choices=['full', 'path'], default='path', help='Generation mode')
    parser.add_argument('--tile_size', type=int, default=512, help='Tile size (pixels) for generated tiles (used if renderer supports it)')
    
    args = parser.parse_args()

    try:
        renderer_kwargs = json.loads(args.renderer_args)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON passed to --renderer_args: {exc}") from exc

    if renderer_kwargs is not None and not isinstance(renderer_kwargs, dict):
        raise SystemExit("--renderer_args must decode to a JSON object (dictionary).")

    renderer = load_renderer(args.renderer, args.tile_size, renderer_kwargs)

    config_path = os.path.join(DATA_ROOT, 'datasets', args.dataset, 'config.json')
    existing_name = None
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                existing_config = json.load(f)
                existing_name = existing_config.get('name')
        except (OSError, json.JSONDecodeError):
            existing_name = None

    name = args.name or existing_name or args.dataset
    desc = args.description or ""

    print(f"Initializing dataset: {args.dataset}")
    update_index(args.dataset, name, desc)
    # Config is saved at the end after determining actual max_level
    
    paths_data = None
    if args.mode == 'path':
        paths_data = load_paths(args.dataset)
    
    tiles_root = os.path.join(DATA_ROOT, 'datasets', args.dataset, 'tiles')
    # Clear previous tiles so each run is fresh
    if os.path.exists(tiles_root):
        shutil.rmtree(tiles_root)

    print(f"Mode: {args.mode}")
    if args.mode == 'full':
        print("Generating FULL pyramid (all tiles)...")
        total_tiles = sum((2 ** level) ** 2 for level in range(args.max_level + 1))
        start_time = time.time()
        generate_full_pyramid(renderer, args.dataset, args.max_level)
        elapsed = time.time() - start_time
        avg = elapsed / total_tiles if total_tiles else 0.0
        # File size stats
        file_count = 0
        total_bytes = 0
        for root, _, files in os.walk(tiles_root):
            for fname in files:
                if fname.lower().endswith('.png'):
                    file_count += 1
                    total_bytes += os.path.getsize(os.path.join(root, fname))
        avg_size = total_bytes / file_count if file_count else 0.0
        avg_kb = avg_size / 1024.0
        print(f"Stats: tiles={total_tiles}, total_time={elapsed:.3f}s, avg_per_tile={avg*1000:.2f}ms, avg_file_size={avg_kb:.2f}KB, path={tiles_root}")
    else:
        print("Generating tiles along PATH...")
        # If mode is path, we pull the generated paths to guide the renderer
        start_time = time.time()
        generated = generate_tiles_along_path(renderer, args.dataset, paths_data)
        elapsed = time.time() - start_time
        avg = elapsed / generated if generated else 0.0
        # File size stats (all tiles for this dataset after run)
        file_count = 0
        total_bytes = 0
        for root, _, files in os.walk(tiles_root):
            for fname in files:
                if fname.lower().endswith('.png'):
                    file_count += 1
                    total_bytes += os.path.getsize(os.path.join(root, fname))
        avg_size = total_bytes / file_count if file_count else 0.0
        avg_kb = avg_size / 1024.0
        print(f"Stats: tiles_generated={generated}, total_time={elapsed:.3f}s, avg_per_tile={avg*1000:.2f}ms, avg_file_size={avg_kb:.2f}KB, path={tiles_root}")
        
    print(f"Saving config...")
    path = os.path.join(DATA_ROOT, 'datasets', args.dataset, 'config.json')
    ensure_dirs(os.path.dirname(path))
    with open(path, 'w') as f:
        json.dump({
            "id": args.dataset,
            "name": name,
            "tile_size": args.tile_size
        }, f, indent=2)

    print("Done.")

if __name__ == "__main__":
    main()
