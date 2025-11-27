import os
import json
import argparse
import sys
import math
import time
import shutil
from concurrent.futures import ProcessPoolExecutor
from PIL import Image

# Add project root to path to find renderers
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from renderers.debug_renderer import DebugQuadtileRenderer
from renderers.mandelbrot_renderer import MandelbrotDeepZoomRenderer

DATA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

_renderer_instance = None

def ensure_dirs(path):
    os.makedirs(path, exist_ok=True)

def ensure_directories(dataset_id):
    output_dir = os.path.join(DATA_ROOT, 'datasets', dataset_id, 'tiles')
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


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

# Coordinate Mapping Logic (Replicated from Mandelbrot Renderer for Path Calculation)
VIEW_CENTER_RE = -0.75
VIEW_CENTER_IM = 0.0
VIEW_WIDTH = 3.0
VIEW_HEIGHT = 3.0

def complex_to_tile_coords(re, im, level):
    num_tiles = 2 ** level
    
    global_min_re = VIEW_CENTER_RE - VIEW_WIDTH / 2
    global_max_im = VIEW_CENTER_IM + VIEW_HEIGHT / 2
    
    # fraction of view width
    frac_x = (re - global_min_re) / VIEW_WIDTH
    # fraction of view height (inverted Y)
    frac_y = (global_max_im - im) / VIEW_HEIGHT
    
    # Total position in tile units
    total_tile_x = frac_x * num_tiles
    total_tile_y = frac_y * num_tiles
    
    tile_x = int(total_tile_x)
    tile_y = int(total_tile_y)
    
    offset_x = total_tile_x - tile_x
    offset_y = total_tile_y - tile_y
    
    return tile_x, tile_y, offset_x, offset_y

def load_or_create_paths(dataset_id, renderer_type):
    path_file = os.path.join(DATA_ROOT, 'datasets', dataset_id, 'paths.json')
    
    if os.path.exists(path_file):
        print(f"Loading existing paths from {path_file}")
        try:
            with open(path_file, 'r') as f:
                data = json.load(f)
                return data.get('paths', [])
        except Exception as e:
            print(f"Error loading paths: {e}. Regenerating defaults.")

    ensure_dirs(os.path.dirname(path_file))
    
    paths = []
    
    if renderer_type == 'mandelbrot':
        # Multi-stage deep zoom path
        
        # 1. Start: Full View
        tx0, ty0, ox0, oy0 = complex_to_tile_coords(-0.75, 0.0, 0)
        k1 = {"camera": {"level": 0, "tileX": tx0, "tileY": ty0, "offsetX": ox0, "offsetY": oy0, "rotation": 0}}
        
        # 2. Seahorse Valley Approach (Level 5)
        # A nice overview of the valley between the head and body
        tx1, ty1, ox1, oy1 = complex_to_tile_coords(-0.748, 0.1, 5)
        k2 = {"camera": {"level": 5, "tileX": tx1, "tileY": ty1, "offsetX": ox1, "offsetY": oy1, "rotation": 0}}

        # 3. Spiral Feature (Level 12)
        # Diving into a specific spiral arm
        tx2, ty2, ox2, oy2 = complex_to_tile_coords(-0.7436431, 0.1318255, 12)
        k3 = {"camera": {"level": 12, "tileX": tx2, "tileY": ty2, "offsetX": ox2, "offsetY": oy2, "rotation": 0}}
        
        # 4. Deep Target (Level 20)
        # Final destination: a mini-mandelbrot deep inside
        target_re = -0.7436438870371587
        target_im = 0.13182590420531197
        tx3, ty3, ox3, oy3 = complex_to_tile_coords(target_re, target_im, 20)
        k4 = {"camera": {"level": 20, "tileX": tx3, "tileY": ty3, "offsetX": ox3, "offsetY": oy3, "rotation": 0}}
        
        paths.append({
            "id": "default_path",
            "name": "Default Path",
            "keyframes": [k1, k2, k3, k4]
        })

    with open(path_file, 'w') as f:
        json.dump({"paths": paths}, f, indent=2)
    
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
    parser.add_argument('--renderer', choices=['debug', 'mandelbrot'], required=True)
    parser.add_argument('--max_level', type=int, default=4, help='Max level to generate')
    parser.add_argument('--mode', choices=['full', 'path'], default=None, help='Generation mode (default depends on renderer)')
    parser.add_argument('--tile_size', type=int, default=512, help='Tile size (pixels) for generated tiles')
    
    args = parser.parse_args()
    
    # Defaults
    if args.mode is None:
        if args.renderer == 'debug':
            args.mode = 'full'
        else:
            args.mode = 'path'
    
    if args.renderer == 'debug':
        renderer = DebugQuadtileRenderer(tile_size=args.tile_size)
        name = "Debug Quadtile"
        desc = "Debug tiles to verify coordinate system"
    elif args.renderer == 'mandelbrot':
        renderer = MandelbrotDeepZoomRenderer(tile_size=args.tile_size)
        name = "Mandelbrot Deep Zoom"
        desc = "Standard Mandelbrot set with deep zoom path"
    
    print(f"Initializing dataset: {args.dataset}")
    update_index(args.dataset, name, desc)
    # Config is saved at the end after determining actual max_level
    
    # Generate/Save Paths
    paths_data = load_or_create_paths(args.dataset, args.renderer)
    
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
