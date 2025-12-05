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

TILE_EXTENSION = ".webp"
TILE_FORMAT = "WEBP"
# Match the "medium" WebP settings used in experiments/compare_image_quality.py
TILE_WEBP_PARAMS = {"quality": 85, "method": 6}

# Add project root to path to find renderers
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import camera_utils

DATA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

_renderer_instance = None

def ensure_dirs(path):
    os.makedirs(path, exist_ok=True)

def make_tile_path(base_path, level, x, y):
    return os.path.join(base_path, str(level), str(x), f"{y}{TILE_EXTENSION}")

def parse_tiles_arg(tile_str):
    """
    Parse a comma-separated list of tiles specified as 'level/x/y' or 'level:x:y'.
    Returns a list of (level, x, y) tuples.
    """
    tiles = []
    if not tile_str:
        return tiles
    parts = tile_str.split(",")
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if "/" in p:
            l, x, y = p.split("/")
        elif ":" in p:
            l, x, y = p.split(":")
        else:
            raise ValueError(f"Invalid tile format '{p}'. Use level/x/y or level:x:y")
        tiles.append((int(l), int(x), int(y)))
    return tiles

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
                        if f.endswith(TILE_EXTENSION):
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
    try:
        os.nice(10)  # Set a lower priority for worker processes
    except AttributeError:
        # os.nice is not available on all operating systems (e.g., Windows)
        pass


def _render_tile(args):
    t0 = time.time()
    level, x, y, base_path = args

    img_path = make_tile_path(base_path, level, x, y)
    ensure_dirs(os.path.dirname(img_path))

    if os.path.exists(img_path):
        return False, 0.0

    if _renderer_instance is None:
        raise RuntimeError("Renderer instance not initialized in worker")

    img = _renderer_instance.render(level, x, y)
    img.save(img_path, format=TILE_FORMAT, **TILE_WEBP_PARAMS)
    return True, time.time() - t0

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
    # print(f"Updated tile manifest at {manifest_path} ({len(tiles)} tiles)")

def render_tasks(renderer, tasks, dataset_dir=None, use_multiprocessing=True, num_workers=8):
    """Render a list of (level, x, y, base_path) tasks, skipping those already present."""
    if not tasks:
        print("No new tiles needed.")
        return 0

    generated = 0
    last_update_time = time.time()
    batch_duration = 0.0
    batch_count = 0
    
    # Fallback check if method exists on renderer (legacy)
    if use_multiprocessing and hasattr(renderer, 'supports_multithreading') and not renderer.supports_multithreading():
        use_multiprocessing = False
        print("Renderer does not support multithreading. Switching to single-process mode.")
    
    # Explicit config override message
    if not use_multiprocessing and hasattr(renderer, 'supports_multithreading') and renderer.supports_multithreading():
         print("Multithreading disabled by configuration.")

    def _process_progress(idx, total):
        nonlocal last_update_time, batch_duration, batch_count
        now = time.time()
        if now - last_update_time > 60:
            avg = batch_duration / batch_count if batch_count > 0 else 0.0
            print(f"Rendering {idx}/{total}... Avg generation (last {batch_count}): {avg:.2f}s")
            
            # Periodically update the manifest so the frontend can see progress live
            if dataset_dir:
                generate_tile_manifest(dataset_dir)
            
            last_update_time = now
            batch_duration = 0.0
            batch_count = 0

    if use_multiprocessing:
        workers = num_workers if num_workers and num_workers > 0 else 8
        print(f"Rendering {len(tasks)} missing tiles with {workers} workers...")
        try:
            with ProcessPoolExecutor(max_workers=workers, initializer=_init_renderer_worker, initargs=(renderer,)) as executor:
                for idx, (created, duration) in enumerate(executor.map(_render_tile, tasks), 1):
                    if created:
                        generated += 1
                    
                    batch_duration += duration
                    batch_count += 1
                    _process_progress(idx, len(tasks))

        except Exception as e:
            print(f"Parallel rendering failed ({e}); falling back to single-process mode...")
            use_multiprocessing = False

    if not use_multiprocessing:
        print(f"Rendering {len(tasks)} tiles in single process...")
        _init_renderer_worker(renderer)
        for idx, task in enumerate(tasks, 1):
            created, duration = _render_tile(task)
            if created:
                generated += 1
            
            batch_duration += duration
            batch_count += 1
            _process_progress(idx, len(tasks))
    
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



def generate_full_pyramid(renderer, base_path, max_level, use_multiprocessing=True, num_workers=8):
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
                img_path = make_tile_path(base_path, level, x, y)
                if not os.path.exists(img_path):
                    tasks.append((level, x, y, base_path))
    tasks.sort(key=lambda t: (t[0], t[1], t[2]))
    if tasks:
        print(f"Full mode: {len(tasks)} / {total_tiles} tiles missing; rendering now...")
    else:
        print("Full mode: all tiles already present; nothing to do.")
    generated = render_tasks(renderer, tasks, dataset_dir=base_path, use_multiprocessing=use_multiprocessing, num_workers=num_workers)
    return generated, total_tiles, len(tasks)


def generate_selected_tiles(renderer, base_path, tiles, use_multiprocessing=True, num_workers=8):
    """
    Render only the explicitly provided tiles (list of (level, x, y)).
    """
    tasks = []
    for (level, x, y) in tiles:
        level_path = os.path.join(base_path, str(level))
        x_path = os.path.join(level_path, str(x))
        ensure_dirs(x_path)
        img_path = make_tile_path(base_path, level, x, y)
        if not os.path.exists(img_path):
            tasks.append((level, x, y, base_path))
    tasks.sort(key=lambda t: (t[0], t[1], t[2]))
    if tasks:
        print(f"Selected tiles: {len(tasks)} / {len(tiles)} missing; rendering now...")
    else:
        print("Selected tiles: all requested tiles already present; nothing to do.")
    generated = render_tasks(renderer, tasks, dataset_dir=base_path, use_multiprocessing=use_multiprocessing, num_workers=num_workers)
    return generated, len(tiles), len(tasks)

def generate_tiles_along_path(renderer, base_path, dataset_id, path, steps=2000, use_multiprocessing=True, num_workers=8, viewport_width=1920, viewport_height=1080):
    if not path:
        print(f"No path defined for {dataset_id}; skipping path-based generation.")
        return 0

    keyframes = path.get('keyframes', [])
    if len(keyframes) < 2:
        print(f"Path for {dataset_id} has fewer than 2 keyframes; skipping.")
        return 0

    print(f"Generating tiles along path for {dataset_id} (Viewport: {viewport_width}x{viewport_height})...")
    required_tiles = set()  # (level, x, y)

    progresses = [s / steps for s in range(steps + 1)]
    # Note: tile_size here refers to the LOGICAL size used for visibility calculations (usually 512 in frontend).
    # The physical tile_size from config is used by the renderer.
    # If we passed the smaller physical size (e.g. 256), the visibility logic would request MORE tiles.
    
    # NOTE: We use parallel camera sampling because calculating visible tiles for 2000 frames 
    # with high-precision Decimal math in Node.js is slow (can take 10+ mins).
    # We use the same number of workers as for rendering.
    cams, tiles = camera_utils.cameras_at_progresses_parallel(
        progresses, path, viewport_width, viewport_height, 512, 
        num_workers=num_workers
    )
    
    # Add the tiles identified by the shared logic
    for t in tiles:
        required_tiles.add((t['level'], t['x'], t['y']))

    print(f"Identified {len(required_tiles)} unique tiles to generate.")
    
    tasks = []
    for (level, x, y) in required_tiles:
        img_path = make_tile_path(base_path, level, x, y)
        if not os.path.exists(img_path):
            tasks.append((level, x, y, base_path))

    tasks.sort(key=lambda t: (t[0], t[1], t[2]))
    if tasks:
        print(f"Path mode: {len(tasks)} new tiles to render (of {len(required_tiles)} unique).")
    else:
        print("Path mode: all required tiles already present; nothing to do.")
    generated = render_tasks(renderer, tasks, dataset_dir=base_path, use_multiprocessing=use_multiprocessing, num_workers=num_workers)
    return generated


def main():
    parser = argparse.ArgumentParser(description="Render tiles for Ultra-Resolution Quads datasets")
    parser.add_argument('--dataset', required=False, help='Dataset ID (e.g. debug_quadtile, mandelbrot_single_precision). If not provided, all datasets will be rendered.')
    parser.add_argument('--renderer_args', default="{}", help='JSON dict of kwargs passed to the renderer constructor')
    parser.add_argument('--max_level', type=int, default=None, help='Max level to generate for "full" mode (defaults to config or 4)')
    parser.add_argument('--mode', choices=['full', 'path'], default=None, help='Generation mode (defaults to config or "path")')
    parser.add_argument('--rebuild', action='store_true', help='Delete existing tiles for the dataset(s) before rendering')
    parser.add_argument('--tiles', default=None, help="Optional comma-separated list of tiles to render, formatted as level/x/y (e.g., '0/0/0,1/0/1'). When provided, overrides mode/max_level and renders only these tiles.")
    parser.add_argument('--workers', type=int, default=None, help="Optional number of workers for multiprocessing (>=2). Use 1 to force single-process.")
    parser.add_argument('--viewport_width', type=int, default=1920, help='Viewport width for path visibility calculation (default 1920)')
    parser.add_argument('--viewport_height', type=int, default=1080, help='Viewport height for path visibility calculation (default 1080)')
    
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

        renderer_path = dataset_config.get('renderer')
        if not renderer_path:
            print(f"Skipping dataset '{dataset_id}': renderer not found in config.json")
            continue

        # Determine render configuration (CLI > Config > Default)
        render_config = dataset_config.get('render_config', {})
        
        mode = args.mode
        if mode is None:
            mode = render_config.get('mode', 'path')
            
        max_level = args.max_level
        if max_level is None:
            max_level = render_config.get('max_level', 4)

        tile_size = dataset_config.get('tile_size', 512)
        supports_multithreading = dataset_config.get('supports_multithreading', True)

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
            
        # Initial manifest update to catch up on any previous state (e.g. interrupted run)
        print(f"Generating initial tile manifest for {dataset_id}...")
        generate_tile_manifest(dataset_tiles_root)

        renderer = load_renderer(renderer_path, tile_size, merged_renderer_kwargs)

        print(f"Initializing dataset: {dataset_id}")
        
        path_data = None
        if mode == 'path':
            path_data = render_config.get('path')
            if not path_data:
                print(f"Warning: Dataset '{dataset_id}' is in 'path' mode but no 'path' object found in render_config.")
                # We continue, generated might be 0 if path is empty

        # Decide rendering strategy
        explicit_tiles = parse_tiles_arg(args.tiles) if args.tiles else []
        num_workers = args.workers if args.workers is not None else 8
        use_multiprocessing = supports_multithreading and (num_workers != 1)

        if explicit_tiles:
            print(f"Rendering explicit tiles: {explicit_tiles}")
            start_time = time.time()
            generated, total_tiles, missing = generate_selected_tiles(
                renderer, dataset_tiles_root, explicit_tiles, use_multiprocessing=use_multiprocessing, num_workers=num_workers
            )
            elapsed = time.time() - start_time
            avg = elapsed / generated if generated else 0.0
        elif mode == 'full':
            print(f"Mode: full | max_level={max_level}")
            start_time = time.time()
            generated, total_tiles, missing = generate_full_pyramid(renderer, dataset_tiles_root, max_level, use_multiprocessing=use_multiprocessing, num_workers=num_workers)
            elapsed = time.time() - start_time
            avg = elapsed / generated if generated else 0.0
        else:
            print("Mode: path")
            start_time = time.time()
            generated = generate_tiles_along_path(
                renderer, dataset_tiles_root, dataset_id, path_data, 
                use_multiprocessing=use_multiprocessing, num_workers=num_workers,
                viewport_width=args.viewport_width, viewport_height=args.viewport_height
            )
            elapsed = time.time() - start_time
            avg = elapsed / generated if generated else 0.0
            total_tiles = None
            missing = None
            
        # Final manifest update
        print(f"Updating final tile manifest for {dataset_id}...")
        generate_tile_manifest(dataset_tiles_root)

        # File size stats
        file_count = 0
        total_bytes = 0
        for root, _, files in os.walk(dataset_tiles_root):
            for fname in files:
                if fname.lower().endswith(TILE_EXTENSION):
                    file_count += 1
                    total_bytes += os.path.getsize(os.path.join(root, fname))
        avg_size = total_bytes / file_count if file_count else 0.0
        avg_kb = avg_size / 1024.0

        if explicit_tiles:
            print(f"Stats: generated={generated}, requested_missing={missing}, requested_total={total_tiles}, total_time={elapsed:.3f}s, avg_per_tile={avg*1000:.2f}ms, avg_file_size={avg_kb:.2f}KB, path={dataset_tiles_root}")
        elif mode == 'full':
            print(f"Stats: generated={generated}, requested_missing={missing}, total_possible={total_tiles}, total_time={elapsed:.3f}s, avg_per_tile={avg*1000:.2f}ms, avg_file_size={avg_kb:.2f}KB, path={dataset_tiles_root}")
        else:
            print(f"Stats: tiles_generated={generated}, total_time={elapsed:.3f}s, avg_per_tile={avg*1000:.2f}ms, avg_file_size={avg_kb:.2f}KB, path={dataset_tiles_root}")
            
    print("Done.")

if __name__ == "__main__":
    main()
