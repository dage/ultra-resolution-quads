import argparse
import importlib
import inspect
import json
import os
import shutil
import sys
import time
import multiprocessing
import resource
import gc
from typing import Any, Dict, Optional, Tuple

from PIL import Image

# Add project root to path to find renderers and constants
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.constants import TILE_EXTENSION, TILE_FORMAT, TILE_WEBP_PARAMS
from backend.renderer_utils import load_renderer, format_time, generate_tile_manifest
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

def _init_renderer_worker_from_config(renderer_path, tile_size, renderer_kwargs, dataset_path):
    """
    Initializer that instantiates the renderer from config in the worker process.
    This avoids pickling large renderer instances and ensures a fresh state.
    """
    global _renderer_instance
    try:
        os.nice(10)
    except AttributeError:
        pass
    
    # Import locally to ensure availability
    from backend.renderer_utils import load_renderer
    try:
        _renderer_instance = load_renderer(renderer_path, tile_size, renderer_kwargs, dataset_path)
    except Exception as e:
        print(f"Error initializing renderer in worker: {e}", file=sys.stderr)
        raise

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

def render_tasks(renderer_instance, tasks, dataset_dir=None, num_workers=8, renderer_config=None):
    """
    Render a list of (level, x, y, base_path) tasks.
    
    Args:
        renderer_instance: The instantiated renderer object (used for main-process debug mode or pickling fallback).
        tasks: List of task tuples.
        dataset_dir: Path to dataset root (for updating manifest).
        num_workers: Number of workers. 
                     If > 0: Uses multiprocessing.Pool (even for 1).
                     If 0: Runs in main process (for debugging).
        renderer_config: Tuple (path, tile_size, kwargs, dataset_path) to instantiate renderer in workers.
    """
    if not tasks:
        print("No new tiles needed.")
        return 0

    generated = 0
    last_update_time = time.time()
    batch_duration = 0.0
    batch_count = 0
    
    # Determine mode
    run_in_pool = True
    if num_workers == 0:
        run_in_pool = False
        print("Workers set to 0: Switching to IN-PROCESS execution (Debug Mode).")
    
    # Check regarding renderer support (legacy check)
    if run_in_pool and hasattr(renderer_instance, 'supports_multithreading') and not renderer_instance.supports_multithreading() and num_workers > 1:
        print(f"Renderer requests single-threading. Forcing workers=1 (still using Pool for memory safety).")
        num_workers = 1

    def _process_progress(idx, total):
        nonlocal last_update_time, batch_count, batch_duration
        now = time.time()
        wall_elapsed = now - last_update_time
        
        if wall_elapsed > 60:
            # Calculate effective speed (wall clock time)
            avg_wall_per_tile = wall_elapsed / batch_count if batch_count > 0 else 0.0
            
            remaining = total - idx
            eta_seconds = remaining * avg_wall_per_tile
            eta_str = format_time(eta_seconds)
            
            # Simple progress output without memory or verbose stats
            print(f"Rendering {idx}/{total}. {avg_wall_per_tile:.2f}s/tile. ETA: {eta_str}", flush=True)
            
            # Periodically update the manifest
            if dataset_dir:
                generate_tile_manifest(dataset_dir)
            
            last_update_time = now
            batch_count = 0
            batch_duration = 0.0

    if run_in_pool:
        # Ensure we have at least 1 worker if we are in pool mode
        pool_size = max(1, num_workers)
        print(f"Rendering {len(tasks)} missing tiles with {pool_size} workers (Process Pool)...")
        
        if renderer_config:
            # Preferred: Instantiate fresh renderer in worker
            pool = multiprocessing.Pool(
                processes=pool_size, 
                initializer=_init_renderer_worker_from_config, 
                initargs=renderer_config, 
                maxtasksperchild=50
            )
        else:
            # Fallback: Pickle the existing instance
            print("Warning: renderer_config not provided, pickling renderer instance (less robust).")
            pool = multiprocessing.Pool(
                processes=pool_size, 
                initializer=_init_renderer_worker, 
                initargs=(renderer_instance,),
                maxtasksperchild=50
            )

        try:
            for idx, (created, duration) in enumerate(pool.imap_unordered(_render_tile, tasks), 1):
                if created:
                    generated += 1
                
                batch_duration += duration
                batch_count += 1
                _process_progress(idx, len(tasks))
            
            pool.close()
            pool.join()

        except KeyboardInterrupt:
            print("\nInterrupted by user. Terminating workers...")
            pool.terminate()
            pool.join()
            sys.exit(1)

        except Exception as e:
            print(f"Pool rendering failed ({e}); terminating...")
            pool.terminate()
            pool.join()
            raise e

    else:
        # Main Process Loop (Debug Mode)
        print(f"Rendering {len(tasks)} tiles in MAIN process...")
        _init_renderer_worker(renderer_instance)
        for idx, task in enumerate(tasks, 1):
            created, duration = _render_tile(task)
            if created:
                generated += 1
            
            # Explicit GC
            gc.collect()

            batch_duration += duration
            batch_count += 1
            _process_progress(idx, len(tasks))
    
    print(f"Rendering complete. Generated {generated} tiles.")
    return generated

def generate_full_pyramid(renderer_instance, base_path, max_level, num_workers=8, renderer_config=None):
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
    
    generated = render_tasks(
        renderer_instance, tasks, dataset_dir=base_path, 
        num_workers=num_workers,
        renderer_config=renderer_config
    )
    return generated, total_tiles, len(tasks)

def generate_selected_tiles(renderer_instance, base_path, tiles, num_workers=8, renderer_config=None):
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
    
    generated = render_tasks(
        renderer_instance, tasks, dataset_dir=base_path, 
        num_workers=num_workers,
        renderer_config=renderer_config
    )
    return generated, len(tiles), len(tasks)

def generate_tiles_along_path(renderer_instance, base_path, dataset_id, path, steps=None, num_workers=8, viewport_width=1920, viewport_height=1080, renderer_config=None):
    if not path:
        print(f"No path defined for {dataset_id}; skipping path-based generation.")
        return 0

    keyframes = path.get('keyframes', [])
    if len(keyframes) < 2:
        print(f"Path for {dataset_id} has fewer than 2 keyframes; skipping.")
        return 0

    # Dynamic step calculation
    if steps is None:
        try:
            info = camera_utils.get_path_info(path)
            length = info.get('totalLength', 0)
            # Heuristic: 100 samples per visual unit ensures dense coverage.
            # Cap at 50,000 steps to prevent explosion on deep zoom paths where visual length is huge.
            steps = int(max(200, min(50000, length * 100)))
            print(f"Calculated path length: {length:.2f}. Using {steps} samples (capped).")
        except Exception as e:
            print(f"Warning: could not calculate dynamic path length ({e}). Falling back to 2000 steps.")
            steps = 2000

    print(f"Generating tiles along path for {dataset_id} (Viewport: {viewport_width}x{viewport_height}, Samples: {steps})...")
    required_tiles = set()  # (level, x, y)

    progresses = [s / steps for s in range(steps + 1)]
    
    # NOTE: We use parallel camera sampling.
    cams_workers = num_workers if num_workers > 0 else 1
    cams, tiles = camera_utils.cameras_at_progresses_parallel(
        progresses, path, viewport_width, viewport_height, 512, 
        num_workers=cams_workers
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
    
    generated = render_tasks(
        renderer_instance, tasks, dataset_dir=base_path, 
        num_workers=num_workers,
        renderer_config=renderer_config
    )
    return generated


def main():
    parser = argparse.ArgumentParser(description="Render tiles for Ultra-Resolution Quads datasets")
    parser.add_argument('--dataset', required=False, help='Dataset ID (e.g. debug_quadtile, mandelbrot_single_precision). If not provided, all datasets will be rendered.')
    parser.add_argument('--renderer_args', default="{}", help='JSON dict of kwargs passed to the renderer constructor')
    parser.add_argument('--max_level', type=int, default=None, help='Max level to generate for "full" mode (defaults to config or 4)')
    parser.add_argument('--mode', choices=['full', 'path'], default=None, help='Generation mode (defaults to config or "path")')
    parser.add_argument('--rebuild', action='store_true', help='Delete existing tiles for the dataset(s) before rendering')
    parser.add_argument('--tiles', default=None, help="Optional comma-separated list of tiles to render, formatted as level/x/y (e.g., '0/0/0,1/0/1'). When provided, overrides mode/max_level and renders only these tiles.")
    parser.add_argument('--workers', type=int, default=None, help="Optional number of workers. 0=MainProcess(Debug), 1=Pool(Safe), >1=Pool(Parallel).")
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

        # Instantiate renderer in main process for checks/fallback
        renderer = load_renderer(renderer_path, tile_size, merged_renderer_kwargs, dataset_path=dataset_tiles_root)
        
        # Prepare renderer config for workers (to avoid pickling the instance)
        # Structure: (renderer_path_str, tile_size_int, kwargs_dict, dataset_path_str)
        renderer_config_tuple = (renderer_path, tile_size, merged_renderer_kwargs, dataset_tiles_root)

        print(f"Initializing dataset: {dataset_id}")
        
        path_data = None
        if mode == 'path':
            path_data = render_config.get('path')
            if not path_data:
                print(f"Warning: Dataset '{dataset_id}' is in 'path' mode but no 'path' object found in render_config.")

        # Decide rendering strategy
        explicit_tiles = parse_tiles_arg(args.tiles) if args.tiles else []
        
        # Worker logic:
        # CLI overrides everything.
        # If CLI is None:
        #   If supports_multithreading -> 8
        #   If NOT supports_multithreading -> 1 (Safe Pool mode)
        if args.workers is not None:
            num_workers = args.workers
        else:
            if supports_multithreading:
                num_workers = 8
            else:
                num_workers = 1

        if explicit_tiles:
            print(f"Rendering explicit tiles: {explicit_tiles}")
            start_time = time.time()
            generated, total_tiles, missing = generate_selected_tiles(
                renderer, dataset_tiles_root, explicit_tiles, 
                num_workers=num_workers,
                renderer_config=renderer_config_tuple
            )
            elapsed = time.time() - start_time
            avg = elapsed / generated if generated else 0.0
        elif mode == 'full':
            print(f"Mode: full | max_level={max_level}")
            start_time = time.time()
            generated, total_tiles, missing = generate_full_pyramid(
                renderer, dataset_tiles_root, max_level, 
                num_workers=num_workers,
                renderer_config=renderer_config_tuple
            )
            elapsed = time.time() - start_time
            avg = elapsed / generated if generated else 0.0
        else:
            print("Mode: path")
            start_time = time.time()
            generated = generate_tiles_along_path(
                renderer, dataset_tiles_root, dataset_id, path_data, 
                num_workers=num_workers,
                viewport_width=args.viewport_width, viewport_height=args.viewport_height,
                renderer_config=renderer_config_tuple
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
        sizes = []
        for root, _, files in os.walk(dataset_tiles_root):
            for fname in files:
                if fname.lower().endswith(TILE_EXTENSION):
                    file_count += 1
                    sz = os.path.getsize(os.path.join(root, fname))
                    total_bytes += sz
                    sizes.append(sz)
        avg_size = total_bytes / file_count if file_count else 0.0
        avg_kb = avg_size / 1024.0
        min_kb = min(sizes) / 1024.0 if sizes else 0.0
        max_kb = max(sizes) / 1024.0 if sizes else 0.0
        median_kb = sorted(sizes)[len(sizes)//2] / 1024.0 if sizes else 0.0

        if explicit_tiles:
            print(f"Stats: generated={generated}, requested_missing={missing}, requested_total={total_tiles}, total_time={elapsed:.3f}s, avg_per_tile={avg*1000:.2f}ms, avg_file_size={avg_kb:.2f}KB (median {median_kb:.2f}KB, min {min_kb:.2f}KB, max {max_kb:.2f}KB), path={dataset_tiles_root}")
        elif mode == 'full':
            print(f"Stats: generated={generated}, requested_missing={missing}, total_possible={total_tiles}, total_time={elapsed:.3f}s, avg_per_tile={avg*1000:.2f}ms, avg_file_size={avg_kb:.2f}KB (median {median_kb:.2f}KB, min {min_kb:.2f}KB, max {max_kb:.2f}KB), path={dataset_tiles_root}")
        else:
            print(f"Stats: tiles_generated={generated}, total_time={elapsed:.3f}s, avg_per_tile={avg*1000:.2f}ms, avg_file_size={avg_kb:.2f}KB (median {median_kb:.2f}KB, min {min_kb:.2f}KB, max {max_kb:.2f}KB), path={dataset_tiles_root}")
            
    print("Done.")

if __name__ == "__main__":
    main()