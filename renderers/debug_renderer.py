from PIL import Image, ImageDraw, ImageFont

class DebugQuadtileRenderer:
    def __init__(self, tile_size=256):
        self.tile_size = tile_size

    def render(self, level, x, y):
        image = Image.new('RGB', (self.tile_size, self.tile_size), color=(240, 240, 240))
        draw = ImageDraw.Draw(image)
        
        # Draw border only
        draw.rectangle([0, 0, self.tile_size-1, self.tile_size-1], outline=(200, 200, 200), width=1)

        # L1,X1,Y1 style text, centered and horizontal
        text = f"L{level},X{x},Y{y}"
        try:
            # ~30% smaller than previous 0.22 factor
            font = ImageFont.truetype("Tahoma.ttf", int(self.tile_size * 0.15))
        except Exception:
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        text_x = (self.tile_size - text_w) / 2
        # Slightly bias upward to look visually centered
        text_y = (self.tile_size - text_h) / 2 - self.tile_size * 0.03
        draw.text((text_x, text_y), text, fill=(0, 0, 0), font=font)
        
        return image
