import math
import os
import sys
from decimal import Decimal, getcontext

# Add project root to path to find backend modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from backend.fractal_renderer import FractalShadesRenderer


class PerpBSTreesRenderer:
    def __init__(self, tile_size=1024, **renderer_kwargs):
        self.tile_size = tile_size

        # Precision drives perturbation mode; mirror the gallery setup
        self.precision = int(renderer_kwargs.get("precision", 15))
        getcontext().prec = self.precision + 20

        # Root view pulled from gallery item #7
        self.root_x = Decimal(str(renderer_kwargs.get("x", "0.0")))
        self.root_y = Decimal(str(renderer_kwargs.get("y", "0.0")))
        self.root_dx = Decimal(str(renderer_kwargs.get("dx", "3.0")))
        self.root_dx = Decimal(str(renderer_kwargs.get("dx", "3.0")))
        self.xy_ratio = Decimal(str(renderer_kwargs.get("xy_ratio", "1.0")))
        self.theta_deg = Decimal(str(renderer_kwargs.get("theta_deg", "0.0")))
        self.skew_params = renderer_kwargs.get("skew_params")
        self.max_iter_base = int(renderer_kwargs.get("max_iter", 6000))
        self.max_iter_increment = int(renderer_kwargs.get("max_iter_increment", 0))

        # Remove positional keys so we don't forward stale versions
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
                "perp_bs_trees",
            )
        )
        self.fs_renderer = FractalShadesRenderer(self.output_dir)

    def _max_iter_for_level(self, level: int) -> int:
        return int(self.max_iter_base + int(level) * self.max_iter_increment)

    def _tile_center_offset(self, level: int, tile_x: int, tile_y: int):
        """
        Map tile indices to normalized offsets (u, v) in [-0.5, 0.5], then to
        complex-plane deltas using the same scheme as the gallery integrator:
        scale v by aspect, then apply skew (or rotation).
        """
        num_tiles = Decimal(2) ** level
        u = (Decimal(tile_x) + Decimal("0.5")) / num_tiles - Decimal("0.5")
        v = Decimal("0.5") - (Decimal(tile_y) + Decimal("0.5")) / num_tiles
        v = v / self.xy_ratio

        if self.skew_params:
            s00 = Decimal(str(self.skew_params.get("skew_00", 1.0)))
            s01 = Decimal(str(self.skew_params.get("skew_01", 0.0)))
            s10 = Decimal(str(self.skew_params.get("skew_10", 0.0)))
            s11 = Decimal(str(self.skew_params.get("skew_11", 1.0)))

            # Revert calibration
            # Try Rotation applied to u, v BEFORE Skew
            if self.theta_deg != 0:
                theta_rad = Decimal(math.radians(float(self.theta_deg)))
                cos_t = Decimal(math.cos(theta_rad))
                sin_t = Decimal(math.sin(theta_rad))
                
                u_rot = u * cos_t - v * sin_t
                v_rot = u * sin_t + v * cos_t
                u, v = u_rot, v_rot

            d_re = self.root_dx * (s00 * u + s01 * v)
            d_im = self.root_dx * (s10 * u + s11 * v)
        else:
            theta_rad = Decimal(math.radians(float(self.theta_deg)))
            cos_t = Decimal(math.cos(theta_rad))
            sin_t = Decimal(math.sin(theta_rad))

            d_re = self.root_dx * (u * cos_t - v * sin_t)
            d_im = self.root_dx * (u * sin_t + v * cos_t)

        return d_re, d_im

    def render(self, level, tile_x, tile_y):
        # Ensure precision in worker process
        getcontext().prec = self.precision + 20
        
        tile_dx = self.root_dx / (Decimal(2) ** level)
        d_re, d_im = self._tile_center_offset(level, tile_x, tile_y)

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
        render_params["batch_prefix"] = f"pbs_{level}_{tile_x}_{tile_y}"

        # Debug hook: print key params at lowest levels to catch mismatches
        if level == 0 and tile_x == 0 and tile_y == 0:
            print("[perp_bs_trees] render params (L0):", {k: render_params[k] for k in sorted(render_params.keys()) if k not in {"filename", "batch_prefix"}})

        _, img = self.fs_renderer.render(**render_params)
        return img

    def supports_multithreading(self):
        return True
