import os
import sys
import shutil
import contextlib
import numpy as np
from typing import Union, Optional, List, Dict, Any, Literal

# Work around numba caching issues on some platforms
# We must configure Numba BEFORE importing fractalshades
# Permanently disable caching to avoid pickle failures with @njit(cache=True).
os.environ["NUMBA_DISABLE_CACHING"] = "1"

try:
    import numba

    _original_njit = numba.njit

    def _no_cache_njit(*args, **kwargs):
        kwargs["cache"] = False
        return _original_njit(*args, **kwargs)

    numba.njit = _no_cache_njit
except ImportError:
    pass

import fractalshades as fs

import fractalshades.models as fsm
import fractalshades.colors as fscolors
import fractalshades.projection
from fractalshades.postproc import (
    Postproc_batch,
    Continuous_iter_pp,
    DEM_normal_pp,
    Fieldlines_pp,
    DEM_pp,
    Raw_pp,
)
from fractalshades.colors.layers import (
    Color_layer,
    Normal_map_layer,
    Blinn_lighting,
    Grey_layer,
    Bool_layer,
    Virtual_layer,
    Overlay_mode
)

# Import custom models
try:
    from . import fractal_renderer_models as cm
except ImportError:
    import fractal_renderer_models as cm

class FractalShadesRenderer:
    """
    A versatile renderer for fractalshades models, designed to support
    diverse gallery examples including deep zooms, custom flavors, and advanced coloring.
    """
    def __init__(self, output_dir, verbosity=0):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        fs.settings.enable_multithreading = True
        fs.settings.verbosity = verbosity
        fs.settings.inspect_calc = False  # suppress detailed perturbation loop logs

    def _create_model(self, 
                      model_name: str, 
                      directory: str, 
                      use_perturbation: bool = False, 
                      **kwargs):
        """
        Factory for fractal models.
        """
        name = (model_name or "mandelbrot").lower()
        
        # 1. Handle Burning Ship and its flavors (Shark Fin, Perpendicular)
        if name in ["burning_ship", "shark_fin", "perpendicular_burning_ship"]:
            flavor = kwargs.get("flavor", "Burning ship")
            
            # Map semantic names to flavors if not explicitly provided
            if name == "shark_fin":
                flavor = "Shark fin"
            elif name == "perpendicular_burning_ship":
                flavor = "Perpendicular burning ship"
            
            if use_perturbation:
                return fsm.Perturbation_burning_ship(directory, flavor=flavor)
            else:
                return fsm.Burning_ship(directory, flavor=flavor)

        # 2. Handle Mandelbrot and its variants
        if name == "mandelbrot":
            if use_perturbation:
                return fsm.Perturbation_mandelbrot(directory)
            return fsm.Mandelbrot(directory)
        
        if name == "mandelbrot_n":
            exponent = kwargs.get("exponent", 3)
            if use_perturbation:
                 return fsm.Perturbation_mandelbrot_N(directory, exponent=exponent)
            return fsm.Mandelbrot_N(directory, exponent=exponent)

        # 3. Handle Power Tower (Tetration)
        if name == "power_tower":
            return fsm.Power_tower(directory)

        # 4. Custom Models (from fractal_renderer_models)
        # Note: these generally don't support perturbation in the standard FS way 
        # unless implemented there.
        if use_perturbation:
             print(f"Warning: Perturbation likely not supported for custom model '{name}'.")

        if name in ["mandelbar", "tricorn"]:
            return cm.Mandelbar(directory)
        if name == "phoenix":
            return cm.Phoenix(directory, **kwargs)
        if name == "celtic":
            return cm.Celtic(directory)
        if name == "nova":
            return cm.Nova(directory, **kwargs)
        if name == "julia":
             if 'c_val' not in kwargs:
                 raise ValueError("Julia model requires 'c_val' parameter.")
             return cm.Julia(directory, c_val=kwargs['c_val'])
            
        # Fallback
        print(f"Warning: Model '{name}' not found. Defaulting to Mandelbrot.")
        return fsm.Mandelbrot(directory)

    def render(self, 
               # --- Core Model Config ---
               fractal_type: str = "mandelbrot", 
               flavor: Optional[str] = None,
               exponent: int = 3,
               fractal_params: Optional[Dict[str, Any]] = None,
               
               # --- Zoom & Projection ---
               x: Union[str, float] = "-0.5", 
               y: Union[str, float] = "0.0", 
               dx: Union[str, float] = "3.0", 
               nx: int = 800, 
               xy_ratio: float = 1.0, 
               theta_deg: float = 0.0, 
               projection: str = "cartesian", # "cartesian", "expmap"
               skew_params: Optional[Dict[str, float]] = None, # {skew_00, skew_01...}
               precision: Optional[int] = None, # dps
               
               # --- Calculation ---
               max_iter: int = 2000, 
               m_divergence: float = 1000.0,
               interior_detect: bool = False,
               epsilon_stationnary: float = 0.001,
               calc_args: Optional[Dict[str, Any]] = None,
               
               # --- Coloring / Plotting ---
               base_layer: Literal["continuous_iter", "distance_estimation"] = "continuous_iter",
               colormap: Union[str, fscolors.Fractal_colormap] = "classic",
               invert_colormap: bool = False,
               zmin: Optional[float] = None,
               zmax: Optional[float] = None,
               interior_color: Optional[Any] = (0.0, 0.0, 0.0),
               interior_mask: str = "all", # "all", "not_diverging"
               
               # --- Lighting ---
               shade_kind: Literal["None", "standard", "glossy"] = "None",
               lighting_config: Optional[Dict[str, Any]] = None,
               
               # --- Fieldlines ---
               fieldlines_kind: Literal["None", "overlay", "twin"] = "None",
               fieldlines_func: Optional[Dict[str, Any]] = None,
               
               # --- Output ---
               filename: str = "fractal.png",
               output_path: Optional[str] = None,
               supersampling: str = "2x2",
               batch_prefix: str = "fs_render",
               return_pillow_image: bool = False
               ):
        """
        Render a fractal image with high configurability matching fractalshades gallery capabilities.
        """
        # Force settings inside worker processes so logs stay suppressed
        fs.settings.inspect_calc = False
        fs.settings.verbosity = 0
        
        # 1. Resolve Paths
        if output_path:
            final_path = output_path
        else:
            final_path = os.path.join(self.output_dir, filename)
        
        os.makedirs(os.path.dirname(final_path), exist_ok=True)
        
        model_dir = os.path.join(self.output_dir, f"_{batch_prefix}_tmp")
        if os.path.exists(model_dir):
            shutil.rmtree(model_dir)
        os.makedirs(model_dir, exist_ok=True)

        # 2. Create Model
        f_params = fractal_params or {}
        if flavor: f_params['flavor'] = flavor
        if exponent: f_params['exponent'] = exponent
        
        # Heuristic for perturbation: use if dx is very small or precision is set
        use_perturbation = False
        if precision is not None:
            use_perturbation = True
        elif isinstance(dx, str) and ("e-" in dx.lower()) and float(dx) < 1e-13:
            use_perturbation = True
            if precision is None:
                 # Auto-calculate precision based on dx
                 try:
                     import math
                     val = float(dx)
                     if val > 0:
                         # Add buffer for safety (e.g. 30 digits extra)
                         precision = int(-math.log10(val)) + 30
                     else:
                         precision = 50
                 except:
                     precision = 50
            
        fractal = self._create_model(fractal_type, model_dir, use_perturbation, **f_params)

        # 3. Zoom setup
        # If not using perturbation, ensure coordinates are floats
        if not use_perturbation:
            try:
                x = float(x)
                y = float(y)
                dx = float(dx)
            except (ValueError, TypeError):
                # If conversion fails, leave as is (might be intended for some custom models, though unlikely for standard)
                pass

        zoom_kwargs = {
            "x": x, "y": y, "dx": dx, "nx": nx, 
            "xy_ratio": xy_ratio, "theta_deg": theta_deg,
            "projection": fs.projection.Cartesian() # Default for now, extend if needed
        }
        if precision is not None:
            zoom_kwargs["precision"] = precision
            
        if skew_params:
            zoom_kwargs["has_skew"] = True
            zoom_kwargs.update(skew_params)
            
        fractal.zoom(**zoom_kwargs)

        # 4. Calculation
        c_args = calc_args or {}
        calc_name = "std_calc"
        
        # Merge explicit args with calc_args
        calc_kwargs = {
            "calc_name": calc_name,
            "subset": None,
            "max_iter": max_iter,
            "M_divergence": m_divergence,
            "epsilon_stationnary": epsilon_stationnary,
        }
        # Add optional ones if supported/provided
        if interior_detect:
            calc_kwargs["interior_detect"] = True
            
        # If fieldlines/twinfield are active, we usually need orbit calc
        # But Fieldlines_pp usually runs *after* standard calc using saved data?
        # Actually fs requires calc_orbit=True for fieldlines to work if they depend on orbit
        # But standard Fieldlines_pp in postproc often re-calculates or uses stored. 
        # Checking gallery: ex 2 uses calc_orbit=True, backshift=3.
        if fieldlines_kind != "None":
            calc_kwargs["calc_orbit"] = True
            calc_kwargs["backshift"] = 3
            
        calc_kwargs.update(c_args)
        
        # FIX: Perturbation models often don't support epsilon_stationnary or interior_detect
        # Keep epsilon_stationnary (required), drop interior detection which can fail
        if use_perturbation:
            if "interior_detect" in calc_kwargs:
                del calc_kwargs["interior_detect"]

        # Run Calc
        # Force settings inside worker processes and silence noisy stdout
        fs.settings.inspect_calc = False
        fs.settings.verbosity = 0

        with open(os.devnull, "w") as devnull:
            with contextlib.redirect_stdout(devnull):
                if hasattr(fractal, "calc_std_div"):
                    try:
                        fractal.calc_std_div(**calc_kwargs)
                    except TypeError as e:
                        print(f"Warning: calc_std_div failed with {e}. Retrying with minimal args.")
                        # Retry without unsupported args if necessary (simple fallback)
                        if "interior_detect" in calc_kwargs:
                            del calc_kwargs["interior_detect"]
                        if "epsilon_stationnary" in calc_kwargs:
                            del calc_kwargs["epsilon_stationnary"]
                        fractal.calc_std_div(**calc_kwargs)
                elif hasattr(fractal, "newton_calc"):
                    # Special case for Power Tower / Newton
                    newton_kwargs = {
                        "calc_name": calc_name,
                        "subset": None,
                        "max_newton": 20,
                        "eps_newton_cv": 1e-12,
                        "max_order": 2000, # Default required param
                    }
                    # Merge c_args for things like max_order, compute_order
                    newton_kwargs.update(c_args)
                    fractal.newton_calc(**newton_kwargs)
                else:
                    raise RuntimeError(f"Model {type(fractal)} has no known calculation method (calc_std_div or newton_calc).")

        # 5. Post-processing Setup
        pp = Postproc_batch(fractal, calc_name)
        
        # Add necessary postprocs
        is_power_tower = isinstance(fractal, fsm.Power_tower)

        if base_layer == "continuous_iter":
            if is_power_tower:
                # Power Tower uses 'order' (cycle period) instead of continuous iter
                pp.add_postproc(base_layer, Raw_pp("order", func=None))
            else:
                pp.add_postproc(base_layer, Continuous_iter_pp())

        elif base_layer == "distance_estimation":
            # DEM often needs continuous iter too
            if is_power_tower:
                 # DEM not standard for Power Tower in this context, falling back to order
                 pp.add_postproc(base_layer, Raw_pp("order", func=None))
            else:
                pp.add_postproc("continuous_iter", Continuous_iter_pp())
                pp.add_postproc(base_layer, DEM_pp())

        # Interior mask
        interior_func = lambda x: x != 1 # Default 'all'
        if interior_mask == "not_diverging":
             interior_func = lambda x: x == 0
        pp.add_postproc("interior", Raw_pp("stop_reason", func=interior_func))

        # Fieldlines
        if fieldlines_kind != "None":
            f_func = fieldlines_func or {}
            # Note: endpoint_k seems to be the correct param name in this version
            pp.add_postproc("fieldlines", Fieldlines_pp(
                n_iter=f_func.get("n_iter", 3),
                swirl=f_func.get("swirl", 0.0),
                endpoint_k=f_func.get("endpoint_k", 0.8)
            ))

        # Normals for shading
        if shade_kind != "None":
             pp.add_postproc("DEM_map", DEM_normal_pp(kind="potential"))

        # 6. Plotter Layers
        plotter = fs.Fractal_plotter(pp, final_render=True, supersampling=supersampling)
        
        # A. Interior Layer (Mask)
        plotter.add_layer(Bool_layer("interior", output=False))
        
        # B. Fieldlines Layer (Virtual or Grey)
        if fieldlines_kind == "twin":
            plotter.add_layer(Virtual_layer("fieldlines", func=None, output=False))
        elif fieldlines_kind == "overlay":
            plotter.add_layer(Grey_layer("fieldlines", func=None, output=False))

        # C. Normals Layer
        if shade_kind != "None":
            plotter.add_layer(Normal_map_layer("DEM_map", max_slope=45, output=False)) # Slope could be param

        # D. Base Color Layer
        # Resolve Colormap
        cmap_obj = colormap
        if isinstance(colormap, str):
            cmap_obj = fscolors.cmap_register.get(colormap, fscolors.cmap_register["classic"])
        
        # Color Function
        sign = -1.0 if invert_colormap else 1.0
        
        if base_layer == "distance_estimation":
            # Typical DEM log-log
            dem_min = 1e-6 # could make configurable
            def dem_cmap_func(x):
                return sign * np.where(np.isinf(x), np.log(dem_min), np.log(np.clip(x, dem_min, None)))
            func = dem_cmap_func
        else:
            # Continuous Iter
            func = lambda x: sign * np.log(np.maximum(x, 1e-10))

        # Probes
        probes = [zmin, zmax] if (zmin is not None and zmax is not None) else None
        if probes is None:
            # Fallback defaults if not provided
            if base_layer == "distance_estimation":
                 probes = [0.0, 1.0] 
            else:
                 # For continuous iter, usually a small range is okay for repeating maps
                 probes = [0.0, 1.0]

        plotter.add_layer(Color_layer(
            base_layer,
            func=func,
            colormap=cmap_obj,
            probes_z=probes,
            output=True
        ))

        # Apply Mask
        plotter[base_layer].set_mask(plotter["interior"], mask_color=interior_color)

        # Apply Twin Field
        if fieldlines_kind == "twin":
            twin_intensity = (fieldlines_func or {}).get("twin_intensity", 0.1)
            plotter[base_layer].set_twin_field(plotter["fieldlines"], twin_intensity)
        elif fieldlines_kind == "overlay":
            overlay_mode = Overlay_mode("tint_or_shade", pegtop=1.0)
            plotter[base_layer].overlay(plotter["fieldlines"], overlay_mode)

        # Apply Shading
        if shade_kind != "None":
            l_conf = lighting_config or {}
            light = Blinn_lighting(0.4, np.array([1., 1., 1.]))
            
            # Primary Light
            light.add_light_source(
                k_diffuse=l_conf.get("k_diffuse", 0.8),
                k_specular=l_conf.get("k_specular", 0.0),
                shininess=l_conf.get("shininess", 350.0),
                polar_angle=l_conf.get("polar_angle", 45.0),
                azimuth_angle=l_conf.get("azimuth_angle", 10.0),
                color=np.array(l_conf.get("color", [1.0, 1.0, 1.0]))
            )
            
            # Glossy Light
            if shade_kind == "glossy":
                light.add_light_source(
                    k_diffuse=0.2,
                    k_specular=l_conf.get("gloss_intensity", 10.0),
                    shininess=400.0,
                    polar_angle=l_conf.get("polar_angle", 45.0),
                    azimuth_angle=l_conf.get("azimuth_angle", 10.0),
                    color=np.array(l_conf.get("gloss_light_color", [1.0, 1.0, 1.0]))
                )
                
            plotter[base_layer].shade(plotter["DEM_map"], light)

        # 7. Plot and Save
        plotter.plot()
        
        # Move file
        # The plotter saves as `Color_layer_{base_layer}.png` usually
        generated_name = f"Color_layer_{base_layer}.png"
        src = os.path.join(model_dir, generated_name)
        if not os.path.exists(src):
            # Fallback search
            files = os.listdir(model_dir)
            pngs = [f for f in files if f.endswith(".png")]
            if pngs:
                src = os.path.join(model_dir, pngs[0])
            else:
                raise RuntimeError(f"No image generated in {model_dir}")

        if os.path.exists(final_path):
            os.remove(final_path)
        shutil.move(src, final_path)
        
        # Cleanup
        shutil.rmtree(model_dir)
        
        if return_pillow_image:
             from PIL import Image
             return final_path, Image.open(final_path)
        
        return final_path
