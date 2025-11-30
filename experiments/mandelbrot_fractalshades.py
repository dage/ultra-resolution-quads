import os
import fractalshades as fs
import fractalshades.models as fsm
import fractalshades.colors as fscolors
import fractalshades.projection
from fractalshades.postproc import Postproc_batch, Continuous_iter_pp
from fractalshades.colors.layers import Color_layer
from PIL import Image

# 1. Setup
fs.settings.enable_multithreading = True
fs.settings.verbosity = 1
# Write artifacts into the project artifacts folder (no more deep_zoom_flake root folder)
output_dir = os.path.join("artifacts", "fractalshades_seahorse")
os.makedirs(output_dir, exist_ok=True)

# 2. Use a reliable, visible Mandelbrot location (Seahorse Valley)
# This is a much shallower zoom so we can quickly verify everything works.
BASE_X = -0.743643887037151
BASE_Y = 0.13182590420533
ZOOM_WIDTH = 0.002
IMG_SIZE = 512


def render_tile(center_x: float, center_y: float, name: str) -> str:
    """Render a single tile at (center_x, center_y) and return its path."""
    model = fsm.Perturbation_mandelbrot(output_dir)

    print(f"Setting up zoom at {ZOOM_WIDTH} width for {name}...")
    model.zoom(
        precision=128,
        x=center_x,
        y=center_y,
        dx=ZOOM_WIDTH,
        nx=IMG_SIZE,
        xy_ratio=1.0,
        theta_deg=0,
        projection=fs.projection.Cartesian()
    )

    print(f"Calculating standard divergence (2,000 iterations) for {name}...")
    model.calc_std_div(
        max_iter=2000,
        calc_name="div_layer",
        subset=None,
        M_divergence=1000.0,
        epsilon_stationnary=1.0e-3,
        BLA_eps=1.0e-6
    )

    print(f"Post-processing and saving {name}...")
    pp = Postproc_batch(model, "div_layer")
    pp.add_postproc("cont_iter", Continuous_iter_pp())

    plotter = fs.Fractal_plotter(pp, final_render=True, supersampling="3x3")

    # Heavy-contrast palette and normalization
    palette_name = "citrus" if "citrus" in fscolors.cmap_register else "classic"

    plotter.add_layer(Color_layer(
        "cont_iter",
        # Heavy contrast: crush lows a bit and lift mids for clear dark-to-bright span
        func="np.power(np.clip((np.log(x) - 2.6) / 3.4, 0.0, 1.0), 0.45)",
        colormap=fscolors.cmap_register[palette_name],
        output=True
    ))

    plotter.plot()

    default_path = os.path.join(output_dir, "Color_layer_cont_iter.png")
    tile_path = os.path.join(output_dir, f"{name}.png")
    os.replace(default_path, tile_path)
    print(f"Saved {tile_path}")
    return tile_path


def compose_tiles(tile_left: str, tile_right: str, out_path: str) -> None:
    left = Image.open(tile_left).convert("RGB")
    right = Image.open(tile_right).convert("RGB")
    w, h = left.size
    gap = 1
    canvas = Image.new("RGB", (w * 2 + gap, h), color="white")
    canvas.paste(left, (0, 0))
    canvas.paste(right, (w + gap, 0))
    canvas.save(out_path)
    print(f"Saved composed tiles to {out_path}")


if __name__ == "__main__":
    # Left tile at base coordinates, right tile shifted by one tile width to the right.
    tile_left = render_tile(BASE_X, BASE_Y, "tile_left")
    tile_right = render_tile(BASE_X + ZOOM_WIDTH, BASE_Y, "tile_right")

    compose_tiles(
        tile_left,
        tile_right,
        os.path.join(output_dir, "tiles_composed.png"),
    )