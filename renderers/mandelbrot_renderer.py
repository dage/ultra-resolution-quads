from PIL import Image
import colorsys

class MandelbrotDeepZoomRenderer:
    def __init__(self, tile_size=256, max_iter=256):
        self.tile_size = tile_size
        self.max_iter = max_iter
        # Defined bounds for the full view (Level 0)
        self.view_center_re = -0.75
        self.view_center_im = 0.0
        self.view_width = 3.0
        self.view_height = 3.0 # Square tiles, square aspect ratio for simplicity

    def render(self, level, tile_x, tile_y):
        # Number of tiles along one dimension at this level
        num_tiles = 2 ** level
        
        # Size of one tile in the complex plane
        complex_tile_width = self.view_width / num_tiles
        complex_tile_height = self.view_height / num_tiles
        
        # Top-left corner of this specific tile in the complex plane
        # X maps to Real part (increasing left to right)
        # Y maps to Imaginary part (decreasing top to bottom, screen coords)
        
        # Global bounds top-left
        global_min_re = self.view_center_re - self.view_width / 2
        global_max_im = self.view_center_im + self.view_height / 2
        
        tile_min_re = global_min_re + tile_x * complex_tile_width
        tile_max_im = global_max_im - tile_y * complex_tile_height
        
        image = Image.new('RGB', (self.tile_size, self.tile_size))
        pixels = image.load()
        
        # Pixel steps
        step_re = complex_tile_width / self.tile_size
        step_im = complex_tile_height / self.tile_size
        
        for py in range(self.tile_size):
            curr_im = tile_max_im - py * step_im
            for px in range(self.tile_size):
                curr_re = tile_min_re + px * step_re
                
                c = complex(curr_re, curr_im)
                z = 0j
                iter_count = 0
                
                while abs(z) <= 4 and iter_count < self.max_iter:
                    z = z*z + c
                    iter_count += 1
                
                if iter_count == self.max_iter:
                    color = (0, 0, 0)
                else:
                    # Simple coloring
                    hue = (iter_count % 64) / 64.0
                    saturation = 0.8
                    value = 1.0
                    r, g, b = colorsys.hsv_to_rgb(hue, saturation, value)
                    color = (int(r*255), int(g*255), int(b*255))
                
                pixels[px, py] = color
                
        return image
