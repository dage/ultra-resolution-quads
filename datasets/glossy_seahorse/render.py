import os
import sys
from decimal import Decimal, getcontext
from PIL import Image

# Set high precision for coordinate calculations
getcontext().prec = 200

# Add project root to path to find backend
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from backend.fractal_renderer import FractalShadesRenderer
from backend.renderer_utils import calculate_max_iter

class GlossySeahorseRenderer:
    def __init__(self, tile_size=16, root_x="-0.746223962861", root_y="-0.0959468433527", root_dx="0.00745", supersampling=None):
        self.tile_size = tile_size
        # Store as Decimals
        self.root_x = Decimal(str(root_x))
        self.root_y = Decimal(str(root_y))
        self.root_dx = Decimal(str(root_dx))
        self.supersampling = supersampling
        
        # Initialize the backend renderer
        # Keep temp outputs in artifacts, not in the dataset folder
        self.output_dir = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "..", "artifacts", "temp_render_output", "glossy_seahorse"
        ))
        self.fs_renderer = FractalShadesRenderer(self.output_dir)

    def render(self, level, tile_x, tile_y):
        # Calculate coordinate for this tile using Decimal arithmetic
        # Level 0 matches the root view (root_x, root_y, root_dx)
        
        # current_dx = root_dx / 2^level
        # We use integer arithmetic for 2^level where possible or Decimal power
        # For level 200, 2**200 is huge but fits in integer (Python has arbitrary precision ints)
        scale_factor = Decimal(2) ** level
        current_dx = self.root_dx / scale_factor
        
        # Calculate Top-Left of the Root View
        # Assuming Aspect Ratio is 1.0 (Square)
        root_left = self.root_x - self.root_dx / Decimal(2.0)
        root_top = self.root_y + self.root_dx / Decimal(2.0)
        
        # Calculate Top-Left of the requested Tile
        # tile_x and tile_y are integers
        tile_left = root_left + Decimal(tile_x) * current_dx
        tile_top = root_top - Decimal(tile_y) * current_dx
        
        # Calculate Center of the requested Tile
        center_x = tile_left + current_dx / Decimal(2.0)
        center_y = tile_top - current_dx / Decimal(2.0)
        
        # Dynamic Max Iterations
        max_iter = calculate_max_iter(level)
        
        # Render using FractalShades
        # Pass coordinates as strings to preserve precision for FractalShades (which handles string inputs via gmpy2 usually)
        _, img = self.fs_renderer.render(
            fractal_type="mandelbrot",
            x=str(center_x),
            y=str(center_y),
            dx=str(current_dx),
            nx=self.tile_size,
            max_iter=max_iter,
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
