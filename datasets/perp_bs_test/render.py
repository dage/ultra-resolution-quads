import os
import sys
from PIL import Image
from decimal import Decimal, getcontext

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from backend.fractal_renderer import FractalShadesRenderer

class BSDeepRenderer:
    def __init__(self, tile_size=512, center_x="0", center_y="0", width_dx="1.0", precision=15, max_iter=1000, skew_params=None, supersampling=None):
        self.tile_size = tile_size
        self.precision = precision
        self.max_iter = max_iter
        self.skew_params = skew_params or {}
        self.supersampling = supersampling
        
        # Setup Decimal context for high precision math
        getcontext().prec = self.precision + 20 # Buffer
        
        self.root_x = Decimal(center_x)
        self.root_y = Decimal(center_y)
        self.root_dx = Decimal(width_dx)
        
        # Initialize the backend renderer
        self.output_dir = os.path.join(os.path.dirname(__file__), "temp_render_output")
        self.fs_renderer = FractalShadesRenderer(self.output_dir)

    def render(self, level, tile_x, tile_y):
        # Level 0 is the full root view
        # current_dx is the scale factor for this tile
        current_dx = self.root_dx / (Decimal(2) ** level)
        
        # We need to calculate the center of the tile in the Complex Plane.
        # Since the view is skewed/rotated, we can't just add dx/dy linearly.
        # We must map the "Screen Offset" (u,v) through the Skew Matrix.
        
        # 1. Calculate Screen Offset (u, v) from Center
        # Range is [-0.5, 0.5] for the full Root view.
        # Tile width in normalized root units = 1 / 2^level
        
        # Number of tiles across
        num_tiles = Decimal(2) ** level
        
        # Tile Center in "Grid Coordinates" (0..N)
        # x: 0.5, 1.5, ...
        grid_cx = Decimal(tile_x) + Decimal("0.5")
        grid_cy = Decimal(tile_y) + Decimal("0.5")
        
        # Normalize to [0, 1] relative to Top-Left
        # u_norm = grid_cx / num_tiles
        # v_norm = grid_cy / num_tiles
        
        # Convert to Centered UV coords [-0.5, 0.5]
        # u direction: Left -> Right (increasing)
        u = (grid_cx / num_tiles) - Decimal("0.5")
        
        # v direction: Bottom -> Top (increasing)
        # Image Y goes Down. So higher tile_y means lower v.
        v = Decimal("0.5") - (grid_cy / num_tiles)
        
        # 2. Apply Skew Matrix
        # Matrix S:
        # [ S00  S01 ]
        # [ S10  S11 ]
        # Delta = dx_root * (S @ [u, v])
        
        s00 = Decimal(self.skew_params.get("skew_00", 1.0))
        s01 = Decimal(self.skew_params.get("skew_01", 0.0))
        s10 = Decimal(self.skew_params.get("skew_10", 0.0))
        s11 = Decimal(self.skew_params.get("skew_11", 1.0))
        
        # Note: root_dx scales the whole thing
        delta_re = self.root_dx * (s00 * u + s01 * v)
        delta_im = self.root_dx * (s10 * u + s11 * v)
        
        center_re = self.root_x + delta_re
        center_im = self.root_y + delta_im
        
        # Convert back to strings for FractalShades
        x_str = f"{center_re:.{self.precision}f}"
        y_str = f"{center_im:.{self.precision}f}"
        dx_str = f"{current_dx:.{self.precision}e}"
        
        # Render
        _, img = self.fs_renderer.render(
            fractal_type="burning_ship",
            x=x_str,
            y=y_str,
            dx=dx_str,
            nx=self.tile_size,
            xy_ratio=1.0, # Default
            max_iter=self.max_iter,
            precision=self.precision,
            skew_params=self.skew_params,
            theta_deg=-2.0, # Match gallery example rotation
            
            # Styling from Gallery Item 4
            base_layer="distance_estimation",
            colormap="dawn",
            zmin=-9.90, zmax=-4.94,
            supersampling=self.supersampling,
            interior_detect=True,
            
            # Output
            filename=f"tile_{level}_{tile_x}_{tile_y}.png",
            return_pillow_image=True,
            batch_prefix=f"bsd_{level}_{tile_x}_{tile_y}"
        )
        
        return img

    def supports_multithreading(self):
        return True