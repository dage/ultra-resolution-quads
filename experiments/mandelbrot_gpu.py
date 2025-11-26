#!/usr/bin/env python3
"""
Experiment: compare ModernGL GPU Mandelbrot output with the existing CPU renderer.
This script renders the same tile via the CPU renderer, then renders via ModernGL
and reports pixel-level differences so we can iteratively converge on parity.
"""

import argparse
import pathlib
import sys
from dataclasses import dataclass
import time

import moderngl
import numpy as np
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from renderers.mandelbrot_renderer import MandelbrotDeepZoomRenderer


class MandelbrotGPU:
    """Headless ModernGL helper for rendering a fullscreen Mandelbrot shader."""

    def __init__(self, width: int = 800, height: int = 600):
        self.width = width
        self.height = height
        self.ctx = moderngl.create_standalone_context()

    def render_with_shader(self, fragment_shader: str, **uniforms):
        """Compile the GLSL shader, render, and return the RGBA pixel array."""
        vertex_shader = '''
            #version 330
            in vec2 in_vert;
            out vec2 v_text;
            void main() {
                v_text = in_vert;
                gl_Position = vec4(2.0 * in_vert - 1.0, 0.0, 1.0);
            }
        '''

        program = self.ctx.program(vertex_shader=vertex_shader, fragment_shader=fragment_shader)

        vertices = np.array([
            [0.0, 0.0],
            [1.0, 0.0],
            [1.0, 1.0],
            [0.0, 1.0],
        ], dtype='f4')
        indices = np.array([0, 1, 2, 2, 3, 0], dtype='i4')

        vbo = self.ctx.buffer(vertices.tobytes())
        ibo = self.ctx.buffer(indices.tobytes())
        vao = self.ctx.simple_vertex_array(program, vbo, 'in_vert', index_buffer=ibo)

        texture = self.ctx.texture((self.width, self.height), 4)
        framebuffer = self.ctx.framebuffer(color_attachments=[texture])
        framebuffer.use()

        for name, value in uniforms.items():
            if name not in program:
                continue
            uniform = program[name]
            if isinstance(value, (int, float)):
                uniform.value = value
            elif isinstance(value, (tuple, list)):
                uniform.value = tuple(value)
            elif isinstance(value, np.ndarray):
                uniform.write(value.astype('f4').tobytes())

        self.ctx.clear(0.0, 0.0, 0.0, 1.0)
        vao.render()

        pixel_data = texture.read()
        return np.frombuffer(pixel_data, dtype='u1').reshape((self.height, self.width, 4))


def build_palette_uniforms(palette):
    """Normalize palette entries into 0..1 floats for the shader."""
    normalized = [(c[0] / 255.0, c[1] / 255.0, c[2] / 255.0) for c in palette]
    flat = np.array(normalized, dtype='f4').reshape(-1)
    return normalized, flat


def create_mandelbrot_shader(max_palette=6):
    """Return the GLSL fragment shader that mirrors the CPU renderer logic."""
    return f'''
        #version 330
        const float PI = 3.141592653589793;
        uniform float u_view_center_re;
        uniform float u_view_center_im;
        uniform float u_view_width;
        uniform float u_view_height;
        uniform int u_level;
        uniform int u_tile_x;
        uniform int u_tile_y;
        uniform int u_tile_size;
        uniform int u_max_iter;
        uniform vec3 u_palette[{max_palette}];
        uniform int u_palette_count;
        out vec4 color;

        vec3 sample_palette(float t) {{
            if (u_palette_count <= 0) {{
                return vec3(0.0);
            }}
            float scaled = t * float(u_palette_count - 1);
            int idx = int(floor(scaled));
            idx = clamp(idx, 0, u_palette_count - 1);
            if (idx >= u_palette_count - 1) {{
                return u_palette[u_palette_count - 1];
            }}
            float frac = scaled - float(idx);
            return mix(u_palette[idx], u_palette[idx + 1], frac);
        }}

        void main() {{
            float complex_tile_width = u_view_width / pow(2.0, float(u_level));
            float complex_tile_height = u_view_height / pow(2.0, float(u_level));

            float global_min_re = u_view_center_re - u_view_width / 2.0;
            float global_max_im = u_view_center_im + u_view_height / 2.0;
            float tile_min_re = global_min_re + float(u_tile_x) * complex_tile_width;
            float tile_max_im = global_max_im - float(u_tile_y) * complex_tile_height;

            float step_re = complex_tile_width / float(u_tile_size);
            float step_im = complex_tile_height / float(u_tile_size);

            float px = gl_FragCoord.x - 0.5;
            float py = gl_FragCoord.y - 0.5;

            float curr_re = tile_min_re + px * step_re;
            float curr_im = tile_max_im - py * step_im;

            float x = 0.0;
            float y = 0.0;
            int iter = 0;

            while (x * x + y * y <= 4.0 && iter < u_max_iter) {{
                float xtemp = x * x - y * y + curr_re;
                y = 2.0 * x * y + curr_im;
                x = xtemp;
                iter++;
            }}

            if (iter >= u_max_iter) {{
                color = vec4(4.0 / 255.0, 6.0 / 255.0, 12.0 / 255.0, 1.0);
                return;
            }}

            float mag = sqrt(x * x + y * y);
            float smooth_iter = float(iter) + 1.0 - log(log(max(mag, 1e-8))) / log(2.0);
            float t = clamp(smooth_iter / float(u_max_iter), 0.0, 1.0);
            float shimmer = 0.04 * sin(t * PI * 10.0);
            t = clamp(t + shimmer, 0.0, 1.0);

            vec3 rgb = sample_palette(t);
            color = vec4(rgb, 1.0);
        }}
    '''


def compare_arrays(cpu_array: np.ndarray, gpu_array: np.ndarray):
    """Compute max/mean per-channel difference and the number of mismatched pixels."""
    gpu_rgb = gpu_array[..., :3]
    diff = np.abs(cpu_array.astype(np.int16) - gpu_rgb.astype(np.int16))
    max_diff = int(diff.max())
    mean_diff = float(diff.mean())
    mismatch_pixels = int(np.count_nonzero(np.any(diff != 0, axis=2)))
    return max_diff, mean_diff, mismatch_pixels, diff


@dataclass
class RenderConfig:
    level: int
    tile_x: int
    tile_y: int
    tile_size: int
    max_iter: int


def main():
    parser = argparse.ArgumentParser(
        description="Compare CPU vs ModernGL Mandelbrot rendering for a specific tile."
    )
    parser.add_argument("--level", type=int, default=0, help="Zoom level (powers of two tiles).")
    parser.add_argument("--tile-x", type=int, default=0, help="Tile index along the real axis.")
    parser.add_argument("--tile-y", type=int, default=0, help="Tile index along the imaginary axis.")
    parser.add_argument("--tile-size", type=int, default=256, help="Pixel resolution of the tile.")
    parser.add_argument("--max-iter", type=int, default=1024, help="Maximum Mandelbrot iterations.")
    parser.add_argument("--save", action="store_true", help="Save CPU/GPU outputs and diff.")
    args = parser.parse_args()

    config = RenderConfig(
        level=args.level,
        tile_x=args.tile_x,
        tile_y=args.tile_y,
        tile_size=args.tile_size,
        max_iter=args.max_iter,
    )

    cpu_renderer = MandelbrotDeepZoomRenderer(tile_size=config.tile_size, max_iter=config.max_iter)
    print("Rendering tile via CPU renderer...")
    cpu_start = time.perf_counter()
    cpu_image = cpu_renderer.render(config.level, config.tile_x, config.tile_y)
    cpu_duration = time.perf_counter() - cpu_start
    cpu_array = np.array(cpu_image, dtype=np.uint8)

    gpu_renderer = MandelbrotGPU(width=config.tile_size, height=config.tile_size)
    shader = create_mandelbrot_shader()
    palette_normalized, palette_flat = build_palette_uniforms(cpu_renderer.palette)

    uniforms = {
        "u_view_center_re": cpu_renderer.view_center_re,
        "u_view_center_im": cpu_renderer.view_center_im,
        "u_view_width": cpu_renderer.view_width,
        "u_view_height": cpu_renderer.view_height,
        "u_level": config.level,
        "u_tile_x": config.tile_x,
        "u_tile_y": config.tile_y,
        "u_tile_size": config.tile_size,
        "u_max_iter": config.max_iter,
        "u_palette_count": len(palette_normalized),
    }

    uniforms["u_palette"] = palette_flat

    print("Rendering tile via GPU renderer (ModernGL)...")
    gpu_start = time.perf_counter()
    gpu_array = gpu_renderer.render_with_shader(shader, **uniforms)
    gpu_duration = time.perf_counter() - gpu_start

    max_diff, mean_diff, mismatch_pixels, diff_map = compare_arrays(cpu_array, gpu_array)

    total_pixels = config.tile_size * config.tile_size
    print(f"Max channel difference: {max_diff}")
    print(f"Mean channel difference: {mean_diff:.4f}")
    print(f"Mismatched pixels: {mismatch_pixels} / {total_pixels}")
    print(f"CPU render time: {cpu_duration:.3f}s")
    print(f"GPU render time: {gpu_duration:.3f}s")
    if mean_diff < 1.0:
        print("🟢 Mean difference below 1 → pass")
    else:
        print("🟥 Mean difference 1 or higher → fail")

    if args.save:
        Image.fromarray(cpu_array, mode="RGB").save("cpu_mandelbrot.png")
        Image.fromarray(gpu_array, mode="RGBA").save("gpu_mandelbrot.png")
        diff_rgb = np.clip(diff_map.astype(np.uint8), 0, 255)
        Image.fromarray(diff_rgb, mode="RGB").save("difference.png")
        print("Saved cpu_mandelbrot.png, gpu_mandelbrot.png, and difference.png")


if __name__ == "__main__":
    main()
