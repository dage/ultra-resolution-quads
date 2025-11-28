"""
Audit required tiles along a path by simulating viewport coverage at high resolution.
Intended for sanity-checking datasets after generation; skips cleanly if data is missing.
"""

import os
import json
import math
import sys
import argparse

# Configuration matching frontend defaults
TILE_SIZE = 512
VIEWPORT_WIDTH = 1920  # Assume a large desktop monitor to catch edge cases
VIEWPORT_HEIGHT = 1080

DATA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

def load_path(dataset_path, path_id):
    path_file = os.path.join(dataset_path, 'paths.json')
    if not os.path.exists(path_file):
        return None
    with open(path_file, 'r') as f:
        data = json.load(f)
        for p in data.get('paths', []):
            if path_id is None or p.get('id') == path_id:
                return p
    return None

def interpolate_camera(k1, k2, t):
    # Linear interpolation in normalized global space with fractional level
    l1 = k1['level']
    l2 = k2['level']
    
    lt = l1 + (l2 - l1) * t
    level = math.floor(lt)
    zoom_offset = lt - level
    
    gxt = k1['x'] + (k2['x'] - k1['x']) * t
    gyt = k1['y'] + (k2['y'] - k1['y']) * t
    
    return {
        'level': level,
        'zoomOffset': zoom_offset,
        'x': gxt,
        'y': gyt
    }

def get_visible_tiles(camera):
    # Matches frontend/main.js renderLayer logic
    # We need to check BOTH the parent level (fading out) and current level + 1 (fading in)
    # if zoomOffset > 0.
    
    visible = set()
    
    # Function to get tiles for a specific level
    def add_layer_tiles(target_level):
        # Calculate scale of target level relative to current camera level
        # displayScale = 2 ^ (camera_level + zoom_offset - target_level)
        display_scale = math.pow(2, camera['level'] + camera['zoomOffset'] - target_level)
        
        tile_size_on_screen = TILE_SIZE * display_scale
        
        # Target Level Pos (normalized -> tile coordinates at target level)
        factor_t = 2 ** target_level
        cam_x_t = camera['x'] * factor_t
        cam_y_t = camera['y'] * factor_t
        
        tiles_in_view_x = VIEWPORT_WIDTH / tile_size_on_screen
        tiles_in_view_y = VIEWPORT_HEIGHT / tile_size_on_screen
        
        # Margin: Frontend uses margin=1. Let's use strict frontend logic.
        margin = 1
        min_tile_x = math.floor(cam_x_t - tiles_in_view_x / 2 - margin)
        max_tile_x = math.floor(cam_x_t + tiles_in_view_x / 2 + margin)
        min_tile_y = math.floor(cam_y_t - tiles_in_view_y / 2 - margin)
        max_tile_y = math.floor(cam_y_t + tiles_in_view_y / 2 + margin)
        
        limit = 2 ** target_level
        
        for x in range(min_tile_x, max_tile_x + 1):
            for y in range(min_tile_y, max_tile_y + 1):
                if 0 <= x < limit and 0 <= y < limit:
                    visible.add((target_level, x, y))

    # Parent Layer (Always visible as background)
    add_layer_tiles(camera['level'])
    
    # Child Layer (Visible if zooming in)
    if camera['zoomOffset'] > 0.001: # Frontend epsilon
         add_layer_tiles(camera['level'] + 1)
         
    return visible

def main():
    parser = argparse.ArgumentParser(description="Audit required tiles along a path.")
    parser.add_argument("--dataset", default="debug_quadtile", help="Dataset ID under datasets/")
    parser.add_argument("--path-id", default=None, help="Path id to audit (default: first path)")
    args = parser.parse_args()

    dataset_path = os.path.join(DATA_ROOT, 'datasets', args.dataset)
    tiles_path = os.path.join(dataset_path, 'tiles')

    if not os.path.exists(dataset_path):
        print(f"[skip] dataset not found: {dataset_path}")
        sys.exit(0)

    path_obj = load_path(dataset_path, args.path_id)
    if not path_obj:
        print(f"[skip] path not found in {dataset_path}")
        sys.exit(0)
        
    keyframes = path_obj['keyframes']
    print(f"Auditing path: {path_obj['name']} ({len(keyframes)} keyframes)")
    
    missing_tiles = set()
    checked_tiles = set()
    
    # Simulation steps
    # Total duration isn't fixed in this script, so we just iterate T from 0 to 1 per segment
    # with high resolution.
    
    SIM_STEPS_PER_SEGMENT = 1000 
    
    for i in range(len(keyframes) - 1):
        k1 = keyframes[i]['camera']
        k2 = keyframes[i + 1]['camera']
        
        print(f"Segment {i}: L{k1['level']} -> L{k2['level']}")
        
        for s in range(SIM_STEPS_PER_SEGMENT + 1):
            t = s / SIM_STEPS_PER_SEGMENT
            cam = interpolate_camera(k1, k2, t)
            
            required = get_visible_tiles(cam)
            
            for tile in required:
                if tile in checked_tiles:
                    continue
                
                level, x, y = tile
                path = os.path.join(tiles_path, str(level), str(x), f"{y}.png")
                
                if not os.path.exists(path):
                    missing_tiles.add(tile)
                    # print(f"MISSING: {tile} at t={t:.4f} (L{cam['level']}+{cam['zoomOffset']:.2f})")
                
                checked_tiles.add(tile)
                
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
