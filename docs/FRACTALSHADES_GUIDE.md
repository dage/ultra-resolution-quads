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
    fractal_type="mandelbrot",
    x="-0.743643887037151",
    y="0.13182590420533",
    dx="0.002",
    nx=800,
    max_iter=2000,
    filename="basic_fractal.png",
    colormap="citrus"
)
```

### Selecting Fractal Models

Use the `fractal_type` parameter to switch between supported fractal types. Some models support specific `flavor` variants.

- **Mandelbrot**: `fractal_type="mandelbrot"`
- **Burning Ship**: `fractal_type="burning_ship"`
    - **Shark Fin**: `fractal_type="shark_fin"` (or `flavor="Shark fin"`)
    - **Perpendicular**: `fractal_type="perpendicular_burning_ship"` (or `flavor="Perpendicular burning ship"`)
- **Power Tower**: `fractal_type="power_tower"`
- **Mandelbrot N**: `fractal_type="mandelbrot_n"` (requires `exponent`)

```python
# Render Shark Fin
renderer.render(
    fractal_type="shark_fin",
    x="-0.5", y="-0.65", dx="0.5", 
    filename="shark.png"
)

# Render Mandelbrot^3
renderer.render(
    fractal_type="mandelbrot_n",
    exponent=3,
    x="0", y="0", dx="2.0",
    filename="multibrot.png"
)
```

### Deep Zooming (Perturbation Theory)

For zooms deeper than `1e-13` (beyond standard float64 precision), perturbation theory is automatically enabled if you provide `precision` (dps) or very small `dx`.

- **Always** pass coordinates as **strings** to preserve precision.
- Set `precision` (decimal digits) explicitly for control.

```python
renderer.render(
    fractal_type="mandelbrot",
    x="-1.74999900000000000000000000000001", 
    y="-0.0000073095",
    dx="1.0e-30",
    precision=60,
    filename="deep_zoom.png"
)
```

### Visualization Styles

The renderer supports a flexible layering system controlled by `base_layer` and additional config objects.

#### 1. Distance Estimation (DEM)
Renders the fractal with distance estimation (smooth gradients based on distance to the set) instead of simple iteration counting.

```python
renderer.render(
    base_layer="distance_estimation",
    colormap="hot",
    filename="dem.png"
)
```

#### 2. Fieldlines
Adds flowing lines that visualize the potential field.

- **Overlay**: Grey lines drawn on top of the color.
- **Twin**: Lines that mathematically mix with the underlying color.

```python
renderer.render(
    fieldlines_kind="twin",  # or "overlay"
    fieldlines_func={"n_iter": 4, "swirl": 0.0, "twin_intensity": 0.5},
    colormap="ocean",
    filename="fieldlines.png"
)
```

#### 3. 3D Lighting (Shading)
Adds simulated 3D lighting to the image, often used with DEM or glossy effects.

```python
renderer.render(
    shade_kind="glossy",  # or "standard"
    lighting_config={
        "k_diffuse": 0.4, 
        "k_specular": 30.0, 
        "shininess": 400.0,
        "polar_angle": 135.0, 
        "gloss_light_color": [1.0, 0.9, 0.9]
    },
    filename="glossy.png"
)
```

### Advanced Features

#### Burning Ship Skew
Deep Burning Ship zooms often require "un-skewing".

```python
renderer.render(
    fractal_type="burning_ship",
    skew_params={
        "skew_00": 1.0, "skew_01": 0.0, 
        "skew_10": 0.0, "skew_11": 1.0
    },
    # ...
)
```

***

## Underlying Library Concepts (Reference)

Use the raw `fractalshades` API only if you need to modify `backend/fractal_renderer.py`.

### Core Architecture
1. **Calculation Components**: `fractalshades.Fractal` subclasses (run calculations).
2. **Post-Processing**: `fractalshades.postproc` (DEM, Fieldlines, Continuous Iteration).
3. **Plotting**: `fractalshades.Fractal_plotter` (Layers, Masks, Shading).

### Resources
- [Fractalshades Documentation](https://gbillotey.github.io/Fractalshades-doc/)
- [Fractalshades Examples](https://gbillotey.github.io/Fractalshades-doc/examples/index.html)