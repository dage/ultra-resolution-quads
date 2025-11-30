import os
import sys
from typing import List, Dict, Any

from PIL import Image, ImageDraw, ImageFont

# Add project root to path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from backend.fractal_renderer import FractalShadesRenderer


def _get_fractal_configs() -> List[Dict[str, Any]]:
    """
    Return 16 diverse fractal views spanning several model types,
    chosen via an automated search process for visual appeal.
    """
    FUNC_CLASSIC = "np.power(np.clip((np.log(x) - 2.6) / 3.4, 0.0, 1.0), 0.45)"

    configs: List[Dict[str, Any]] = [
          {
            "name": "Elephant Valley Var",
            "desc": "Visually stunning with rich textures and elegant curves",
            "model": "mandelbrot",
            "x": 0.3299789834272471,
            "y": -0.03985010908816195,
            "width": 0.14820262887783786,
            "max_iter": 3299,
            "colormap": "sunset",
            "func": FUNC_CLASSIC,
            "visualization": "dem",
            "add_lighting": False,
          },
          {
            "name": "Triple Spiral Var",
            "desc": "Visually striking with rich blue gradients and intricate patterns",
            "model": "mandelbrot",
            "x": -0.08883271851852871,
            "y": 0.6532067896262057,
            "width": 0.010132953748783589,
            "max_iter": 2940,
            "colormap": "legacy",
            "func": FUNC_CLASSIC,
            "visualization": "continuous_iter",
            "add_lighting": False,
          },
          {
            "name": "Triple Spiral Var 2",
            "desc": "Elegant gradient and intricate patterns",
            "model": "mandelbrot",
            "x": -0.08579269304710704,
            "y": 0.6535056508198839,
            "width": 0.036866865381374125,
            "max_iter": 2951,
            "colormap": "classic",
            "func": FUNC_CLASSIC,
            "visualization": "dem",
            "add_lighting": True,
          },
          {
            "name": "Elephant Valley Var 2",
            "desc": "Visually striking with elegant blue gradients and intricate fractal patterns",
            "model": "mandelbrot",
            "x": 0.3193846574562268,
            "y": 0.1219016803920847,
            "width": 0.8380002128857211,
            "max_iter": 3046,
            "colormap": "legacy",
            "func": FUNC_CLASSIC,
            "visualization": "dem",
            "add_lighting": True,
          },
          {
            "name": "Mandelbrot Power 4 Var",
            "desc": "Visually striking with deep blue gradients and intricate fractal edges",
            "model": "mandelbrot_n",
            "x": 0.12076166124146137,
            "y": 0.4645288213788723,
            "width": 1.863357599138842,
            "max_iter": 2710,
            "colormap": "legacy",
            "func": FUNC_CLASSIC,
            "visualization": "dem",
            "add_lighting": False,
            "mandelbrot_n_exponent": 4
          },
          {
            "name": "Triple Spiral Var 3",
            "desc": "Visually striking with strong contrast and rhythmic patterns",
            "model": "mandelbrot",
            "x": -0.08674439834348258,
            "y": 0.6559028378784463,
            "width": 0.04951250981407869,
            "max_iter": 2210,
            "colormap": "legacy",
            "func": FUNC_CLASSIC,
            "visualization": "continuous_iter",
            "add_lighting": False,
          },
          {
            "name": "Mandelbrot Power 4 Var 2",
            "desc": "Simple but recognizable fractal pattern with decent contrast",
            "model": "mandelbrot_n",
            "x": -0.09529814213082477,
            "y": 0.7260553334887425,
            "width": 2.9208162590861444,
            "max_iter": 3201,
            "colormap": "atoll",
            "func": FUNC_CLASSIC,
            "visualization": "continuous_iter",
            "add_lighting": False,
            "mandelbrot_n_exponent": 4
          },
          {
            "name": "Elephant Valley Var 3",
            "desc": "Minimalist and intriguing, but limited visual impact",
            "model": "mandelbrot",
            "x": 0.17737214809613383,
            "y": -0.06798479675524778,
            "width": 0.2268718369927641,
            "max_iter": 3378,
            "colormap": "legacy",
            "func": FUNC_CLASSIC,
            "visualization": "continuous_iter",
            "add_lighting": False,
          },
          {
            "name": "Mandelbrot Power 3 Var",
            "desc": "Simple but recognizable fractal pattern with strong contrast",
            "model": "mandelbrot_n",
            "x": 0.21356689239306625,
            "y": 0.42812058607133147,
            "width": 1.0987099012226151,
            "max_iter": 2404,
            "colormap": "classic",
            "func": FUNC_CLASSIC,
            "visualization": "dem",
            "add_lighting": False,
            "mandelbrot_n_exponent": 3
          },
          {
            "name": "Seahorse Valley Var",
            "desc": "Simple but symmetrical, with a subtle gradient",
            "model": "mandelbrot",
            "x": -0.7551264211473593,
            "y": 0.0972217272063441,
            "width": 0.25,
            "max_iter": 4128,
            "colormap": "atoll",
            "func": FUNC_CLASSIC,
            "visualization": "continuous_iter",
            "add_lighting": False,
          },
          {
            "name": "Mandelbrot Power 3 Var 2",
            "desc": "Symmetrical but lacks vibrant detail and color",
            "model": "mandelbrot_n",
            "x": 0.00321283704183295,
            "y": 0.3446279801257034,
            "width": 1.8454824023171301,
            "max_iter": 2483,
            "colormap": "autumn",
            "func": FUNC_CLASSIC,
            "visualization": "dem",
            "add_lighting": False,
            "mandelbrot_n_exponent": 3
          },
          {
            "name": "Burning Ship Hull Var",
            "desc": "Subtle gradients with a bold black contrast",
            "model": "burning_ship",
            "x": -1.759666115044216,
            "y": -0.027428729969749818,
            "width": 0.08032435789171112,
            "max_iter": 5764,
            "colormap": "sunset",
            "func": FUNC_CLASSIC,
            "visualization": "dem",
            "add_lighting": True,
          },
          {
            "name": "Mandelbrot Power 3 Var 3",
            "desc": "Symmetrical but lacks vibrant detail and visual excitement",
            "model": "mandelbrot_n",
            "x": -0.23443643568006434,
            "y": 0.7091180336278731,
            "width": 2.678833159396925,
            "max_iter": 2615,
            "colormap": "autumn",
            "func": FUNC_CLASSIC,
            "visualization": "continuous_iter",
            "add_lighting": False,
            "mandelbrot_n_exponent": 3
          },
          {
            "name": "Burning Ship Tail Var",
            "desc": "Subtle texture with limited color variation",
            "model": "burning_ship",
            "x": -1.7782722693217992,
            "y": -0.06569268302156242,
            "width": 0.25451014576158504,
            "max_iter": 6407,
            "colormap": "legacy",
            "func": FUNC_CLASSIC,
            "visualization": "dem",
            "add_lighting": True,
          },
          {
            "name": "Mandelbrot Power 3 Var 4",
            "desc": "Minimalist and abstract, but lacks visual complexity",
            "model": "mandelbrot_n",
            "x": -0.048432846055270706,
            "y": 0.7427349452206422,
            "width": 0.6204880663866617,
            "max_iter": 3237,
            "colormap": "autumn",
            "func": FUNC_CLASSIC,
            "visualization": "continuous_iter",
            "add_lighting": False,
            "mandelbrot_n_exponent": 3
          },
          {
            "name": "Elephant Valley Var 4",
            "desc": "Minimalist and abstract, with subtle gradient and sparse detail",
            "model": "mandelbrot",
            "x": 0.4048802154829432,
            "y": -0.050553764323954066,
            "width": 0.4115893204747487,
            "max_iter": 3066,
            "colormap": "autumn",
            "func": FUNC_CLASSIC,
            "visualization": "continuous_iter",
            "add_lighting": False,
          }
    ]

    return configs


def create_gallery() -> None:
    """
    Render 16 diverse Mandelbrot tiles and compose them into a 4x4 gallery.
    The specific views were chosen (with help from the analyzer tool) to avoid
    uniform backgrounds and cover several visually distinct regions.
    """
    output_dir = os.path.join("artifacts", "gallery_experiment")
    os.makedirs(output_dir, exist_ok=True)

    renderer = FractalShadesRenderer(output_dir, verbosity=1)
    configs = _get_fractal_configs()

    rendered_paths: List[Dict[str, Any]] = []

    print(f"Rendering {len(configs)} diverse fractals...")
    for i, conf in enumerate(configs):
        fname = f"fractal_{i:02d}.png"
        print(f"\n[{i+1}/{len(configs)}] Rendering {conf['name']}...")
        try:
            render_kwargs = {
                "center_x": conf["x"],
                "center_y": conf["y"],
                "width": conf["width"],
                "img_size": 512,
                "max_iter": conf["max_iter"],
                "filename": fname,
                "colormap": conf.get("colormap", "classic"),
                "layer_func": conf.get("func"),
                "model": conf.get("model", "mandelbrot"),
                "visualization": conf.get("visualization", "continuous_iter"),
                "add_lighting": conf.get("add_lighting", False)
            }
            
            if "mandelbrot_n_exponent" in conf:
                render_kwargs["mandelbrot_n_exponent"] = conf["mandelbrot_n_exponent"]

            path = renderer.render(**render_kwargs)
            print(f"  Saved: {path}")
            item = dict(conf)
            item["path"] = path
            rendered_paths.append(item)
        except Exception as e:
            print(f"  ERROR rendering {conf['name']}: {e}")

    if not rendered_paths:
        print("No images rendered. Exiting.")
        return

    print("\nConstructing 4x4 gallery...")

    cols = 4
    rows = 4
    tile_size = 512
    padding = 50
    text_height = 100

    gallery_w = cols * tile_size + (cols + 1) * padding
    gallery_h = rows * (tile_size + text_height) + (rows + 1) * padding

    gallery = Image.new("RGB", (gallery_w, gallery_h), (30, 30, 30))
    draw = ImageDraw.Draw(gallery)

    # Font handling
    try:
        font_paths = [
            "/System/Library/Fonts/Helvetica.ttc",  # macOS
            "/System/Library/Fonts/Supplemental/Arial.ttf",  # macOS
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Linux
            "C:\\Windows\\Fonts\\arial.ttf",  # Windows
        ]
        font_path = None
        for p in font_paths:
            if os.path.exists(p):
                font_path = p
                break

        if font_path:
            font_title = ImageFont.truetype(font_path, 28)
            font_desc = ImageFont.truetype(font_path, 18)
        else:
            raise Exception("No system font found")
    except Exception:
        print("Using default font.")
        font_title = ImageFont.load_default()
        font_desc = ImageFont.load_default()

    for i, conf in enumerate(rendered_paths[:16]):
        r = i // cols
        c = i % cols

        try:
            img = Image.open(conf["path"]).convert("RGB")
        except Exception as e:
            print(f"Error opening {conf['path']}: {e}")
            continue

        x_off = padding + c * (tile_size + padding)
        y_off = padding + r * (tile_size + text_height + padding)

        gallery.paste(img, (x_off, y_off))

        text_y = y_off + tile_size + 15

        draw.text((x_off, text_y), conf["name"], font=font_title, fill=(255, 255, 255))
        
        # Truncate desc if too long
        desc = conf["desc"]
        if len(desc) > 50:
            desc = desc[:47] + "..."
            
        draw.text(
            (x_off, text_y + 35),
            desc,
            font=font_desc,
            fill=(200, 200, 200),
        )

        specs = (
            f"Pos: {conf['x']:.4f}, {conf['y']:.4f} | "
            f"W: {conf['width']:.2e} | Iter: {conf['max_iter']}"
        )
        draw.text((x_off, text_y + 60), specs, font=font_desc, fill=(150, 150, 150))
        
        model_info = f"Model: {conf.get('model', 'mandelbrot')}"
        if "mandelbrot_n_exponent" in conf:
            model_info += f"^{conf['mandelbrot_n_exponent']}"
        draw.text((x_off, text_y + 80), model_info, font=font_desc, fill=(150, 150, 150))

    gallery_path = os.path.join(output_dir, "gallery_full.png")
    gallery.save(gallery_path)
    print(f"Gallery saved to {gallery_path}")


if __name__ == "__main__":
    create_gallery()