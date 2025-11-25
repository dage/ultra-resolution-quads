import os
import json
import argparse
import sys
import shutil

# Add project root to path to find renderers
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from renderers.debug_renderer import DebugQuadtileRenderer
from renderers.mandelbrot_renderer import MandelbrotDeepZoomRenderer

DATA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

def ensure_dirs(path):
    os.makedirs(path, exist_ok=True)

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

def save_config(dataset_id, name, min_level, max_level):
    path = os.path.join(DATA_ROOT, 'datasets', dataset_id, 'config.json')
    ensure_dirs(os.path.dirname(path))
    with open(path, 'w') as f:
        json.dump({
            "id": dataset_id,
            "name": name,
            "min_level": min_level,
            "max_level": max_level
        }, f, indent=2)

def save_default_paths(dataset_id):
    path = os.path.join(DATA_ROOT, 'datasets', dataset_id, 'paths.json')
    # Always overwrite for now to ensure we have the latest test path
    ensure_dirs(os.path.dirname(path))
    with open(path, 'w') as f:
        json.dump({
            "paths": [
                {
                    "id": "default",
                    "name": "Deep Zoom",
                    "keyframes": [
                        {"camera": {"level": 0, "tileX": 0, "tileY": 0, "offsetX": 0.5, "offsetY": 0.5, "rotation": 0}},
                        {"camera": {"level": 4, "tileX": 8, "tileY": 8, "offsetX": 0.5, "offsetY": 0.5, "rotation": 0}}
                    ]
                }
            ]
        }, f, indent=2)

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

def main():
    parser = argparse.ArgumentParser(description="Generate datasets for Ultra-Resolution Quads")
    parser.add_argument('--dataset', required=True, help='Dataset ID (e.g. debug_quadtile, mandelbrot_deep)')
    parser.add_argument('--renderer', choices=['debug', 'mandelbrot'], required=True)
    parser.add_argument('--max_level', type=int, default=4, help='Max level to generate (full pyramid)')
    
    args = parser.parse_args()
    
    if args.renderer == 'debug':
        renderer = DebugQuadtileRenderer()
        name = "Debug Quadtile"
        desc = "Debug tiles to verify coordinate system"
    elif args.renderer == 'mandelbrot':
        renderer = MandelbrotDeepZoomRenderer()
        name = "Mandelbrot Deep"
        desc = "Standard Mandelbrot set"
    
    print(f"Initializing dataset: {args.dataset}")
    update_index(args.dataset, name, desc)
    save_config(args.dataset, name, 0, args.max_level)
    save_default_paths(args.dataset)
    
    print("Generating tiles...")
    generate_full_pyramid(renderer, args.dataset, args.max_level)
    print("Done.")

if __name__ == "__main__":
    main()
