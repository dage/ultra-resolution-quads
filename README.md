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

### Backend Dependencies

Install packages:

```bash
pip install -r requirements.txt
```

### 2. Generate Datasets

The viewer relies on pre-generated tiles. You must run the setup script to generate the required datasets if you plan to use the examples. This script creates both a debug grid and a deep-zoom Mandelbrot set.

```bash
python setup_datasets.py
```

Note: Generated tiles in `datasets/` are git-ignored to keep the repository light. The `paths.json` and `config.json` files are tracked to ensure reproducible experiences.

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

The project includes a test suite for the frontend logic (simulating a browser environment using Node.js).

```bash
node tests/test_frontend.js
```

## Analysis Tools

### Camera Path Analysis
You can analyze the continuity and speed of a camera path using the plotting script. This generates a 9-panel chart showing position, velocity, and acceleration.

```bash
python scripts/plot_camera_path.py datasets/mandelbrot_deep/paths.json --output artifacts/analysis.png
```

## Path Macros

Camera keyframes in `datasets/*/paths.json` can use small macros that are expanded by `shared/camera_path.js` (shared by frontend and backend). The canonical camera shape is `{ globalLevel, x, y }` where `x/y` are normalized doubles in `[0,1)` and `globalLevel` is a single double (integer + fractional crossfade).

- `macro: "global"` (or just provide `x/y` directly): supply `level`, `globalX`, and `globalY` (normalized doubles) to set camera position.
- `macro: "mandelbrot"` (aliases: `mandelbrot_point`, `mb`): supply `level`, `re`, and `im` for a point in the Mandelbrot set. Uses the renderer bounds centered at `-0.75 + 0i` with a width/height of `3.0`.

Example:

```json
{
  "paths": [
    {
      "id": "macro_demo",
      "keyframes": [
        { "camera": { "macro": "global", "level": 10, "globalX": 0.375, "globalY": 0.52 } },
        { "camera": { "macro": "mandelbrot", "level": 14, "re": -0.743643887, "im": 0.131825904 } }
      ]
    }
  ]
}
```

## Project Structure

- **`backend/`**: Contains `generate_dataset.py` and storage management logic.
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
