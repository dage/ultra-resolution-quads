import os
import shutil
import numpy as np
from typing import Union, Optional, List
from PIL import Image

# Work around numba caching issues on some platforms (e.g., Python 3.12 / M-series Macs)
os.environ.setdefault("NUMBA_DISABLE_CACHING", "1")

import fractalshades as fs
import fractalshades.models as fsm
import fractalshades.colors as fscolors
import fractalshades.projection
from fractalshades.postproc import (
    Postproc_batch,
    Continuous_iter_pp,
    DEM_normal_pp,
    Fieldlines_pp
)
from fractalshades.colors.layers import (
    Color_layer,
    Normal_map_layer,
    Blinn_lighting
)

class FractalShadesRenderer:
    """
    A generic wrapper for fractalshades to easily render Mandelbrot tiles/images.
    """
    def __init__(self, output_dir, verbosity=0):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        fs.settings.enable_multithreading = True
        fs.settings.verbosity = verbosity

    def _create_model(self, model_name: str, directory: str, mandelbrot_n_exponent: int, use_perturbation: bool = False):
        """
        Factory for different fractal models to allow more diverse galleries.
        """
        name = (model_name or "mandelbrot").lower()

        if use_perturbation:
            # Deep zoom models
            if name == "mandelbrot":
                return fsm.Perturbation_mandelbrot(directory)
            elif name == "burning_ship":
                return fsm.Perturbation_burning_ship(directory)
            # Fallback to standard if perturbation version not handled explicitly or available
            # For now, we only support perturbation for these two common types.

        if name == "mandelbrot":
            return fsm.Mandelbrot(directory)
        if name == "burning_ship":
            return fsm.Burning_ship(directory)
        if name == "mandelbrot_n":
            return fsm.Mandelbrot_N(directory, exponent=mandelbrot_n_exponent)
        if name == "power_tower":
            return fsm.Power_tower(directory)
            
        # Fallback
        return fsm.Mandelbrot(directory)

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
               
               # Visualization & Features
               visualization: str = "continuous_iter", # "continuous_iter", "dem", "fieldlines"
               add_lighting: bool = False, 
               interior_color: Optional[str] = None,
               
               # Model Configuration
               model: str = "mandelbrot", # treated as 'fractal_type'
               mandelbrot_n_exponent: int = 3,
               
               # Deep Zoom / Perturbation
               use_perturbation: bool = False,
               dps: Optional[int] = None,
               
               # Burning Ship Specific
               skew_matrix: Optional[tuple] = None, # (00, 01, 10, 11)
               
               # Projection
               projection_type: str = "cartesian", # "cartesian", "expmap", "moebius"
               projection_params: Optional[dict] = None
               ):
        """
        Render a single fractal image.
        
        Args:
            center_x, center_y: Coordinates (float or string for high precision).
            width: View width.
            img_size: Output resolution.
            max_iter: Max iterations.
            filename, output_path: Output destination.
            colormap: Colormap name or object.
            layer_func: Custom color mapping function string.
            supersampling: Antialiasing mode ("2x2", "3x3", "None").
            batch_prefix: Temp file prefix.
            return_pillow_image: Return PIL object.
            visualization: "continuous_iter" (default), "dem", "fieldlines".
            add_lighting: Enable 3D lighting (requires DEM or compatible visualization).
            interior_color: Color for points inside the set (e.g., "black", "white").
            model: Fractal type ("mandelbrot", "burning_ship", "mandelbrot_n", "power_tower").
            mandelbrot_n_exponent: Exponent for Mandelbrot_N.
            use_perturbation: Enable perturbation theory for deep zooms.
            dps: Decimal precision for perturbation (optional).
            skew_matrix: (skew_00, skew_01, skew_10, skew_11) for Burning Ship un-skewing.
            projection_type: "cartesian", "expmap", or "moebius".
            projection_params: Dict of params for the chosen projection.
        """
        
        # Determine final output path
        if output_path:
            final_path = output_path
            os.makedirs(os.path.dirname(final_path), exist_ok=True)
        else:
            final_path = os.path.join(self.output_dir, filename)
            os.makedirs(os.path.dirname(final_path), exist_ok=True)

        # 1. Setup Model
        model_dir = os.path.join(self.output_dir, f"_{batch_prefix}_tmp")
        if os.path.exists(model_dir):
            shutil.rmtree(model_dir)
        os.makedirs(model_dir, exist_ok=True)
        
        fractal_model = self._create_model(model, model_dir, mandelbrot_n_exponent, use_perturbation)

        # 2. Zoom / Projection
        zoom_kwargs = {
            "x": center_x,
            "y": center_y,
            "dx": width,
            "nx": img_size,
            "xy_ratio": 1.0,
            "theta_deg": 0,
        }

        # Handle Skew (only for Burning Ship / relevant models if they support it)
        if skew_matrix:
            zoom_kwargs.update({
                "has_skew": True,
                "skew_00": skew_matrix[0],
                "skew_01": skew_matrix[1],
                "skew_10": skew_matrix[2],
                "skew_11": skew_matrix[3]
            })

        # Handle Projection
        if projection_type == "expmap":
            zoom_kwargs["projection"] = fs.projection.Expmap(**(projection_params or {}))
        elif projection_type == "moebius":
            zoom_kwargs["projection"] = fs.projection.Moebius(**(projection_params or {}))
        else:
            zoom_kwargs["projection"] = fs.projection.Cartesian()
            
        # Handle DPS for perturbation
        if use_perturbation and dps is not None:
            zoom_kwargs["dps"] = dps

        fractal_model.zoom(**zoom_kwargs)

        # 3. Calculate
        # Define calculations based on visualization type
        calc_name = "div_layer"
        calc_kwargs = {
            "calc_name": calc_name,
            "subset": None,
            "max_iter": max_iter,
            "M_divergence": 1000.0,
        }

        # Perturbation models typically have a slightly different calc interface or just work.
        try:
            fractal_model.calc_std_div(
                epsilon_stationnary=1.0e-3,
                **calc_kwargs,
            )
        except TypeError:
            # Some models might not take epsilon_stationnary
            fractal_model.calc_std_div(**calc_kwargs)

        # 4. Post-processing
        pp = Postproc_batch(fractal_model, calc_name)
        
        # Setup layers
        if visualization == "fieldlines":
            # Removed damping_ratio as it's not supported in this version of fractalshades
            pp.add_postproc("field", Fieldlines_pp(n_iter=4, swirl=0.0))
            layer_name = "field"
        elif visualization == "dem":
            # For DEM, we use continuous iter but will likely rely on lighting for the effect
            # or we could use a different postproc if available, but keeping it simple.
            pp.add_postproc("dem", Continuous_iter_pp())
            layer_name = "dem"
        else: # continuous_iter
            pp.add_postproc("cont_iter", Continuous_iter_pp())
            layer_name = "cont_iter"
            
        if add_lighting:
            pp.add_postproc("normals", DEM_normal_pp(kind="potential"))

        plotter = fs.Fractal_plotter(pp, final_render=True, supersampling=supersampling)

        # Resolve Colormap
        cmap = None
        if isinstance(colormap, fscolors.Fractal_colormap):
            cmap = colormap
        elif isinstance(colormap, str):
            if colormap not in fscolors.cmap_register:
                # Fallback
                available = list(fscolors.cmap_register.keys())
                print(f"Warning: Colormap '{colormap}' not found. Available: {available[:5]}...")
                cmap = fscolors.cmap_register.get("classic") or fscolors.cmap_register[available[0]]
            else:
                cmap = fscolors.cmap_register[colormap]
        else:
            raise ValueError("colormap must be a string or a fractalshades.colors.Fractal_colormap")

        # Default high-contrast function if none provided
        if layer_func is None:
            if visualization == "fieldlines":
                layer_func = "np.sin(x * 8.0)" # Simple default for fieldlines
            elif visualization == "dem":
                layer_func = "np.power(x, 0.2)" # Soften DEM
            else:
                layer_func = "np.power(np.clip((np.log(x) - 2.6) / 3.4, 0.0, 1.0), 0.45)"

        c_layer = Color_layer(
            layer_name,
            func=layer_func,
            colormap=cmap,
            output=True
        )
        
        if add_lighting:
            n_layer = Normal_map_layer("normals", max_slope=45, output=False)
            plotter.add_layer(n_layer)
            
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
        
        # Mask for interior points if requested
        if interior_color:
            pass

        # 5. Plot
        plotter.plot()

        # 6. Move/Rename Output
        # The output filename depends on the layer name
        generated_filename = f"Color_layer_{layer_name}.png"
        generated_path = os.path.join(model_dir, generated_filename)
        
        if os.path.exists(generated_path):
            if os.path.exists(final_path):
                os.remove(final_path)
            shutil.move(generated_path, final_path)
        else:
            # Debugging help: list what IS there
            listing = os.listdir(model_dir)
            raise RuntimeError(f"Fractalshades failed to generate image at {generated_path}. Found: {listing}")

        # Cleanup temp dir
        shutil.rmtree(model_dir)
        
        if return_pillow_image:
            return final_path, Image.open(final_path).convert("RGB")
        
        return final_path