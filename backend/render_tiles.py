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

from PIL import Image

# Add project root to path to find renderers
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import camera_utils

DATA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

_renderer_instance = None

def ensure_dirs(path):
    os.makedirs(path, exist_ok=True)

def tiles_base_path(dataset_id, tile_size):
    """
    Return the root path for tiles. 
    Now simply the dataset directory, as we no longer nest under 'tiles/size'.
    """
    return os.path.join(DATA_ROOT, 'datasets', dataset_id)

def clean_existing_tiles(dataset_dir):
    """
    Remove only the level directories (integer names) within the dataset directory.
    Preserves config.json, paths.json, etc.
    """
    if not os.path.exists(dataset_dir):
        return
        
    print(f"Cleaning tiles in {dataset_dir}...")
    for item in os.listdir(dataset_dir):
        item_path = os.path.join(dataset_dir, item)
        if os.path.isdir(item_path) and item.isdigit():
            shutil.rmtree(item_path)

def check_and_clean_if_needed(dataset_dir, target_tile_size):
    """
    Check if existing tiles match the target size. If not, clean them.
    """
    if not os.path.exists(dataset_dir):
        return

    # Find any existing tile to check its size
    found_tile = None
    for item in os.listdir(dataset_dir):
        level_dir = os.path.join(dataset_dir, item)
        if os.path.isdir(level_dir) and item.isdigit():
            # Look inside a level directory
            for x_name in os.listdir(level_dir):
                x_dir = os.path.join(level_dir, x_name)
                if os.path.isdir(x_dir):
                    for f in os.listdir(x_dir):
                        if f.endswith('.png'):
                            found_tile = os.path.join(x_dir, f)
                            break
                if found_tile: break
        if found_tile: break
    
    if found_tile:
        try:
            with Image.open(found_tile) as img:
                w, h = img.size
                if w != target_tile_size or h != target_tile_size:
                    print(f"Found existing tiles with size {w}x{h}, but target is {target_tile_size}x{target_tile_size}.")
                    print("Triggering clean rebuild...")
                    clean_existing_tiles(dataset_dir)
                else:
                    # Sizes match, nothing to do
                    pass
        except Exception as e:
            print(f"Warning: could not check existing tile size: {e}")
            # If we can't read it, maybe safe to ignore or force clean? 
            # Let's assume ignore for now unless it causes issues.
            pass

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

def render_tasks(renderer, tasks):
    """Render a list of (level, x, y, base_path) tasks, skipping those already present."""
    if not tasks:
        print("No new tiles needed.")
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
    
    print(f"Rendering complete. Generated {generated} tiles.")
    return generated

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

def generate_full_pyramid(renderer, base_path, max_level):
    tasks = []
    total_tiles = 0
    for level in range(max_level + 1):
        num_tiles = 2 ** level
        total_tiles += num_tiles * num_tiles
        level_path = os.path.join(base_path, str(level))
        ensure_dirs(level_path)
        for x in range(num_tiles):
            x_path = os.path.join(level_path, str(x))
            ensure_dirs(x_path)
            for y in range(num_tiles):
                img_path = os.path.join(x_path, f"{y}.png")
                if not os.path.exists(img_path):
                    tasks.append((level, x, y, base_path))
    tasks.sort(key=lambda t: (t[0], t[1], t[2]))
    if tasks:
        print(f"Full mode: {len(tasks)} / {total_tiles} tiles missing; rendering now...")
    else:
        print("Full mode: all tiles already present; nothing to do.")
    generated = render_tasks(renderer, tasks)
    return generated, total_tiles, len(tasks)

def generate_tiles_along_path(renderer, base_path, dataset_id, paths, steps=2000):
    print(f"Generating tiles along paths for {dataset_id}...")
    required_tiles = set()  # (level, x, y)
    
    for path_obj in paths:
        keyframes = path_obj.get('keyframes', [])
        if len(keyframes) < 2:
            continue

        progresses = [s / steps for s in range(steps + 1)]
        camera_utils.set_camera_path(path_obj, internal_resolution=max(steps, 2000), tension=0.0)
        
        # New API returns (cameras, tiles) directly from the shared JS logic
        cams, tiles = camera_utils.cameras_at_progresses(progresses)
        
        # Add the tiles identified by the shared logic
        for t in tiles:
            required_tiles.add((t['level'], t['x'], t['y']))

    print(f"Identified {len(required_tiles)} unique tiles to generate.")
    
    tasks = []
    for (level, x, y) in required_tiles:
        img_path = os.path.join(base_path, str(level), str(x), f"{y}.png")
        if not os.path.exists(img_path):
            tasks.append((level, x, y, base_path))

    tasks.sort(key=lambda t: (t[0], t[1], t[2]))
    if tasks:
        print(f"Path mode: {len(tasks)} new tiles to render (of {len(required_tiles)} unique).")
    else:
        print("Path mode: all required tiles already present; nothing to do.")
    generated = render_tasks(renderer, tasks)
    return generated


def main():
    parser = argparse.ArgumentParser(description="Render tiles for Ultra-Resolution Quads datasets")
    parser.add_argument('--dataset', required=False, help='Dataset ID (e.g. debug_quadtile, mandelbrot_deep). If not provided, all datasets will be rendered.')
    parser.add_argument('--renderer', required=False, default=None, help='Renderer path override (e.g. renderers.mandelbrot_renderer:MandelbrotRenderer). Defaults to renderer in datasets/{id}/config.json')
    parser.add_argument('--renderer_args', default="{}", help='JSON dict of kwargs passed to the renderer constructor')
    parser.add_argument('--max_level', type=int, default=4, help='Max level to generate for "full" mode')
    parser.add_argument('--mode', choices=['full', 'path'], default='path', help='Generation mode')
    parser.add_argument('--rebuild', action='store_true', help='Delete existing tiles for the dataset(s) before rendering')
    
    args = parser.parse_args()

    try:
        renderer_kwargs = json.loads(args.renderer_args)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON passed to --renderer_args: {exc}") from exc

    if renderer_kwargs is not None and not isinstance(renderer_kwargs, dict):
        raise SystemExit("--renderer_args must decode to a JSON object (dictionary).")

    datasets_to_render = []
    if args.dataset:
        datasets_to_render.append(args.dataset)
    else:
        datasets_dir = os.path.join(DATA_ROOT, 'datasets')
        for item in sorted(os.listdir(datasets_dir)):
            if os.path.isdir(os.path.join(datasets_dir, item)):
                datasets_to_render.append(item)

    for dataset_id in datasets_to_render:
        print(f"Processing dataset: {dataset_id}")

        # Load dataset config to get tile_size
        config_path = os.path.join(DATA_ROOT, 'datasets', dataset_id, 'config.json')
        if not os.path.exists(config_path):
            print(f"Skipping dataset '{dataset_id}': config.json not found at: {config_path}")
            continue

        with open(config_path, 'r') as f:
            dataset_config = json.load(f)

        renderer_path = args.renderer or dataset_config.get('renderer')
        if not renderer_path:
            print(f"Skipping dataset '{dataset_id}': renderer not provided via --renderer and not found in config.json")
            continue

        tile_size = dataset_config.get('tile_size', 512)

        config_renderer_args = dataset_config.get('renderer_args') if isinstance(dataset_config, dict) else {}
        merged_renderer_kwargs = {}
        if isinstance(config_renderer_args, dict):
            merged_renderer_kwargs.update(config_renderer_args)
        merged_renderer_kwargs.update(renderer_kwargs)

        # Determine output path (now directly in dataset dir)
        dataset_tiles_root = tiles_base_path(dataset_id, tile_size)
        
        if args.rebuild:
            clean_existing_tiles(dataset_tiles_root)
        else:
            # Auto-detect mismatch
            check_and_clean_if_needed(dataset_tiles_root, tile_size)

        renderer = load_renderer(renderer_path, tile_size, merged_renderer_kwargs)

        print(f"Initializing dataset: {dataset_id}")
        
        paths_data = None
        if args.mode == 'path':
            try:
                paths_data = load_paths(dataset_id)
            except (FileNotFoundError, ValueError) as exc:
                print(f"Skipping dataset '{dataset_id}' in path mode: {exc}")
                continue

        print(f"Mode: {args.mode}")
        if args.mode == 'full':
            print("Generating FULL pyramid (all tiles)...")
            start_time = time.time()
            generated, total_tiles, missing = generate_full_pyramid(renderer, dataset_tiles_root, args.max_level)
            elapsed = time.time() - start_time
            avg = elapsed / generated if generated else 0.0
            # File size stats
            file_count = 0
            total_bytes = 0
            for root, _, files in os.walk(dataset_tiles_root):
                for fname in files:
                    if fname.lower().endswith('.png'):
                        file_count += 1
                        total_bytes += os.path.getsize(os.path.join(root, fname))
            avg_size = total_bytes / file_count if file_count else 0.0
            avg_kb = avg_size / 1024.0
            print(f"Stats: generated={generated}, requested_missing={missing}, total_possible={total_tiles}, total_time={elapsed:.3f}s, avg_per_tile={avg*1000:.2f}ms, avg_file_size={avg_kb:.2f}KB, path={dataset_tiles_root}")
        else:
            print("Generating tiles along PATH...")
            start_time = time.time()
            generated = generate_tiles_along_path(renderer, dataset_tiles_root, dataset_id, paths_data)
            elapsed = time.time() - start_time
            avg = elapsed / generated if generated else 0.0
            # File size stats
            file_count = 0
            total_bytes = 0
            for root, _, files in os.walk(dataset_tiles_root):
                for fname in files:
                    if fname.lower().endswith('.png'):
                        file_count += 1
                        total_bytes += os.path.getsize(os.path.join(root, fname))
            avg_size = total_bytes / file_count if file_count else 0.0
            avg_kb = avg_size / 1024.0
            print(f"Stats: tiles_generated={generated}, total_time={elapsed:.3f}s, avg_per_tile={avg*1000:.2f}ms, avg_file_size={avg_kb:.2f}KB, path={dataset_tiles_root}")
            
    print("Done.")

if __name__ == "__main__":
    main()
