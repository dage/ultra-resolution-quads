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

### 2. Generate a Dataset

The viewer relies on pre-generated tiles. You must run the backend generator before launching the viewer.

**Generate a Debug Grid (fastest to test):**
```bash
python backend/generate_dataset.py --dataset debug_quadtile --renderer debug --max_level 6
```

**Generate a Mandelbrot Zoom (Path-Based Generation):**
This uses a "path-based" generation mode to only create tiles needed for a specific deep-zoom path (e.g., Seahorse Valley), saving massive amounts of disk space compared to a full pyramid.

```bash
python backend/generate_dataset.py --dataset mandelbrot_deep --renderer mandelbrot --max_level 20 --mode path
```

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

## Project Structure

- **`backend/`**: Contains `generate_dataset.py` and storage management logic.
- **`datasets/`**: Generated tiles and config files live here.
- **`frontend/`**: The web viewer.
  - `main.js`: Core engine logic (state, camera, rendering loop).
- **`renderers/`**: Python modules that define how tiles are drawn.
- **`tests/`**: Automated test scripts.
- **`artifacts/`**: Temporary folder for logs, screenshots, and scratch files (git-ignored).
- **`PRD.md`**: Project Requirements Document explaining the core architecture.

## Architecture Note

Standard map viewers use floating-point coordinates which break down (jitter) after zooming in by a factor of ~10^15. This project uses a **Layer-Stack Camera Model**:

- **Level (int)**: The discrete zoom step.
- **Tile Index (int, int)**: The exact grid coordinate at that level.
- **Offset (float, float)**: The fractional position [0, 1) inside a specific tile.

This guarantees pixel-perfect precision regardless of how deep you zoom.