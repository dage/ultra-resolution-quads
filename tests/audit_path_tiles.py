import os
import json
import math
import sys

# Configuration matching frontend defaults
TILE_SIZE = 512
VIEWPORT_WIDTH = 1920  # Assume a large desktop monitor to catch edge cases
VIEWPORT_HEIGHT = 1080

DATASET_ID = 'debug_deep_test'
DATA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
DATASET_PATH = os.path.join(DATA_ROOT, 'datasets', DATASET_ID)
TILES_PATH = os.path.join(DATASET_PATH, 'tiles')

def load_path():
    with open(os.path.join(DATASET_PATH, 'paths.json'), 'r') as f:
        data = json.load(f)
        # Find the seahorse zoom path
        for p in data['paths']:
            if p['id'] == 'deep_zoom_seahorse':
                return p
    return None

def interpolate_camera(k1, k2, t):
    # Matches frontend/main.js interpolateCamera logic
    
    l1 = k1['level']
    l2 = k2['level']
    
    # Interpolate Global Level
    lt = l1 + (l2 - l1) * t
    
    level = math.floor(lt)
    zoom_offset = lt - level
    
    # Interpolate Position (Global Coordinates)
    factor1 = 1.0 / (2 ** l1)
    gx1 = (k1['tileX'] + k1['offsetX']) * factor1
    gy1 = (k1['tileY'] + k1['offsetY']) * factor1
    
    factor2 = 1.0 / (2 ** l2)
    gx2 = (k2['tileX'] + k2['offsetX']) * factor2
    gy2 = (k2['tileY'] + k2['offsetY']) * factor2
    
    gxt = gx1 + (gx2 - gx1) * t
    gyt = gy1 + (gy2 - gy1) * t
    
    # Convert back to local
    factor_t = 2 ** level
    full_x = gxt * factor_t
    full_y = gyt * factor_t
    
    tile_x = math.floor(full_x)
    tile_y = math.floor(full_y)
    offset_x = full_x % 1
    offset_y = full_y % 1
    
    return {
        'level': level,
        'zoomOffset': zoom_offset,
        'tileX': tile_x,
        'tileY': tile_y,
        'offsetX': offset_x,
        'offsetY': offset_y
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
        
        # Center point in Target Level Coordinates
        # Camera Global Pos
        factor_g = 1.0 / (2 ** camera['level'])
        gx = (camera['tileX'] + camera['offsetX']) * factor_g
        gy = (camera['tileY'] + camera['offsetY']) * factor_g
        
        # Target Level Pos
        factor_t = 2 ** target_level
        cam_x_t = gx * factor_t
        cam_y_t = gy * factor_t
        
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
    path_obj = load_path()
    if not path_obj:
        print("Path not found!")
        sys.exit(1)
        
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
                path = os.path.join(TILES_PATH, str(level), str(x), f"{y}.png")
                
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
