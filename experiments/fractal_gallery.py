import sys
import os
from PIL import Image, ImageDraw, ImageFont

# Add project root to path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from backend.fractal_renderer import FractalShadesRenderer

def create_gallery():
    output_dir = os.path.join("artifacts", "gallery_experiment")
    # Initialize renderer with verbosity=1 to see some progress from fractalshades
    renderer = FractalShadesRenderer(output_dir, verbosity=1)
    
    # Define fractals
    # We select a few interesting spots. 
    # Coloring functions
    # Classic: High contrast highlight for low-mid iteration ranges. Clips high iterations.
    FUNC_CLASSIC = "np.power(np.clip((np.log(x) - 2.6) / 3.4, 0.0, 1.0), 0.45)"
    
    # Cyclic: Sine wave based on log(iterations). Never clips, creates bands.
    # Frequency 10.0: moderate banding.
    FUNC_CYCLIC = "0.5 + 0.5 * np.sin(10.0 * np.log(x))"
    
    fractals = [
        {
            "name": "Seahorse Valley Overview",
            "desc": "The classic valley between head and body.",
            "x": -0.745,
            "y": 0.1,
            "width": 0.05,
            "max_iter": 5000,
            "colormap": "citrus",
            "func": FUNC_CLASSIC
        },
        {
            "name": "Elephant Spirals",
            "desc": "Spirals near the Elephant Valley.",
            "x": 0.28,
            "y": 0.01,
            "width": 0.5,
            "max_iter": 3000,
            "colormap": "classic",
            "func": FUNC_CLASSIC
        },
        {
            "name": "Mini Brot Neck",
            "desc": "The connection to the main set.",
            "x": -1.76,
            "y": 0.0,
            "width": 0.5,
            "max_iter": 5000,
            "colormap": "classic",
            "func": FUNC_CLASSIC
        },
        {
            "name": "Triple Spiral",
            "desc": "Deep zoom into a spiral structure.",
            "x": -0.088,
            "y": 0.654,
            "width": 0.01,
            "max_iter": 2500,
            "colormap": "sunset",
            "func": FUNC_CLASSIC
        }
    ]

    rendered_files = []
    
    print(f"Rendering {len(fractals)} fractals...")
    
    for i, f_conf in enumerate(fractals):
        print(f"\n[{i+1}/{len(fractals)}] Rendering {f_conf['name']}...")
        fname = f"fractal_{i}.png"
        
        # Render using the generic wrapper
        try:
            path = renderer.render(
                center_x=f_conf["x"],
                center_y=f_conf["y"],
                width=f_conf["width"],
                img_size=512,
                max_iter=f_conf["max_iter"],
                filename=fname,
                colormap=f_conf.get("colormap", "classic"),
                layer_func=f_conf.get("func")
            )
            
            print(f"  Success: {path}")
                
            rendered_files.append((path, f_conf))
            
        except Exception as e:
            print(f"  ERROR rendering {f_conf['name']}: {e}")

    if not rendered_files:
        print("No images rendered. Exiting.")
        return

    # Create Gallery Image
    print("\nConstructing gallery...")
    
    # Layout: 2x2 grid (or adaptable)
    cols = 2
    rows = (len(rendered_files) + cols - 1) // cols
    
    tile_size = 512
    padding = 50
    text_height = 100
    
    gallery_w = cols * tile_size + (cols + 1) * padding
    gallery_h = rows * (tile_size + text_height) + (rows + 1) * padding
    
    gallery = Image.new("RGB", (gallery_w, gallery_h), (30, 30, 30))
    draw = ImageDraw.Draw(gallery)
    
    # Font handling
    try:
        # Try to find a decent font on the system. 
        # Common paths for macOS/Linux/Windows
        font_paths = [
            "/System/Library/Fonts/Helvetica.ttc", # macOS
            "/System/Library/Fonts/Supplemental/Arial.ttf", # macOS
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", # Linux
            "C:\\Windows\\Fonts\\arial.ttf" # Windows
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
    except:
        print("Using default font.")
        font_title = ImageFont.load_default()
        font_desc = ImageFont.load_default()

    for i, (path, conf) in enumerate(rendered_files):
        r = i // cols
        c = i % cols
        
        try:
            img = Image.open(path).convert("RGB")
            
            x_off = padding + c * (tile_size + padding)
            y_off = padding + r * (tile_size + text_height + padding)
            
            gallery.paste(img, (x_off, y_off))
            
            # Draw text
            text_y = y_off + tile_size + 15
            
            # Draw Title
            draw.text((x_off, text_y), conf["name"], font=font_title, fill=(255, 255, 255))
            
            # Draw Description
            draw.text((x_off, text_y + 35), conf["desc"], font=font_desc, fill=(200, 200, 200))
            
            # Draw Tech Specs
            specs = f"Pos: {conf['x']}, {conf['y']} | Width: {conf['width']} | Iter: {conf['max_iter']}"
            draw.text((x_off, text_y + 60), specs, font=font_desc, fill=(150, 150, 150))
            
        except Exception as e:
            print(f"Error adding {path} to gallery: {e}")

    gallery_path = os.path.join(output_dir, "gallery_full.png")
    gallery.save(gallery_path)
    print(f"Gallery saved to {gallery_path}")

if __name__ == "__main__":
    create_gallery()
