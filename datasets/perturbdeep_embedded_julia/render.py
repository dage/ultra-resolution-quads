import os
import sys
from decimal import Decimal, getcontext

# Add project root to path to find backend modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from backend.fractal_renderer import FractalShadesRenderer


class PerturbDeepEmbeddedJuliaRenderer:
    """
    Tile renderer for Fractal Gallery #9 (PerturbDeep Embedded Julia).
    Matches the gallery item's camera and styling, but renders a quadtile pyramid.
    """

    def __init__(self, tile_size=512, **renderer_kwargs):
        self.tile_size = tile_size

        self.precision = int(renderer_kwargs.get("precision", 15))
        getcontext().prec = self.precision + 20

        self.root_x = Decimal(str(renderer_kwargs.get("x", "0.0")))
        self.root_y = Decimal(str(renderer_kwargs.get("y", "0.0")))
        self.root_dx = Decimal(str(renderer_kwargs.get("dx", "3.0")))
        self.xy_ratio = Decimal(str(renderer_kwargs.get("xy_ratio", "1.0")))

        self.max_iter_base = int(renderer_kwargs.get("max_iter", 20000))
        self.max_iter_increment = int(renderer_kwargs.get("max_iter_increment", 0))

        for key in ["x", "y", "dx", "nx", "max_iter", "max_iter_increment"]:
            renderer_kwargs.pop(key, None)
        self.renderer_kwargs = renderer_kwargs

        self.output_dir = os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
                "artifacts",
                "temp_render_output",
                "perturbdeep_embedded_julia",
            )
        )
        self.fs_renderer = FractalShadesRenderer(self.output_dir)

    def _max_iter_for_level(self, level: int) -> int:
        return int(self.max_iter_base + int(level) * self.max_iter_increment)

    def render(self, level, tile_x, tile_y):
        getcontext().prec = self.precision + 20

        num_tiles = Decimal(2) ** level
        u = (Decimal(tile_x) + Decimal("0.5")) / num_tiles - Decimal("0.5")
        v = Decimal("0.5") - (Decimal(tile_y) + Decimal("0.5")) / num_tiles
        tile_dx = self.root_dx / (Decimal(2) ** level)
        v = v / self.xy_ratio

        # Match gallery/integrator mapping: offsets use root_dx, with v scaled by ratio.
        d_re = self.root_dx * u
        d_im = self.root_dx * v

        center_x = self.root_x + d_re
        center_y = self.root_y + d_im

        render_params = self.renderer_kwargs.copy()
        render_params["x"] = f"{center_x:.{self.precision}f}"
        render_params["y"] = f"{center_y:.{self.precision}f}"
        render_params["dx"] = f"{tile_dx:.{self.precision}e}"
        render_params["nx"] = self.tile_size
        render_params["max_iter"] = self._max_iter_for_level(level)
        render_params["filename"] = f"tile_{level}_{tile_x}_{tile_y}.webp"
        render_params["return_pillow_image"] = True
        render_params["batch_prefix"] = f"pdej_{level}_{tile_x}_{tile_y}"

        # Preserve gallery aspect for each tile; frontend will handle non-square tiles.
        render_params["xy_ratio"] = float(self.xy_ratio)

        _, img = self.fs_renderer.render(**render_params)
        return img

    def supports_multithreading(self):
        return True
