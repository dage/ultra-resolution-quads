# Ultra-Resolution Quads

A single-view, ultra-resolution image explorer in the browser. This project demonstrates an "infinite" zoom capability using a sparse quadtree structure, allowing users to explore procedural images (like fractals) or massive datasets far beyond standard floating-point precision limits.

## Features

- **Infinite Zoom Architecture**: Uses a custom integer-based layer stack to avoid floating-point precision errors at deep zoom levels.
- **Sparse Quadtrees**: Efficiently manages storage by only generating and serving tiles relevant to the specific camera path or area of interest.
- **Smooth Navigation**: 60fps rendering with smooth cross-fading between zoom levels.
- **Path Playback**: "Experience Mode" allows the camera to follow pre-defined keyframe paths.
- **Extensible Renderers**: Python-based backend makes it easy to plug in new image generators (e.g., Mandelbrot, noise functions).
- **No Build Step**: Frontend is pure Vanilla JS/CSS/HTML.

## Quick Start

### 1. Prerequisites

You will need Python 3 and the Pillow library for image generation.

```bash
pip install Pillow
```

For rendering deep fractal zooms, install fractalshades.

**macOS example:**
```bash
brew install gmp mpfr libmpc
CFLAGS="-I/opt/homebrew/include" LDFLAGS="-L/opt/homebrew/lib" pip install gmpy2 fractalshades
```

### Backend Dependencies

Install packages:

```bash
pip install -r requirements.txt
```

### 2. Render Tiles

The viewer relies on pre-generated tiles. `backend/render_tiles.py` reads `datasets/{id}/config.json` to pick the renderer and tile size; it only writes tile PNGs (no configs).

Render all datasets that exist in `datasets/`:
```bash
python backend/render_tiles.py
```

Or render a single dataset:
```bash
python backend/render_tiles.py --dataset debug_quadtile
python backend/render_tiles.py --dataset mandelbrot_single_precision
python backend/render_tiles.py --dataset mandelbrot_single_precision --rebuild  # wipe tiles first
```

Note: Generated tiles in `datasets/` are git-ignored to keep the repository light. The `paths.json` and `config.json` files are tracked to ensure reproducible experiences. Tiles are stored under `datasets/<id>/<level>/<x>/<y>.png`. The renderer automatically detects existing tile sizes and triggers a clean rebuild if the requested `tile_size` differs from what is on disk. Use `--rebuild` to manually wipe existing tiles for a dataset. The old `backend/generate_dataset.py` and `setup_datasets.py` helpers are retired; use `render_tiles.py` directly.
Each dataset can optionally provide a single camera path in `paths.json` under the `path` key.

### 3. Run the Server

Start a simple static HTTP server in the project root:

```bash
python -m http.server 8000
```

### 4. Explore

Open **[http://localhost:8000/frontend/index.html](http://localhost:8000/frontend/index.html)** in your web browser.

## Controls

- **Pan**: Left-click and drag.
- **Zoom**: Scroll wheel (Mouse wheel).
- **Manual Control**: Use the side panel to type in exact coordinates or adjust sliders.
- **Modes**: Switch between "Explore" (free cam) and "Path Playback" (cinematic) in the UI.

## Testing

You can run all automated checks with a single helper script:

```bash
tests/run_all_tests.sh
```

```bash
node tests/test_frontend.js
```

## Analysis Tools

### Camera Path Analysis
You can analyze the continuity and speed of a camera path using the plotting script. This generates a 9-panel chart showing position, velocity, and acceleration.

```bash
python scripts/plot_camera_path.py datasets/mandelbrot_single_precision/paths.json --output artifacts/analysis.png
```

### Fractal Rendering Helper

A generic wrapper class, `FractalShadesRenderer`, is available in `backend/fractal_renderer.py` to simplify rendering high-resolution Mandelbrot images using `fractalshades`. It supports high-precision coordinates (via strings), custom colormaps, and optional 3D lighting.

Usage example:
```python
from backend.fractal_renderer import FractalShadesRenderer

renderer = FractalShadesRenderer("output_folder")
path = renderer.render(
    center_x="-0.743643887037151", # Strings recommended for high precision
    center_y="0.13182590420533",
    width=0.002,
    img_size=512,
    max_iter=2000,
    filename="fractal.png",
    colormap="citrus",
    add_lighting=True
)
```

## Path Macros

Camera keyframes in the single `path` inside `datasets/*/paths.json` can use small macros that are expanded by `shared/camera_path.js` (shared by frontend and backend). The canonical camera shape is `{ globalLevel, x, y }` where `x/y` are normalized doubles in `[0,1)` and `globalLevel` is a single double (integer + fractional crossfade).

- `macro: "global"` (or just provide `x/y` directly): supply `level`, `globalX`, and `globalY` (normalized doubles) to set camera position.
- `macro: "mandelbrot"` (aliases: `mandelbrot_point`, `mb`): supply `level`, `re`, and `im` for a point in the Mandelbrot set. Uses the renderer bounds centered at `-0.75 + 0i` with a width/height of `3.0`.

Example:

```json
{
  "path": {
    "id": "macro_demo",
    "keyframes": [
      { "camera": { "macro": "global", "level": 10, "globalX": 0.375, "globalY": 0.52 } },
      { "camera": { "macro": "mandelbrot", "level": 14, "re": -0.743643887, "im": 0.131825904 } }
    ]
  }
}
```

## Project Structure

- **`backend/`**: Contains `render_tiles.py` and storage management logic.
- **`datasets/`**: Generated tiles and config files live here.
- **`frontend/`**: The web viewer.
  - `main.js`: Core engine logic (state, camera, rendering loop).
- **`renderers/`**: Python modules that define how tiles are drawn.
- **`tests/`**: Automated test scripts.
- **`artifacts/`**: Temporary folder for logs, screenshots, and scratch files (git-ignored).
- **`scripts/`**: Utility scripts for analysis and maintenance.
- **`PRD.md`**: Project Requirements Document explaining the core architecture.

## Architecture Note

Standard map viewers use floating-point coordinates which break down (jitter) after zooming in by a factor of ~10^15. This project uses a **Layer-Stack Camera Model** with a single normalized coordinate pair and a single zoom scalar:

- **Global Level (double)**: Zoom as a single number; integer part selects the base level, fractional part drives crossfade.
- **Position (x, y)**: Doubles in `[0,1)` at level 0; tile indices are derived internally when selecting imagery.

This keeps the API simple (no split tile/offset pairs) while still allowing deep zoom with predictable tile selection.