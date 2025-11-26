import math
from PIL import Image

class MandelbrotDeepZoomRenderer:
    def __init__(self, tile_size=256, max_iter=1024):
        self.tile_size = tile_size
        self.max_iter = max_iter
        # Defined bounds for the full view (Level 0)
        self.view_center_re = -0.75
        self.view_center_im = 0.0
        self.view_width = 3.0
        self.view_height = 3.0 # Square tiles, square aspect ratio for simplicity

        # Neon-inspired palette for a futuristic vibe (dark base to cyan/magenta highlights)
        self.palette = [
            (8, 6, 18),
            (12, 60, 180),
            (24, 190, 255),
            (140, 255, 255),
            (255, 90, 210),
            (20, 10, 40)
        ]

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

                color = self._color_from_iteration(iter_count, z)

                pixels[px, py] = color

        return image

    def _color_from_iteration(self, iter_count, z):
        if iter_count >= self.max_iter:
            return (4, 6, 12)  # Deep space interior

        # Smooth iteration count reduces banding for gradients
        mag = abs(z)
        smooth_iter = iter_count + 1 - math.log(math.log(mag)) / math.log(2)
        t = max(0.0, min(1.0, smooth_iter / self.max_iter))

        # Small oscillation adds a subtle holographic shimmer
        shimmer = 0.04 * math.sin(t * math.pi * 10)
        t = max(0.0, min(1.0, t + shimmer))

        return self._sample_palette(t)

    def _sample_palette(self, t):
        # Map t in [0,1] across the palette stops
        if not self.palette:
            return (0, 0, 0)

        scaled = t * (len(self.palette) - 1)
        idx = int(math.floor(scaled))
        frac = scaled - idx

        if idx >= len(self.palette) - 1:
            return self.palette[-1]

        c1 = self.palette[idx]
        c2 = self.palette[idx + 1]
        r = int(c1[0] + (c2[0] - c1[0]) * frac)
        g = int(c1[1] + (c2[1] - c1[1]) * frac)
        b = int(c1[2] + (c2[2] - c1[2]) * frac)
        return (r, g, b)
