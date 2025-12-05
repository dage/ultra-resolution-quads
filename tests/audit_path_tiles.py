"""
Audit required tiles along a path by simulating viewport coverage at high resolution.
Intended for sanity-checking datasets after generation; skips cleanly if data is missing.
"""

import os
import json
import math
import sys
import argparse

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from backend import camera_utils

# Configuration matching frontend defaults
TILE_SIZE = 512
VIEWPORT_WIDTH = 1920  # Assume a large desktop monitor to catch edge cases
VIEWPORT_HEIGHT = 1080

DATA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

def load_path(dataset_path, path_id):
    config_file = os.path.join(dataset_path, 'config.json')
    if not os.path.exists(config_file):
        return None
    with open(config_file, 'r') as f:
        data = json.load(f)
        render_config = data.get('render_config', {})
        path_obj = render_config.get('path')
        
        if not path_obj or not isinstance(path_obj, dict):
            return None
            
        # If path_id is specified, we could check it, but currently we only support one path per config.
        # So we just return it if found.
        if path_id is not None:
            if path_obj.get('id') != path_id:
                # Mismatch
                return None
        
        return path_obj
    return None

def main():
    parser = argparse.ArgumentParser(description="Audit required tiles along a path.")
    parser.add_argument("--dataset", default="debug_quadtile", help="Dataset ID under datasets/")
    parser.add_argument("--path-id", default=None, help="Path id to audit (default: first/only path)")
    args = parser.parse_args()

    dataset_path = os.path.join(DATA_ROOT, 'datasets', args.dataset)
    
    # Updated: Tiles are now directly in the dataset folder
    tiles_path = dataset_path 

    if not os.path.exists(dataset_path):
        print(f"[skip] dataset not found: {dataset_path}")
        sys.exit(0)

    path_obj = load_path(dataset_path, args.path_id)
    if not path_obj:
        print(f"[skip] path not found in {dataset_path} (checked config.json)")
        sys.exit(0)
        
    keyframes = path_obj.get('keyframes', [])
    print(f"Auditing path: {path_obj.get('name', 'Unnamed')} ({len(keyframes)} keyframes)")
    
    missing_tiles = set()
    checked_tiles = set()
    
    # Calculate total steps based on path complexity or just fixed high res
    # Use 2000 steps like the generator to be consistent
    TOTAL_STEPS = 2000
    progresses = [i / TOTAL_STEPS for i in range(TOTAL_STEPS + 1)]
    
    print("Calculating required tiles using Production Logic (ViewUtils)...")
    camera_utils.set_camera_path(path_obj)
    
    # Bulk retrieve (cameras, tiles)
    _, required_tiles_list = camera_utils.cameras_at_progresses(progresses)
    
    print(f"Found {len(required_tiles_list)} unique tiles required by the path.")

    for t in required_tiles_list:
        level = t['level']
        x = t['x']
        y = t['y']
        tile_key = (level, x, y)
        
        if tile_key in checked_tiles:
            continue
        
        # Check for tile file
        path = os.path.join(tiles_path, str(level), str(x), f"{y}.webp")
        
        if not os.path.exists(path):
            missing_tiles.add(tile_key)
        
        checked_tiles.add(tile_key)
                
    print(f"\nAudit Complete.")
    print(f"Total Unique Tiles Checked: {len(checked_tiles)}")
    print(f"Missing Tiles: {len(missing_tiles)}")
    
    if missing_tiles:
        print("\nSample Missing Tiles:")
        for t in list(missing_tiles)[:10]:
            print(t)
        print("...")

if __name__ == "__main__":
    main()