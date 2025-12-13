# Ultra-Resolution Quads

**Ultra-Resolution Quads** is a high-performance tiled rendering system designed to support "infinite" zoom capabilities without floating-point precision errors. It relies on a sparse quadtree structure to serve and explore ultra-resolution imagery.

The project is divided into a core viewer (frontend) and pluggable backend renderers that generate the tile content.

## 🏗 Architecture

### 1. Core Viewer (Frontend)
The frontend is a vanilla JS web application located in `frontend/`. It handles:
-   **Quadtree Navigation:** Efficiently loads tiles based on zoom level and viewport.
-   **Layer-Stack Camera:** Uses integer coordinates + float offsets to bypass standard floating-point limitations.
-   **Tile Caching & Rendering:** Manages DOM elements or Canvas drawing for smooth panning and zooming.

### 2. Pluggable Renderers (Backend)
The backend generates the static image tiles served to the viewer. The system is designed to support multiple types of renderers.

#### A. Fractal Renderer (Fractalshades)
A powerful rendering engine based on [Fractalshades](https://gbillotey.github.io/Fractalshades-doc/) for creating mathematical fractals with arbitrary precision.

-   **Features:** Deep zooming (perturbation theory), 3D lighting, fieldlines, and diverse fractal types (Mandelbrot, Burning Ship, Power Tower).
-   **Code:** `backend/fractal_renderer.py` (Wrapper), `backend/fractal_renderer_models.py` (Custom Models).
-   **Usage:** See [docs/FRACTALSHADES_GUIDE.md](docs/FRACTALSHADES_GUIDE.md) for details.

#### B. Debug Renderer
A simple renderer used for testing the quadtree logic. It generates tiles with grid coordinates and debug information.

-   **Usage:** `backend/generate_dataset.py --renderer debug`

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

## 🚀 Getting Started

1.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

2.  **Generate a Tiled Dataset:**
    To use the web viewer, generate a dataset using one of the renderers.
    
    *Option A: Debug Grid (Fast)*
    ```bash
    python backend/generate_dataset.py --dataset debug_quadtile --renderer debug --max_level 6
    ```
    
    *Option B: Deep Zoom Fractal (Computationally Intensive)*
    ```bash
    python backend/generate_dataset.py --dataset power_tower --renderer mandelbrot --max_level 15 --mode path
    ```

3.  **Start the Viewer:**
    ```bash
    python -m http.server 8000
    ```
    Open `http://localhost:8000/frontend/index.html` to explore.

## Telemetry & Automation
The viewer includes features for automated testing and performance profiling.

### URL Parameters
*   `dataset`: Automatically load a specific dataset ID on startup.
*   `autoplay`: If `true`, automatically starts the camera path once the initial tiles are loaded.
    *   *Example:* `http://localhost:8000/frontend/index.html?dataset=glossy_seahorse&autoplay=true`

### Script Injection Hooks
External scripts (e.g., Playwright/Selenium) can interface with the render loop:

*   `window.appState`: Access the full application state (camera position, config, etc.).
*   `window.activeTileElements`: Access the Map of currently rendered DOM elements to check load status.
*   `window.externalLoopHook(state, timestamp)`: Define this function to execute custom logic on every render frame.

### Running Experiments
We provide a generic Python runner to automate experiments using these hooks.

**Usage:**
1.  Create a JavaScript file (e.g., `experiments/my_hook.js`) defining `window.externalLoopHook` and pushing data to `window.telemetryData`.
2.  Run the experiment:
    ```bash
    python scripts/run_browser_experiment.py \
        --dataset <dataset_id> \
        --hook experiments/my_hook.js \
        --output artifacts/my_results.json
    ```
3.  The runner will launch the browser, inject your hook, autoplay the dataset's path, and save the collected `window.telemetryData` to the JSON output file.
4.  If your hook needs to flush a final summary after playback, expose an optional `window.emitTextContentTelemetryNow()` (or similar) and the runner will call it before reading `telemetryData`.

## 🔍 Quick Perplexity Search (CLI)

Use Perplexity Sonar (cheap tier) via OpenRouter to fetch fresh web context for agents—no UI required.

1.  Ensure `OPENROUTER_API_KEY` is available (the script auto-loads the repo `.env`; existing env vars override file values).
2.  Run a search with a prompt (multiline via standard shell quoting/heredoc):
    ```bash
    python scripts/perplexity_search.py "latest research on ultra-high-res tile streaming"
    # or
    python scripts/perplexity_search.py "$(cat <<'EOF'
    Summarize camera interpolation methods for quadtree renderers.
    Focus on papers newer than 2022.
    EOF
    )"
    ```
The script hardcodes `perplexity/sonar` with medium context and prints the answer plus citations to stdout.

## ComfyUI Upscale “Hallucination” Test (Experiment)

Runs a fixed ComfyUI workflow against a default tile from `datasets/` and generates a standalone HTML A/B report:

```bash
python experiments/comfyui_hallucination_test.py --server 127.0.0.1:8188
```

This experiment downscales the input by default (`--downscale-input 0.5`) to keep the workflow fast, while still exercising the workflow’s internal 2× upscale. (The ComfyUI desktop app often listens on `127.0.0.1:8000`.)

Outputs are written to `artifacts/comfyui_hallucination_test/` (images, `meta_<seed>.json`, and `report_<seed>.html`). You can regenerate only the HTML from existing artifacts with `--regen-html --seed <seed>`.

## ComfyUI Z-Image Turbo Text-to-Image (Experiment)

Generates a 1024x1024 image from a text prompt using `z-image turbo` via ComfyUI, and optionally analyzes the result using an AI vision model.

```bash
python experiments/z_image_turbo_t2i.py "A futuristic city with flying cars" --server 127.0.0.1:8000 --ai-analyze
```

**Options:**
-   `prompt`: The text description of the image to generate.
-   `--server`: ComfyUI server address (default: `127.0.0.1:8000`).
-   `--seed`: Random seed (default: 0 for random).
-   `--ai-analyze`: Analyze the generated image using OpenRouter/Qwen-VL to check prompt adherence.

Outputs are saved to `artifacts/z_image_turbo_t2i/`.

## 📖 Documentation

-   **Fractal Generation:** See [docs/FRACTALSHADES_GUIDE.md](docs/FRACTALSHADES_GUIDE.md).
-   **Project Internals:** See `PRD.md` (if available) for architectural decisions.
