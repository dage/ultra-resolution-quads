from PIL import Image, ImageDraw, ImageFont

class DebugQuadtileRenderer:
    def __init__(self, tile_size=256):
        self.tile_size = tile_size

    def render(self, level, x, y):
        image = Image.new('RGB', (self.tile_size, self.tile_size), color=(240, 240, 240))
        draw = ImageDraw.Draw(image)
        
        # Draw border
        draw.rectangle([0, 0, self.tile_size-1, self.tile_size-1], outline=(200, 200, 200), width=1)
        
        # Draw text
        text = f"L{level}\nx{x}\ny{y}"
        # Simple centering (approximate without font metrics if default font is used)
        # But let's try to be a bit nicer if possible, though default font is small.
        
        # We can't easily load system fonts reliably across platforms without knowing paths, 
        # so we'll use the default PIL font which is very small, or try to load a common one if available.
        # For simplicity/robustness, we stick to default or a simple bitmap font if available.
        
        # better: Draw a crosshair
        mid = self.tile_size // 2
        draw.line([(mid, 0), (mid, self.tile_size)], fill=(220, 220, 220))
        draw.line([(0, mid), (self.tile_size, mid)], fill=(220, 220, 220))

        # Draw text in black
        draw.text((10, 10), text, fill=(0, 0, 0))
        
        return image
