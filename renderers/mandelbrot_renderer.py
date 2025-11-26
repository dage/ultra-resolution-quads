import moderngl
import numpy as np
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
        
        # Initialize ModernGL context
        self.ctx = moderngl.create_standalone_context()
        
        # Compile shader
        self.prog = self.ctx.program(
            vertex_shader=self._get_vertex_shader(),
            fragment_shader=self._get_fragment_shader()
        )

        # Setup quad geometry
        vertices = np.array([
            [0.0, 0.0],
            [1.0, 0.0],
            [1.0, 1.0],
            [0.0, 1.0],
        ], dtype='f4')
        indices = np.array([0, 1, 2, 2, 3, 0], dtype='i4')

        self.vbo = self.ctx.buffer(vertices.tobytes())
        self.ibo = self.ctx.buffer(indices.tobytes())
        self.vao = self.ctx.simple_vertex_array(self.prog, self.vbo, 'in_vert', index_buffer=self.ibo)

        # Setup framebuffer
        self.texture = self.ctx.texture((self.tile_size, self.tile_size), 4)
        self.fbo = self.ctx.framebuffer(color_attachments=[self.texture])
        
        # Precompute palette uniforms
        self._update_palette_uniforms()

    def supports_multithreading(self):
        return False

    def _get_vertex_shader(self):
        return '''
            #version 330
            in vec2 in_vert;
            out vec2 v_text;
            void main() {
                v_text = in_vert;
                gl_Position = vec4(2.0 * in_vert - 1.0, 0.0, 1.0);
            }
        '''

    def _get_fragment_shader(self):
        # Note: max_palette matches len(self.palette)
        max_palette = len(self.palette)
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

    def _update_palette_uniforms(self):
        normalized = [(c[0] / 255.0, c[1] / 255.0, c[2] / 255.0) for c in self.palette]
        flat = np.array(normalized, dtype='f4').reshape(-1)
        
        if 'u_palette' in self.prog:
            self.prog['u_palette'].write(flat.tobytes())
        if 'u_palette_count' in self.prog:
            self.prog['u_palette_count'].value = len(normalized)

    def render(self, level, tile_x, tile_y):
        self.fbo.use()
        
        # Update uniforms
        if 'u_view_center_re' in self.prog: self.prog['u_view_center_re'].value = self.view_center_re
        if 'u_view_center_im' in self.prog: self.prog['u_view_center_im'].value = self.view_center_im
        if 'u_view_width' in self.prog: self.prog['u_view_width'].value = self.view_width
        if 'u_view_height' in self.prog: self.prog['u_view_height'].value = self.view_height
        if 'u_level' in self.prog: self.prog['u_level'].value = level
        if 'u_tile_x' in self.prog: self.prog['u_tile_x'].value = tile_x
        if 'u_tile_y' in self.prog: self.prog['u_tile_y'].value = tile_y
        if 'u_tile_size' in self.prog: self.prog['u_tile_size'].value = self.tile_size
        if 'u_max_iter' in self.prog: self.prog['u_max_iter'].value = self.max_iter
        
        self.ctx.clear(0.0, 0.0, 0.0, 1.0)
        self.vao.render()
        
        pixel_data = self.texture.read()
        # The texture format is 4 channels (RGBA) from `self.ctx.texture((..., ...), 4)`
        array = np.frombuffer(pixel_data, dtype='u1').reshape((self.tile_size, self.tile_size, 4))
        
        # Convert to RGB image to match original renderer output
        return Image.fromarray(array, 'RGBA').convert('RGB')