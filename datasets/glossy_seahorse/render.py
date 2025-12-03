import os
import sys
from PIL import Image

# Add project root to path to find backend
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from backend.fractal_renderer import FractalShadesRenderer

class GlossySeahorseRenderer:
    def __init__(self, tile_size=1024, root_x=-0.746223962861, root_y=-0.0959468433527, root_dx=0.00745, supersampling=None):
        self.tile_size = tile_size
        self.root_x = root_x
        self.root_y = root_y
        self.root_dx = root_dx
        self.supersampling = supersampling
        
        # Initialize the backend renderer
        # We use a specific temp directory for this dataset to avoid collisions
        self.output_dir = os.path.join(os.path.dirname(__file__), "temp_render_output")
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
            fractal_type="mandelbrot",
            x=center_x,
            y=center_y,
            dx=current_dx,
            nx=self.tile_size,
            max_iter=2000,
            colormap="legacy",
            shade_kind="glossy",
            lighting_config={
                "k_diffuse": 0.4, 
                "k_specular": 30.0, 
                "shininess": 400.0,
                "polar_angle": 135.0, 
                "azimuth_angle": 20.0,
                "gloss_light_color": [1.0, 0.9, 0.9]
            },
            supersampling=self.supersampling,
            interior_detect=False,
            filename=f"tile_{level}_{tile_x}_{tile_y}.webp",
            return_pillow_image=True,
            batch_prefix=f"gs_{level}_{tile_x}_{tile_y}" # Unique prefix for thread safety if needed
        )
        
        return img

    def supports_multithreading(self):
        return True
