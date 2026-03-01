# Ultra-Resolution Quads

**Ultra-Resolution Quads** is a high-performance tiled rendering system designed to support "infinite" zoom capabilities without floating-point precision errors. It relies on a sparse quadtree structure to serve and explore ultra-resolution imagery.

The project is divided into a core viewer (frontend) and pluggable backend renderers that generate the tile content.

## Status

- Pre-alpha / research project: the viewer works, datasets/renderers exist, APIs may change quickly.
- Current renderer focus: fractals (arbitrary precision via `fractalshades`) + a debug grid renderer.
- In progress: text-to-image / diffusion-based renderers that can generate coherent tiles across scale.

## 🏗 Architecture

### 1. Core Viewer (Frontend)
The frontend is a vanilla JS web application located in `frontend/`. It handles:
-   **Quadtree Navigation:** Efficiently loads tiles based on zoom level and viewport.
-   **Layer-Stack Camera:** Uses integer coordinates + float offsets to bypass standard floating-point limitations.
-   **Tile Caching & Rendering:** Manages DOM elements or Canvas drawing for smooth panning and zooming.
-   **Precision:** Uses `Decimal.js` for camera math to reach very deep zoom levels.

### 2. Pluggable Renderers (Backend)
The backend generates the static image tiles served to the viewer. The system supports both offline batch rendering and live on-demand rendering.

- **Offline (Batch):** `backend/render_tiles.py` generates the full pyramid, path-driven, or explicit tile list.
- **Live (On-demand):** `backend/live_server.py` (FastAPI) renders missing tiles on the fly and caches them.

---

## 🚀 Quickstart (Local)

Prereqs: Python 3.11+ and Node.js.

1.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

2.  **Start the Repo:**
    ```bash
    ./start.sh
    ```
    Open `http://localhost:8001/` (redirects to `frontend/index.html`).

3.  **Generate a Tiled Dataset (Optional):**
    *Option A: Debug Grid (Fast)*
    ```bash
    python backend/render_tiles.py --dataset debug_quadtile
    ```
    
    *Option B: Deep Zoom Fractal (Computationally Intensive)*
    ```bash
    python backend/render_tiles.py --dataset glossy_seahorse --mode path
    ```

---

## 🌟 Fractal Gallery Showcase

We include a dedicated gallery generation script to demonstrate the capabilities of the Fractal Renderer.

| Type | Description |
| :--- | :--- |
| **Mandelbrot** | The classic set, supported with arbitrary precision. |
| **Burning Ship** | Including variants like **Shark Fin** and **Perpendicular**. |
| **Power Tower** | Tetration fractals showing map-like structures. |
| **Visualization** | Supports 3D glossy lighting, Distance Estimation (DEM), and Fieldlines. |

### Generating the Gallery
Run the following command to generate a set of 10 high-quality example fractals:
```bash
python experiments/fractal_gallery.py
```
The images will be saved to `artifacts/gallery_v2/`.

---

## 🔧 How It Works

### Backend (`backend/`)
- `live_server.py`: FastAPI server that renders a missing tile, writes it to disk, and returns it.
  - Endpoint: `GET /live/<dataset>/<level>/<x>/<y>.webp`
  - Health/progress: `GET /status`
- `render_tiles.py`: offline/batch tile generator.
- `renderer_utils.py`: dynamic renderer loading + `tiles.json` manifest generation.

### Dataset Format (`datasets/<id>/`)
- `config.json`: dataset metadata + renderer wiring.
- `render.py`: the renderer class referenced by `config.json`.
- Rendered tiles: `datasets/<id>/<level>/<x>/<y>.webp` (gitignored).
- Optional manifest: `datasets/<id>/tiles.json` (gitignored).

### Rendering Tiles
**Batch render:**
```bash
python backend/render_tiles.py --dataset debug_quadtile --mode full --max_level 5
python backend/render_tiles.py --dataset glossy_seahorse --mode path
python backend/render_tiles.py --dataset multibrot_p4 --tiles "0/0/0,1/0/0,1/1/0"
```

**Live render:**
- Start the repo with `./start.sh`
- Toggle “Live Render” in the UI
- Pan/zoom; missing tiles are rendered and cached to `datasets/<id>/...`

---

## 🧪 Experiments & Tooling

### Telemetry & Automation
The viewer includes features for automated testing and performance profiling.
*   `autoplay`: If `true`, automatically starts the camera path.
*   `window.externalLoopHook(state, timestamp)`: Hook for custom logic on every frame.
*   **Experiment Runner:** `python scripts/run_browser_experiment.py` automates browser sessions with Playwright.

### Text-to-Image (WIP)
The repo contains a robust ComfyUI API client and experiments for T2I tile rendering:
- `backend/comfyui_client.py`: API client.
- `experiments/z_image_turbo_t2i.py`: Text-to-image generation.
- `experiments/comfyui_hallucination_test.py`: Hallucination/upscale analysis.
- `experiments/iterate_t2i/`: Dedicated folder for iterating on seamless generative zoom.

### Perplexity Search (CLI)
Use Perplexity Sonar via OpenRouter for fresh web context:
```bash
python scripts/perplexity_search.py "latest research on ultra-high-res tile streaming"
```

---

## 🔍 Tests

```bash
bash tests/run_all_tests.sh
```
Includes camera parity tests, frontend math tests, and path audits.

## 📖 Documentation

-   **Fractal Generation:** See [docs/FRACTALSHADES_GUIDE.md](docs/FRACTALSHADES_GUIDE.md).
-   **Project Internals:** See `PRD.md` (if available).

## License

No license is included yet. If you want to contribute or reuse this code, please open an issue so we can pick an appropriate license.
