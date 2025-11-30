# Fractalshades AI Agent Reference Guide

## Overview

[Fractalshades](https://gbillotey.github.io/Fractalshades-doc/) is a Python package for creating static and interactive visualizations of 2D fractals. It supports deep exploration of Mandelbrot and Burning Ship sets (zoom scales of 1.e-2000 and beyond) using arbitrary-precision mathematics.

This guide covers usage within the **Ultra-Resolution Quads** project.

***

## 🚀 Recommended: Using `FractalShadesRenderer`

For most tasks in this project, **do not use `fractalshades` directly**. Instead, use the wrapper class `FractalShadesRenderer` in `backend/fractal_renderer.py`. It abstracts away the boilerplate for model setup, cleaning, post-processing, and file handling.

### Basic Usage

```python
from backend.fractal_renderer import FractalShadesRenderer

# Initialize with an output directory
renderer = FractalShadesRenderer("artifacts/my_renders")

# Render a standard Mandelbrot image
path = renderer.render(
    center_x=-0.743643887037151,
    center_y=0.13182590420533,
    width=0.002,
    max_iter=2000,
    filename="basic_fractal.png",
    colormap="citrus"
)
```

### Selecting Fractal Models

Use the `model` parameter to switch between supported fractal types:

- `"mandelbrot"` (default)
- `"burning_ship"`
- `"mandelbrot_n"` (Requires `mandelbrot_n_exponent`)
- `"power_tower"`

```python
# Render Burning Ship
renderer.render(
    model="burning_ship",
    center_x=-1.75, 
    center_y=-0.03, 
    width=0.05, 
    filename="ship.png"
)

# Render Mandelbrot^3
renderer.render(
    model="mandelbrot_n",
    mandelbrot_n_exponent=3,
    center_x=0, center_y=0, width=2.0,
    filename="multibrot.png"
)
```

### Deep Zooming (Perturbation Theory)

For zooms deeper than `1e-13` (beyond standard float64 precision), you **must** enable perturbation theory.

- Set `use_perturbation=True`
- Pass coordinates as **strings** to preserve precision
- Set `dps` (decimal precision) to an appropriate integer (e.g., 50, 100, 1000)

```python
renderer.render(
    use_perturbation=True,    # Enable deep zoom engine
    dps=60,                   # Precision in decimal digits
    center_x="-1.74999900000000000000000000000001", 
    center_y="-0.0000073095",
    width="1.0e-30",
    model="burning_ship",     # Works for "mandelbrot" and "burning_ship"
    filename="deep_zoom.png"
)
```

### Visualization Styles

The renderer supports high-level visualization presets via the `visualization` parameter:

1.  **`"continuous_iter"`** (Default): Standard smooth escape-time coloring.
2.  **`"fieldlines"`**: Adds flowing field lines to the rendering.
3.  **`"dem"`**: Distance Estimation Method (pseudo-3D relief).

You can also enable 3D lighting effects with `add_lighting=True` (works best with DEM).

```python
# Fieldlines
renderer.render(
    visualization="fieldlines",
    colormap="ocean",
    filename="fieldlines.png"
)

# 3D Lighting with DEM
renderer.render(
    visualization="dem",
    add_lighting=True,
    filename="3d_dem.png"
)
```

### Advanced Features

#### Burning Ship Skew
Deep Burning Ship zooms often require "un-skewing" to prevent the image from looking stretched.

```python
renderer.render(
    model="burning_ship",
    skew_matrix=(1.0, 0.0, 0.0, 1.0), # (skew_00, skew_01, skew_10, skew_11)
    # ...
)
```

#### Projections
Support for alternative mappings of the complex plane.

```python
renderer.render(
    projection_type="expmap", # or "moebius", "cartesian"
    # projection_params={"...": ...} 
    # ...
)
```

***

## Underlying Library Concepts (Reference)

The following sections describe the raw `fractalshades` API. Use this only if you need to modify the `FractalShadesRenderer` internals or create a custom renderer that the wrapper doesn't support.

### Core Architecture

1. **Calculation Components** (`fractalshades.Fractal` subclasses) - Run calculations.
2. **Plotting Components** (`fractalshades.Fractal_plotter`) - Apply post-processing.

### Raw Model Instantiation

#### Standard Precision
```python
from fractalshades.models import Mandelbrot, Burning_ship, Mandelbrot_N

# Mandelbrot
m = Mandelbrot(directory="out")
m.zoom(x=-0.7, y=0.0, dx=3.0, nx=800, xy_ratio=1.0, theta_deg=0.0)

# Burning Ship
b = Burning_ship(directory="out")
b.zoom(x=-1.75, y=-0.03, dx=0.05, nx=800, xy_ratio=1.0)
```

#### Arbitrary Precision (Perturbation)
```python
from fractalshades.models import Perturbation_mandelbrot

pm = Perturbation_mandelbrot(directory="out")
pm.zoom(
    x="-0.7436...", y="0.1318...", dx="1.e-15", 
    nx=1200, xy_ratio=1.0, dps=50, max_iter=100000
)
```

### Post-Processing Layers

Fractalshades uses "layers" to build the final image.

```python
import fractalshades as fs
from fractalshades import postproc as pp

plotter = fs.Fractal_plotter(fractal=m, calc_name="div_layer")

# Add a color layer
plotter.add_layer(
    bool_layer=False,
    output_fn=lambda x: x.continuous_iter,
    colormap=fs.colors.Fractal_colormap.get("citrus"),
    probes_z=[fs.numpy_utils.expr_parser.Numpy_expr("z", "continuous_iter")]
)
plotter.plot()
```

### Working with Color Palettes

#### Creating Custom Colormaps
```python
from fractalshades.colors import Fractal_colormap

colors = [
    [0.0, 0.0, 0.5],    # Dark blue
    [0.0, 0.5, 1.0],    # Light blue
    [1.0, 1.0, 0.0]     # Yellow
]

colormap = Fractal_colormap(
    colors=colors,
    kinds=['Lch', 'Lch'],
    grad_npts=[32, 32],
    extent='mirror'
)
```

### Resources
- [Fractalshades Documentation](https://gbillotey.github.io/Fractalshades-doc/)
- [Fractalshades Examples](https://gbillotey.github.io/Fractalshades-doc/examples/index.html)
