import math

# Logical tile size used for viewport math. Image resolution can differ.
LOGICAL_TILE_SIZE = 512
# We use a standard reference viewport. 
# The frontend adapts to the window size, but for generation we must cover the *maximum expected* viewport.
# 1920x1080 is a safe target.
VIEWPORT_WIDTH = 1920
VIEWPORT_HEIGHT = 1080

def interpolate_camera(k1, k2, t):
    """
    Linearly interpolates between two camera keyframes in Global Coordinate Space.
    Matches frontend/main.js interpolation logic.
    """
    l1 = k1['level']
    l2 = k2['level']
    
    # Interpolate Global Level
    lt = l1 + (l2 - l1) * t
    
    level = math.floor(lt)
    zoom_offset = lt - level
    
    # Interpolate Position (Global Coordinates)
    # Global coordinates are normalized [0, 1) at Level 0
    factor1 = 1.0 / (2 ** l1)
    gx1 = (k1['tileX'] + k1['offsetX']) * factor1
    gy1 = (k1['tileY'] + k1['offsetY']) * factor1
    
    factor2 = 1.0 / (2 ** l2)
    gx2 = (k2['tileX'] + k2['offsetX']) * factor2
    gy2 = (k2['tileY'] + k2['offsetY']) * factor2
    
    gxt = gx1 + (gx2 - gx1) * t
    gyt = gy1 + (gy2 - gy1) * t
    
    # Convert back to local tile coordinates at current level
    factor_t = 2 ** level
    full_x = gxt * factor_t
    full_y = gyt * factor_t
    
    tile_x = math.floor(full_x)
    tile_y = math.floor(full_y)
    offset_x = full_x - tile_x
    offset_y = full_y - tile_y
    
    return {
        'level': level,
        'zoomOffset': zoom_offset,
        'tileX': tile_x,
        'tileY': tile_y,
        'offsetX': offset_x,
        'offsetY': offset_y,
        'globalX': gxt,
        'globalY': gyt
    }

def get_viewport_bounds_at_level(camera, target_level):
    """
    Calculates the tile-space bounding box of the viewport for a specific target level.
    """
    # Camera center in Global Coordinates
    gx = camera['globalX']
    gy = camera['globalY']
    
    # Scale of the target level relative to Level 0
    target_factor = 2 ** target_level
    
    # Camera center in Target Level Tile Coordinates
    cam_x_t = gx * target_factor
    cam_y_t = gy * target_factor
    
    # Display Scale: How large is a Target Level tile drawn on screen?
    # scale = 2 ^ (camera_total_level - target_level)
    cam_total_level = camera['level'] + camera['zoomOffset']
    scale = 2 ** (cam_total_level - target_level)
    
    tile_size_on_screen = LOGICAL_TILE_SIZE * scale
    
    # Viewport dimensions in "Target Level Tiles"
    # If scale is small (zoomed out), we see many tiles.
    # If scale is large (zoomed in), we see few tiles.
    tiles_w = VIEWPORT_WIDTH / tile_size_on_screen
    tiles_h = VIEWPORT_HEIGHT / tile_size_on_screen
    
    # Bounds
    min_x = cam_x_t - tiles_w / 2
    max_x = cam_x_t + tiles_w / 2
    min_y = cam_y_t - tiles_h / 2
    max_y = cam_y_t + tiles_h / 2
    
    return min_x, max_x, min_y, max_y

def get_visible_tiles(camera, margin=1):
    """
    Returns a set of (level, x, y) tuples visible for the given camera state.
    Matches frontend rendering logic (Parent + Child layers).
    """
    visible = set()
    
    # We always render the 'base level' (floor)
    # and if zoomOffset > 0, we render 'base level + 1'
    
    levels = [camera['level']]
    if camera['zoomOffset'] > 0.001:
        levels.append(camera['level'] + 1)
        
    for lvl in levels:
        if lvl < 0: continue
        
        min_x, max_x, min_y, max_y = get_viewport_bounds_at_level(camera, lvl)
        
        # Apply margin and discretize
        tx_min = math.floor(min_x - margin)
        tx_max = math.floor(max_x + margin)
        ty_min = math.floor(min_y - margin)
        ty_max = math.floor(max_y + margin)
        
        limit = 2 ** lvl
        
        for x in range(tx_min, tx_max + 1):
            for y in range(ty_min, ty_max + 1):
                if 0 <= x < limit and 0 <= y < limit:
                    visible.add((lvl, x, y))
                    
    return visible
