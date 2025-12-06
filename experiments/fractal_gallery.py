import os
import sys
import time
import traceback
from PIL import Image, ImageDraw, ImageFont

# Force disable Numba caching to prevent ReferenceError: underlying object has vanished
os.environ["NUMBA_DISABLE_CACHING"] = "1"
# Also try setting a local cache dir just in case
os.environ["NUMBA_CACHE_DIR"] = os.path.join(os.getcwd(), ".numba_cache")

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.fractal_renderer import FractalShadesRenderer

OUTPUT_DIR = "artifacts/gallery_v2"

GALLERY_ITEMS = [
    {
        "title": "1. Glossy Seahorse",
        "desc": "Mandelbrot with 3D lighting",
        "filename": "01_seahorse_glossy.png",
        "params": {
            "fractal_type": "mandelbrot",
            "x": "-0.746223962861", "y": "-0.0959468433527", "dx": "0.00745",
            "nx": 800, "max_iter": 2000,
            "shade_kind": "glossy",
            "lighting_config": {
                "k_diffuse": 0.4, "k_specular": 30.0, "shininess": 400.0,
                "polar_angle": 135.0, "azimuth_angle": 20.0,
                "gloss_light_color": [1.0, 0.9, 0.9]
            },
            "colormap": "legacy"
        }
    },
    {
        "title": "2. Twin Fieldlines",
        "desc": "Mandelbrot with fieldlines",
        "filename": "02_fieldlines_twin.png",
        "params": {
            "fractal_type": "mandelbrot",
            "x": "-0.1065", "y": "0.9695", "dx": "0.7",
            "nx": 800, "max_iter": 1000,
            "fieldlines_kind": "twin",
            "fieldlines_func": {"n_iter": 4, "swirl": 0.0, "twin_intensity": 0.5},
            "colormap": "ocean"
        }
    },
    {
        "title": "3. Deep Embedded Julia",
        "desc": "Deep zoom perturbation",
        "filename": "03_deep_embedded_julia.png",
        "params": {
            "fractal_type": "mandelbrot",
            "x": "-1.768667862837488812627419470",
            "y": "0.001645580546820209430325900",
            "dx": "12.e-22",
            "nx": 800, "max_iter": 10000, "precision": 30,
            "shade_kind": "standard",
            "colormap": "classic",
            # Fixed: Added zmin/zmax to prevent black image
            "base_layer": "distance_estimation",
            "zmin": 9.015, "zmax": 9.025,
            # Fieldlines disabled for stability in this specific deep zoom context
            "lighting_config": {"k_diffuse": 0.4, "k_specular": 10.0}
        }
    },
    {
        "title": "4. Burning Ship Deep",
        "desc": "BS deep zoom with skew",
        "filename": "04_burning_ship_deep.png",
        "params": {
            "fractal_type": "burning_ship",
            "x": "0.533551593577038561769721161491702555962775680136595415306315189524970818968817900068355227861158570104764433694",
            "y": "1.26175074578870311547721223871955368990255513054155186351034363459852900933566891849764050954410207620093433856",
            "dx": "7.072814368784043e-101",
            "nx": 800, "max_iter": 5000, "precision": 150,
            "xy_ratio": 1.8, "theta_deg": -2.0,
            "skew_params": {
                "skew_00": 1.3141410612942215, "skew_01": 0.8651590600810832,
                "skew_10": 0.6372176654581702, "skew_11": 1.1804627997751416
            },
            "base_layer": "distance_estimation",
            "colormap": "dawn",
            # Fixed: Added probes from example 14
            "zmin": -9.90, "zmax": -4.94
        }
    },
    {
        "title": "5. Perp. Burning Ship",
        "desc": "Glynn Spiral (Hidden)",
        "filename": "05_perp_bs_glynn.png",
        "params": {
            "fractal_type": "perpendicular_burning_ship",
            "flavor": "Perpendicular burning ship",
            "x": "-1.6221172452279831275586824847368230989301274844265",
            "y": "-0.0043849065564689427951877101597546609652950526531633",
            "dx": "4.646303299697506e-40",
            "nx": 800, "max_iter": 20000, "precision": 55,
            "xy_ratio": 1.8, "theta_deg": -2.0,
            "skew_params": {
                "skew_00": 1.011753723519244, "skew_01": -1.157539989768796,
                "skew_10": -0.5299787188179303, "skew_11": 1.5947275737676074
            },
            "base_layer": "distance_estimation",
            "shade_kind": "glossy",
            "colormap": "peacock",
            # Fixed: Added probes from example 18
            "zmin": 6.54, "zmax": 18.42
        }
    },
    {
        "title": "6. Perp. BS Sierpinski",
        "desc": "Sierpinski Carpets",
        "filename": "06_perp_bs_sierpinski.png",
        "params": {
            "fractal_type": "perpendicular_burning_ship",
            "flavor": "Perpendicular burning ship",
            "x": "-1.929319698524937920226708049698305350754670432084006734339806946",
            "y": "-0.0000000000000000007592779387989739090287550144163328879329853232537252481600401185",
            "dx": "7.032184999234219e-55",
            "nx": 800, "max_iter": 20000, "precision": 64,
            "xy_ratio": 1.6, "theta_deg": -26.0,
            "skew_params": {
                "skew_00": 1.05, "skew_01": 0.0,
                "skew_10": -0.1, "skew_11": 0.9523809
            },
            "shade_kind": "glossy",
            "base_layer": "distance_estimation",
            "colormap": "hot",
            # Fixed: Added probes from example 20
            "zmin": 8.71, "zmax": 9.90
        }
    },
    {
        "title": "7. Perp. BS Trees",
        "desc": "Tree structures",
        "filename": "07_perp_bs_trees.png",
        "params": {
            "fractal_type": "perpendicular_burning_ship",
            "flavor": "Perpendicular burning ship",
            "x": "-1.60075649116104853234447567671822519294",
            "y": "-0.00000585584069328913182973043272000146363667",
            "dx": "1.345424030679299e-29",
            "nx": 800, "max_iter": 6000, "precision": 64,
            "xy_ratio": 1.6, "theta_deg": 120.0,
            "skew_params": {
                "skew_00": -0.985244568474214, "skew_01": 0.6137988525,
                "skew_10": 0.8089497623371, "skew_11": -1.518945126681
            },
            "shade_kind": "glossy",
            "colormap": "spring",
            # Added probes from example 21 just in case, though previous run was okay
            "zmin": 7.51, "zmax": 8.06
        }
    },
    {
        "title": "8. Shark Fin",
        "desc": "Shark Fin flavor",
        "filename": "08_shark_fin.png",
        "params": {
            "fractal_type": "shark_fin",
            "flavor": "Shark fin",
            "x": "-0.5", "y": "-0.65", "dx": "0.5", 
            "nx": 800, "max_iter": 1500,
            "colormap": "blue_brown"
        }
    },
    {
        "title": "9. Power Tower",
        "desc": "Tetration map",
        "filename": "09_power_tower.png",
        "params": {
            "fractal_type": "power_tower",
            "x": 1.40735, "y": -3.36277, "dx": 0.0005,
            # Lighter settings: smaller tile + fewer iterations for speed
            "nx": 400, "max_iter": 120,
            "colormap": "flower"
        }
    },
    {
        "title": "10. Multibrot Power 4",
        "desc": "Mandelbrot N=4",
        "filename": "10_multibrot_p4.png",
        "params": {
            "fractal_type": "mandelbrot_n",
            "exponent": 4,
            "x": "0.0", "y": "0.0", "dx": "2.5",
            "nx": 800, "max_iter": 1500,
            "colormap": "autumn"
        }
    }
]

def create_composite_gallery(items, output_path):
    """Creates a labeled grid image of all fractals."""
    print("\nGenerating composite gallery image...")
    
    cols = 5
    rows = (len(items) + cols - 1) // cols
    
    # Config
    tile_w, tile_h = 400, 300 # Resize for grid
    padding = 20
    text_h = 80
    
    full_w = cols * tile_w + (cols + 1) * padding
    full_h = rows * (tile_h + text_h) + (rows + 1) * padding
    
    bg_color = (20, 20, 20)
    text_color = (220, 220, 220)
    
    gallery_img = Image.new("RGB", (full_w, full_h), bg_color)
    draw = ImageDraw.Draw(gallery_img)
    
    # Try to load a font
    try:
        # Mac default
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 16)
        font_small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 12)
    except:
        try:
            # Linux default
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
        except:
            font = ImageFont.load_default()
            font_small = ImageFont.load_default()

    for i, item in enumerate(items):
        r, c = divmod(i, cols)
        
        # Load and resize image
        img_path = os.path.join(OUTPUT_DIR, item["filename"])
        try:
            with Image.open(img_path) as img:
                # Resize preserving aspect ratio logic could go here, but strict resize is easier for grid
                # We generated them at 800x? depending on ratio. Let's crop/resize to fit tile
                img = img.convert("RGB")
                img.thumbnail((tile_w, tile_h), Image.Resampling.LANCZOS)
                
                # Paste coordinates
                x_off = padding + c * (tile_w + padding)
                y_off = padding + r * (tile_h + text_h + padding)
                
                # Center image in slot
                paste_x = x_off + (tile_w - img.width) // 2
                paste_y = y_off + (tile_h - img.height) // 2
                
                gallery_img.paste(img, (paste_x, paste_y))
                
                # Draw text
                text_y = y_off + tile_h + 5
                draw.text((x_off, text_y), item["title"], font=font, fill=text_color)
                draw.text((x_off, text_y + 20), item["desc"], font=font_small, fill=(150, 150, 150))
                duration = item.get("duration_s")
                if duration is not None:
                    draw.text((x_off, text_y + 40), f"Time: {duration:.2f}s", font=font_small, fill=(120, 200, 120))
                
        except Exception as e:
            print(f"Failed to process image {item['filename']}: {e}")

    gallery_img.save(output_path)
    print(f"Gallery saved to: {output_path}")

def run_gallery():
    print(f"Generating diverse gallery in: {OUTPUT_DIR}")
    # Ensure cache dir exists
    os.makedirs(os.environ["NUMBA_CACHE_DIR"], exist_ok=True)
    
    renderer = FractalShadesRenderer(OUTPUT_DIR)
    start_time = time.time()
    
    successful_items = []

    for item in GALLERY_ITEMS:
        print(f"\nRendering {item['title']}...")
        try:
            t0 = time.time()
            renderer.render(filename=item["filename"], **item["params"])
            duration = time.time() - t0
            item_with_duration = dict(item)
            item_with_duration["duration_s"] = duration
            successful_items.append(item_with_duration)
        except Exception as e:
            print(f"❌ Error rendering {item['title']}: {e}")
            traceback.print_exc()

    duration = time.time() - start_time
    print(f"\nAll renders complete in {duration:.2f}s")
    
    if successful_items:
        composite_path = os.path.join(OUTPUT_DIR, "fractal_gallery_composite.png")
        create_composite_gallery(successful_items, composite_path)

if __name__ == "__main__":
    run_gallery()
