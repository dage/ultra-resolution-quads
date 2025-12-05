import os
import sys
from PIL import Image

# Add project root to path to find backend
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from backend.fractal_renderer import FractalShadesRenderer
from backend.renderer_utils import calculate_max_iter

class PowerTowerRenderer:
    def __init__(self, tile_size=512, root_x=1.40735, root_y=-3.36277, root_dx=0.0005, supersampling=None):
        self.tile_size = tile_size
        self.root_x = root_x
        self.root_y = root_y
        self.root_dx = root_dx
        self.supersampling = supersampling
        
        # Initialize the backend renderer
        # Keep temp outputs in artifacts, not in the dataset folder
        self.output_dir = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "..", "artifacts", "temp_render_output", "power_tower"
        ))
        self.fs_renderer = FractalShadesRenderer(self.output_dir)

    def render(self, level, tile_x, tile_y):
        # Calculate coordinate for this tile
        # Level 0 matches the root view (root_x, root_y, root_dx)
        
        current_dx = self.root_dx / (2 ** level)
        
        # Calculate Top-Left of the Root View
        # Assuming Aspect Ratio is 1.0 (Square)
        root_left = self.root_x - self.root_dx / 2.0
        root_top = self.root_y + self.root_dx / 2.0
        
        # Calculate Top-Left of the requested Tile
        tile_left = root_left + tile_x * current_dx
        tile_top = root_top - tile_y * current_dx
        
        # Calculate Center of the requested Tile
        center_x = tile_left + current_dx / 2.0
        center_y = tile_top - current_dx / 2.0
        
        # Render using FractalShades
        # We pass return_pillow_image=True to get the object directly
        _, img = self.fs_renderer.render(
            fractal_type="power_tower",
            x=center_x,
            y=center_y,
            dx=current_dx,
            nx=self.tile_size,
            max_iter=calculate_max_iter(level),
            colormap="flower",
            supersampling=self.supersampling,
            interior_detect=True,
            filename=f"tile_{level}_{tile_x}_{tile_y}.webp",
            return_pillow_image=True,
            batch_prefix=f"pt_{level}_{tile_x}_{tile_y}" # Unique prefix for thread safety if needed
        )
        
        return img

    def supports_multithreading(self):
        # FractalShades might have its own threading or numba compilation which can be tricky
        # But since we are launching separate processes in render_tiles.py, 
        # we generally want to be careful.
        # However, render_tiles.py uses ProcessPoolExecutor. 
        # Pickling this class is fine.
        return True
