# Ultra-Resolution Quads – PRD

## 1. Product Summary
- Single-view, ultra-resolution image explorer in the browser.
- Image space is an infinite quadtree (view → 4 → 4 → …) backed by precomputed tiles.
- Uses sparse quadtree tiles so only data near the camera path is rendered.
- Supports a continuous camera path that can zoom extremely far into an image.
- Frontend: one big view with mouse pan + scroll zoom, plus explicit camera controls.

The PRD is written to be directly actionable for coding agents: all data flows are file/URI based, with minimal hidden behavior.

## 2. Goals
- Interactive exploration of extremely large / detailed images.
- Long, smooth zoom paths without loading the full dataset at once.
- Simple backend: Python scripts that generate and manage datasets on disk (no HTTP API required).
- Simple dataset management via files: create, list, select, rename, delete datasets by editing JSON / running scripts.
- Easy experimentation with mathematical images (e.g. polar-Newton, Mandelbrot) and practical sources.
- Pluggable renderers (Python scripts in a `renderers/` folder).
- Primary browser target: Chrome on desktop.

## 3. High-Level Architecture

### 3.1 Data Layout & Access Pattern
- All data for the viewer is exposed as static files (JSON + images) under a **base data URI**.
- The frontend receives a single config value at build-time or startup:
  - `BASE_DATA_URI` – e.g. `/data/` or `https://example.com/ultra-quads/`.
- On disk, all datasets live under a `datasets/` directory at the project root; the static server maps that directory so it is reachable as `BASE_DATA_URI + "datasets/"`.
- Under `BASE_DATA_URI`, the following file layout is expected:
  - `datasets/index.json` – list of datasets and their metadata.
  - `datasets/{dataset_id}/config.json` – minimal dataset configuration needed by the viewer (e.g. zoom levels).
  - `datasets/{dataset_id}/tiles/{level}/{x}/{y}.png` – tile images.
  - `datasets/{dataset_id}/paths.json` – camera paths for that dataset.
  - `datasets/{dataset_id}/tiles_meta.json` (optional) – metadata per tile if needed.
- The frontend **only** reads these JSON and image files via HTTP GET; it does not call any JSON-over-HTTP API endpoints.

### 3.2 Frontend Viewer
- Single-page app using DOM nodes (one `div` or `img` per tile).
- Renders a fixed viewport; camera movement is implemented by translating and swapping tiles.
- Two main modes:
  - **Exploration mode** – user/agent can pan and zoom freely.
  - **Experience mode** – camera follows a predefined keyframe path.

### 3.3 Backend Tooling (Python)
- Backend is a collection of Python scripts in `backend/` that operate directly on the filesystem layout above.
- Responsibilities:
  - Create new datasets (`datasets/{dataset_id}/` directories and `config.json`).
  - Manage dataset metadata (update `datasets/index.json`).
  - Generate tiles into `datasets/{dataset_id}/tiles/...`.
  - Generate / edit camera paths saved into `paths.json`.
  - Optionally perform precomputation along a camera path.
- No dedicated HTTP API service is required for v1; a simple static file server (e.g. `python -m http.server`) can host the data and frontend.

## 4. Coordinate System & Camera Model

### 4.1 Layer-Stack Architecture
To support unlimited zoom depth without floating-point precision loss:
- **Fixed viewport**: Camera stays conceptually centered; tiles move around it.
- **Integer tile indexing**: Tiles use `(level, x, y)` coordinates—exact, no floating-point error.
- **Per-layer offsets**: A float offset in `[0, 1)` tracks fractional position within the current tile.
- **Why this works**: Integer indices remain exact; offsets stay high-precision. There is no precision wall at level ~53.

Result: Zoom depth is limited only by tile generation, not by IEEE 754 floating-point.

### 4.2 Camera State Representation
- Camera state used by the frontend and stored in JSON:
  - `level` – current zoom level (integer).
  - `tileX`, `tileY` – integer tile indices at that level.
  - `offsetX`, `offsetY` – floats in `[0, 1)` for intra-tile position.
  - `rotation` (optional) – rotation angle in radians or degrees.
- Internal layer stack representation in the viewer:
  - Array of layers: `{ level, tileX, tileY, offsetX, offsetY }` per zoom level.

## 5. Tiles & Rendering

### 5.1 Frontend Rendering Logic
- The frontend renders tiles as positioned DOM elements (e.g. absolutely positioned `div` or `img`).
- Pan updates the camera offsets; when `offsetX` or `offsetY` are outside `[0, 1)`, the corresponding tile index increments/decrements (wrapping logic).
- Zoom interpolates between adjacent layers with a crossfade:
  - As we zoom into a child quadrant, fade out the parent tile and fade in the four child tiles.
- Rendering loop uses `requestAnimationFrame` for smooth updates.

### 5.2 Tile Indexing
- Tiles are addressed only by `(level, x, y)` and mapped to paths:
  - `datasets/{dataset_id}/tiles/{level}/{x}/{y}.png`.

## 6. Dataset & Metadata Format

### 6.1 `datasets/index.json`
Top-level list of datasets:
```json
{
  "datasets": [
    {
      "id": "mandelbrot_deep",
      "name": "Mandelbrot Deep Zoom",
      "description": "Deep zoom into the Mandelbrot set"
    },
    {
      "id": "debug_quadtile",
      "name": "Debug Quadtile",
      "description": "Synthetic dataset that displays tile coordinates"
    }
  ]
}
```

### 6.2 `datasets/{dataset_id}/config.json`
Dataset configuration:
```json
{
  "id": "mandelbrot_deep",
  "name": "Mandelbrot Deep Zoom",
  "min_level": 0,
  "max_level": 20
}
```

### 6.3 `datasets/{dataset_id}/paths.json`
Camera paths keyed by id:
```json
{
  "paths": [
    {
      "id": "default_path",
      "name": "Default Path",
      "keyframes": [
        {
          "camera": { "level": 0, "tileX": 0, "tileY": 0, "offsetX": 0.5, "offsetY": 0.5, "rotation": 0.0 }
        }
      ]
    }
  ]
}
```

### 6.4 Optional `tiles_meta.json`
- Optional per-dataset metadata file for tiles (may be added later).

## 7. Frontend Behavior

### 7.1 Shared Rendering Engine
- Both frontend modes use the same core engine:
  - Maintains camera state (`level`, `tileX`, `tileY`, `offsetX`, `offsetY`, `rotation`).
  - Computes which tiles are visible for the current camera and viewport.
  - Loads tiles on demand as images from the filesystem layout.
  - Keeps a small margin of tiles beyond the viewport and evicts far-away tiles to limit memory usage.
  - Renders tiles each frame via `requestAnimationFrame`.
- In v1, tiles are loaded strictly on demand. Complexity regarding preloading or predictive fetching is explicitly out of scope. Visible tile pop-in during rapid movement is acceptable for this version.

### 7.2 Exploration Mode
- Input:
  - Mouse drag to pan (updates offsets and tile indices).
  - Scroll wheel to zoom in/out (updates active layer and crossfade).
- Camera UI:
  - Explicit panel showing current camera state:
    - Numeric inputs/sliders for `level`, `tileX`, `tileY`, `offsetX`, `offsetY`, and `rotation`.
    - Buttons for small incremental moves (e.g. pan up/down/left/right, zoom in/out).
  - Changing these values updates the camera state and lets both humans and AI agents control the viewpoint and capture screenshots.

### 7.3 Path Playback Mode
- Camera follows a keyframe-based path defined in the dataset’s `paths.json`.
- Keyframes are ordered in the `keyframes` array; playback progresses through them in sequence using a normalized time parameter between successive keyframes.
- Linear interpolation of position (`tileX`, `tileY`, `offsetX`, `offsetY`), `level`, and `rotation` between successive keyframes initially.
- UI:
  - Dataset selector.
  - Play/pause controls and time scrubber for the active dataset’s default path.
- Keyframes and paths are authored offline (via scripts or manual JSON editing), not created or edited in the frontend.

## 8. Tile Generation Pipeline & Renderers

### 8.1 Tile Generation Pipeline (Backend Scripts)
- **Renderer Interface:**
  - Renderers are Python classes that implement a simple interface: `render(level, x, y) -> Image`.
  - Input: `level`, `x`, `y` coordinates.
  - Output: A bitmap image ready to be saved.

- **Path-Based Generation Algorithm (Discrete Viewport Sampling):**
  - Instead of generating the full infinite tree, we generate tiles along a specific camera path.
  - **Algorithm:**
    1. Discretize the camera path into fine time steps.
    2. For each step, calculate the camera's viewport bounding box at the current zoom level.
    3. Identify all integer tile coordinates `(level, x, y)` that intersect this bounding box.
    4. Collect the union of all such tiles to generate.

- **Process:**
  - Load dataset configuration.
  - Instantiate the specified renderer class.
  - Run the sampling algorithm to get a list of required tiles.
  - For each required tile:
    - Call `renderer.render(level, x, y)`.
    - Save to `datasets/{dataset_id}/tiles/{level}/{x}/{y}.png` at project root.

### 8.2 Built-in Renderers (v1)
- `debug_quadtile_renderer`:
  - Renders a flat background and writes the tile ID (e.g. `L5_x12_y7`) in large text at the center.
  - Used to validate tiling, crossfades, and camera movement.
- `mandelbrot_deepzoom_renderer`:
  - Renders a Mandelbrot fractal slice for each tile based on the mapped complex-plane bounds.
  - Tuned for visually interesting deep zoom paths.

## 9. Constraints & Open Questions
- Target max resolution / zoom depth:
  - No hard limit; design for “as far as we can push it” using sparse tiling and on-demand generation.
- Frontend stack:
  - Vanilla JavaScript + DOM-based tile rendering (no canvas).
  - Minimal dependencies to keep it easy for coding agents to manipulate.
- Storage:
  - Local filesystem for all tiles and JSON in v1.
  - Deployed via static hosting or a simple static HTTP server.
- Performance:
  - Real-time feel; use `requestAnimationFrame` for rendering and camera updates.
  - Avoid layout thrashing by batching DOM updates per frame.
- Open questions:

## 10. Development & Artifacts

### 10.1 Artifacts Folder (`artifacts/`)
- A local-only folder for storing temporary development files.
- **Git Ignored:** This folder is excluded from version control.
- **Contents:**
  - Screenshots taken during testing.
  - Temporary log files (e.g., server logs).
  - Temporary test scripts or throwaway code.
- **Maintenance:** Developers should manually clean this folder periodically. It serves as a scratchpad to keep the project root clean.

## 11. Testing Strategy

### 11.1 Tests Folder (`tests/`)
- Contains automated test scripts to verify core logic without needing a full browser environment.
- **Key Tests:**
  - `tests/test_frontend.js`: Uses a Node.js sandbox to mock the DOM and execute `frontend/main.js`. It verifies:
    - **Zoom Logic:** Correct level increments/decrements and offset wrapping.
    - **Rendering:** Correct identification of visible tiles for parent/child layers.
    - **Crossfading:** Correct opacity calculations (Parent stable at 1.0, Child fades in).
    - **Performance:** Verification that DOM elements are reused (reconciled) rather than recreated every frame.

### 11.2 Running Tests
Run the frontend logic test suite via Node.js:
```bash
node tests/test_frontend.js
```