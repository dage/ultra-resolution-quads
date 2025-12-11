import os
import sys
from decimal import Decimal, getcontext
from PIL import Image

# Set high precision for coordinate calculations
getcontext().prec = 100

# Add project root to path to find backend
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from backend.fractal_renderer import FractalShadesRenderer
from backend.renderer_utils import calculate_max_iter

class MultibrotP4Renderer:
    def __init__(self, tile_size=1024, root_x="0.0", root_y="0.0", root_dx="2.5", supersampling=None):
        self.tile_size = tile_size
        self.root_x = Decimal(str(root_x))
        self.root_y = Decimal(str(root_y))
        self.root_dx = Decimal(str(root_dx))
        self.supersampling = supersampling
        
        self.output_dir = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "..", "artifacts", "temp_render_output", "multibrot_p4"
        ))
        self.fs_renderer = FractalShadesRenderer(self.output_dir)

    def render(self, level, tile_x, tile_y):
        scale_factor = Decimal(2) ** level
        current_dx = self.root_dx / scale_factor
        
        # Calculate Top-Left of the Root View
        root_left = self.root_x - self.root_dx / Decimal(2.0)
        root_top = self.root_y + self.root_dx / Decimal(2.0)
        
        # Calculate Top-Left of the requested Tile
        tile_left = root_left + Decimal(tile_x) * current_dx
        tile_top = root_top - Decimal(tile_y) * current_dx
        
        # Calculate Center of the requested Tile
        center_x = tile_left + current_dx / Decimal(2.0)
        center_y = tile_top - current_dx / Decimal(2.0)
        
        # Use dynamic max iter starting at 1500
        max_iter = calculate_max_iter(level, base=1500, increment=100)
        
        _, img = self.fs_renderer.render(
            fractal_type="mandelbrot_n",
            exponent=4,
            x=str(center_x),
            y=str(center_y),
            dx=str(current_dx),
            nx=self.tile_size,
            max_iter=max_iter,
            colormap="autumn",
            supersampling=self.supersampling,
            interior_detect=False,
            filename=f"tile_{level}_{tile_x}_{tile_y}.webp",
            return_pillow_image=True,
            batch_prefix=f"mb4_{level}_{tile_x}_{tile_y}"
        )
        return img

    def supports_multithreading(self):
        # We allow the renderer to say yes, but config will control the default
        return True
