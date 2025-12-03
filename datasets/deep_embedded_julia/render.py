import os
import sys
from decimal import Decimal, getcontext
import math

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from backend.fractal_renderer import FractalShadesRenderer

class JuliaDeepRenderer:
    def __init__(self, tile_size=512, **renderer_kwargs):
        self.tile_size = tile_size
        self.renderer_kwargs = renderer_kwargs
        
        # Setup Decimal context for high precision math if precision is in kwargs
        precision = renderer_kwargs.get("precision", 15)
        getcontext().prec = precision + 20 # Buffer
        
        # Initialize the backend renderer
        self.output_dir = os.path.join(os.path.dirname(__file__), "temp_render_output")
        self.fs_renderer = FractalShadesRenderer(self.output_dir)

        # Extract root parameters for coordinate calculation
        self.root_x = Decimal(str(self.renderer_kwargs.get("x", "0.0")))
        self.root_y = Decimal(str(self.renderer_kwargs.get("y", "0.0")))
        self.root_dx = Decimal(str(self.renderer_kwargs.get("dx", "3.0")))
        self.precision = precision
        # Item 3 doesn't have xy_ratio or theta_deg, so defaults should be fine.
        self.xy_ratio = Decimal(str(self.renderer_kwargs.get("xy_ratio", "1.0")))
        self.theta_deg = Decimal(str(self.renderer_kwargs.get("theta_deg", "0.0")))

    def render(self, level, tile_x, tile_y):
        current_dx = self.root_dx / (Decimal(2) ** level)
        
        # Calculate Screen Offset (u, v) from Center
        num_tiles = Decimal(2) ** level
        
        grid_cx = Decimal(tile_x) + Decimal("0.5")
        grid_cy = Decimal(tile_y) + Decimal("0.5")
        
        u = (grid_cx / num_tiles) - Decimal("0.5")
        v = Decimal("0.5") - (grid_cy / num_tiles)
        
        # Standard Rotation (no skew_params for Item 3)
        theta_rad = Decimal(math.radians(float(self.theta_deg)))
        cos_t = Decimal(math.cos(theta_rad))
        sin_t = Decimal(math.sin(theta_rad))
        
        d_re = self.root_dx * (u * cos_t - v * sin_t)
        d_im = self.root_dx * (u * sin_t + v * cos_t)

        center_re = self.root_x + d_re
        center_im = self.root_y + d_im
        
        # Prepare parameters for FractalShadesRenderer
        render_params = self.renderer_kwargs.copy()
        render_params["x"] = f"{center_re:.{self.precision}f}"
        render_params["y"] = f"{center_im:.{self.precision}f}"
        render_params["dx"] = f"{current_dx:.{self.precision}e}"
        render_params["nx"] = self.tile_size
        render_params["filename"] = f"tile_{level}_{tile_x}_{tile_y}.webp"
        render_params["return_pillow_image"] = True
        render_params["batch_prefix"] = f"juliad_{level}_{tile_x}_{tile_y}"
        
        _, img = self.fs_renderer.render(**render_params)
        
        return img

    def supports_multithreading(self):
        return True
