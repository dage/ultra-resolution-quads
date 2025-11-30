import os
import shutil
import numpy as np
from typing import Union, Optional
from PIL import Image
import fractalshades as fs
import fractalshades.models as fsm
import fractalshades.colors as fscolors
import fractalshades.projection
from fractalshades.postproc import Postproc_batch, Continuous_iter_pp, DEM_normal_pp
from fractalshades.colors.layers import Color_layer, Normal_map_layer, Blinn_lighting

class FractalShadesRenderer:
    """
    A generic wrapper for fractalshades to easily render Mandelbrot tiles/images.
    """
    def __init__(self, output_dir, verbosity=0):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        fs.settings.enable_multithreading = True
        fs.settings.verbosity = verbosity

    def render(self, 
               center_x: Union[float, str], 
               center_y: Union[float, str], 
               width: float, 
               img_size: int = 512, 
               max_iter: int = 2000, 
               filename: Optional[str] = "fractal.png",
               output_path: Optional[str] = None,
               colormap: Union[str, fscolors.Fractal_colormap] = "citrus",
               layer_func: str = None,
               supersampling: str = "3x3",
               batch_prefix: str = "fs_render",
               return_pillow_image: bool = False,
               add_lighting: bool = False):
        """
        Render a single Mandelbrot image.
        
        Args:
            center_x: Center X coordinate (real part). Supports float or string (for high precision).
            center_y: Center Y coordinate (imaginary part). Supports float or string.
            width: Width of the view in complex plane.
            img_size: Pixel width/height of the output image.
            max_iter: Maximum iterations.
            filename: Output filename (relative to output_dir). Used if output_path is None.
            output_path: Absolute or relative path to write the image to. Overrides filename/output_dir.
            colormap: Name of the colormap to use (str) OR a fractalshades.colors.Fractal_colormap object.
            layer_func: String function for color mapping (e.g. "np.power(...)"). 
                        If None, a default high-contrast function is used.
            supersampling: Supersampling mode (e.g. "2x2", "3x3", "None").
            batch_prefix: Temporary prefix for fractalshades batch files.
            return_pillow_image: If True, returns (path, Image object).
            add_lighting: If True, adds 3D lighting effects using DEM normals.
            
        Returns:
            Full path to the rendered image (str), or (path, Image) if return_pillow_image is True.
        """
        
        # Determine final output path
        if output_path:
            final_path = output_path
            # Ensure directory exists
            os.makedirs(os.path.dirname(final_path), exist_ok=True)
        else:
            final_path = os.path.join(self.output_dir, filename)
            os.makedirs(os.path.dirname(final_path), exist_ok=True)

        # 1. Setup Model
        # We use a temporary subdir for the model output to avoid collisions if running in parallel contexts
        # (though this class instance handles one render at a time effectively)
        # Use a hash of parameters or random string to avoid collision? 
        # For now, relying on batch_prefix which caller can randomize if needed.
        model_dir = os.path.join(self.output_dir, f"_{batch_prefix}_tmp")
        if os.path.exists(model_dir):
            shutil.rmtree(model_dir)
        os.makedirs(model_dir, exist_ok=True)
        
        model = fsm.Perturbation_mandelbrot(model_dir)

        # 2. Zoom
        # Note: fractalshades handles string inputs for x/y automatically for arbitrary precision.
        model.zoom(
            precision=128, # Sufficient for most deep zooms; internal auto-adjustment usually kicks in.
            x=center_x,
            y=center_y,
            dx=width,
            nx=img_size,
            xy_ratio=1.0,
            theta_deg=0,
            projection=fs.projection.Cartesian()
        )

        # 3. Calculate Divergence
        model.calc_std_div(
            max_iter=max_iter,
            calc_name="div_layer",
            subset=None,
            M_divergence=1000.0,
            epsilon_stationnary=1.0e-3,
            BLA_eps=1.0e-6
        )

        # 4. Post-processing
        pp = Postproc_batch(model, "div_layer")
        pp.add_postproc("cont_iter", Continuous_iter_pp())
        
        if add_lighting:
            pp.add_postproc("normals", DEM_normal_pp(kind="potential"))

        plotter = fs.Fractal_plotter(pp, final_render=True, supersampling=supersampling)

        # Resolve Colormap
        cmap = None
        if isinstance(colormap, fscolors.Fractal_colormap):
            cmap = colormap
        elif isinstance(colormap, str):
            if colormap not in fscolors.cmap_register:
                # Fallback if specific map not found
                available = list(fscolors.cmap_register.keys())
                print(f"Warning: Colormap '{colormap}' not found. Available: {available[:5]}...")
                cmap = fscolors.cmap_register.get("classic") or fscolors.cmap_register[available[0]]
            else:
                cmap = fscolors.cmap_register[colormap]
        else:
            raise ValueError("colormap must be a string or a fractalshades.colors.Fractal_colormap")

        # Default high-contrast function if none provided
        if layer_func is None:
            # "np.power(np.clip((np.log(x) - 2.6) / 3.4, 0.0, 1.0), 0.45)"
            layer_func = "np.power(np.clip((np.log(x) - 2.6) / 3.4, 0.0, 1.0), 0.45)"

        c_layer = Color_layer(
            "cont_iter",
            func=layer_func,
            colormap=cmap,
            output=True
        )
        
        if add_lighting:
            n_layer = Normal_map_layer("normals", max_slope=45, output=False)
            plotter.add_layer(n_layer)
            
            # Ambient light + 1 directional light source
            lighting = Blinn_lighting(0.5, np.array([1., 1., 1.]))
            lighting.add_light_source(
                k_diffuse=0.8, 
                k_specular=0.2, 
                shininess=350., 
                polar_angle=45., 
                azimuth_angle=45., 
                color=np.array([1.0, 1.0, 1.0])
            )
            c_layer.shade(n_layer, lighting)

        plotter.add_layer(c_layer)

        # 5. Plot
        plotter.plot()

        # 6. Move/Rename Output
        # Fractalshades generates "Color_layer_cont_iter.png" in the model dir
        generated_path = os.path.join(model_dir, "Color_layer_cont_iter.png")
        
        if os.path.exists(generated_path):
            if os.path.exists(final_path):
                os.remove(final_path)
            shutil.move(generated_path, final_path)
        else:
            raise RuntimeError(f"Fractalshades failed to generate image at {generated_path}")

        # Cleanup temp dir
        shutil.rmtree(model_dir)
        
        if return_pillow_image:
            return final_path, Image.open(final_path).convert("RGB")
        
        return final_path