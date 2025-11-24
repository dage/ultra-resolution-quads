# Ultra-Resolution Quads – PRD

## 1. Product Summary
- Single-view, ultra-resolution image explorer.
- Image space is an infinite quadtree (view -> 4 -> 4 -> …).
- Uses sparse quadtree tiles so only data near the camera path is rendered.
- Supports a “swimming” camera path that zooms extremely far into an image.
 - Frontend: one big view with mouse pan + scroll zoom.

## 2. Goals
- Interactive exploration of extremely large / detailed images.
- Long, smooth zoom paths without loading the full dataset.
- Backend that generates and serves just-in-time tiles for ultra-res datasets.
- Simple dataset management: list, create, select, rename, delete ultra-res sets.
- Easy experimentation with mathematical images (e.g. polar-Newton) and more practical sources.
- Pluggable renderers (scripts in a `renderers/` folder).
- Primary browser target: Chrome on desktop.

## 6. System Overview

### 6.1 Frontend (viewer)
- Single full-window view (canvas or similar).
- Two modes:
  - Exploration mode: mouse drag to pan; scroll wheel to zoom in/out.
  - Experience mode: camera follows the keyframe path; user passively watches or uses a scrubber to navigate time (no direct pan/zoom).
- Both modes share the same rendering/code path: crossfading between levels, moving quadtile tiles, and dynamically loading tiles.
- Exploration mode: load tiles on demand as the user moves (no deep preloading).
- Experience mode: preload tiles in the background along the path (up to ~5 levels ahead) so everything is cached before the camera arrives.
- Seamless zooming via crossfade: as we zoom into a child quadrant, fade out the parent tile and fade in the four child tiles.
- Minimal UI to:
  - Pick a dataset.
  - Edit a simple keyframe-based camera path (linear interpolation for position, zoom, and rotation to start; splines later).
  - Play / pause the camera path.

### 6.2 Backend (Python + Gemini)
- Python service that manages datasets, camera paths, tile metadata, and renderers.
- Dataset CRUD: list all datasets, create new, rename, delete, select one for editing.
- Serves tiles given `dataset_id + tile_id`; can precompute tiles along a path.
- Uses Gemini API to help with dataset parameters and interesting camera paths.
- Configuration via `.env` and `.env_template` (Gemini key, storage, etc.).

### 6.3 Tile Generation Pipeline
- Input: base renderer (e.g. polar-Newton / fractal) + dataset config (bounds, levels, params).
- Process:
  - Sparse quadtree tiling; generate tiles only for current camera viewport and a small predictive window along the camera path.
  - Algorithm to decide which tiles to render: all tiles whose screen-space projection intersects the viewport (plus margin) over a short time horizon.
- Indexing: Quadtile Hierarchical String Indexing (OpenStreetMap-style):
  - `"0"` = full image; children are `"00"`, `"01"`, `"10"`, `"11"`; deeper tiles extend the string (e.g. `"0132"`).
- Output: tiles at `/{dataset_id}/{tile_id}.png`, with metadata like:
  - `tiles = { "0": {...}, "01": {..., "parent": "0"}, "0132": {..., "parent": "013"} }`

### 6.4 Built-in Renderers (v1)
- `debug_quadtile_renderer`: renders a flat background and writes the tile ID (e.g. `0132`) in large text in the center of the tile; used to validate tiling, crossfades, and camera movement.
- `mandelbrot_deepzoom_renderer`: renders a Mandelbrot fractal slice for the tile based on camera position/zoom, tuned for visually interesting deep zooms (simulating a long Mandelbrot zoom path).

## 7. Data & APIs (first pass)
- Entities:
  - `Dataset`: id, name, type, base params.
  - `CameraPath`: id, dataset_id, list of keyframes.
  - `Keyframe`: time, position, zoom, rotation_angle, params.
  - `Tile`: tile_id (quadtile string), dataset_id, zoom, parent, storage_path.
  - `Renderer`: id, name, script_path.
- API ideas:
  - `GET /datasets` – list datasets.
  - `POST /datasets` – create dataset config.
  - `PATCH /datasets/:id` – rename / update dataset.
  - `DELETE /datasets/:id` – delete dataset.
  - `POST /paths` – create / update camera path for a dataset.
  - `GET /tiles/{dataset_id}/{tile_id}` – fetch tile.
  - `POST /paths/:id/precompute` – precompute tiles along a path.
  - `GET /renderers` – list available renderer scripts from the `renderers/` folder.

## 8. Constraints & Open Questions
- Target max resolution / zoom depth: no hard limit; design for “as far as we can push it” using sparse tiling.
- Frontend stack: vanilla JavaScript + canvas to start; keep it minimal.
- Gemini involvement: initial version does not use Gemini; long-term goal is AI-based image-generation renderers (e.g. Nano Banana / Nano Banana Pro).
- Storage: local filesystem for all tiles in v1.
- Performance: real-time feel; use `requestAnimationFrame` for rendering and camera updates.
