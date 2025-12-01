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
    python backend/generate_dataset.py --dataset mandelbrot_deep --renderer mandelbrot --max_level 15 --mode path
    ```

3.  **Start the Viewer:**
    ```bash
    python -m http.server 8000
    ```
    Open `http://localhost:8000/frontend/index.html` to explore.

## 📖 Documentation

-   **Fractal Generation:** See [docs/FRACTALSHADES_GUIDE.md](docs/FRACTALSHADES_GUIDE.md).
-   **Project Internals:** See `PRD.md` (if available) for architectural decisions.