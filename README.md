# Ultra-Resolution Quads

A precision-safe deep-zoom viewer + pluggable tile renderers (fractals today, text-to-image next).

This repo is a working prototype for a “true infinite zoom” pipeline:
render tiles on demand, cache them, and navigate to extreme zoom levels without the usual float64 drift.

## Status

- Pre-alpha / research project: the viewer works, datasets/renderers exist, APIs may change quickly.
- Current renderer focus: fractals (arbitrary precision via `fractalshades`) + a debug grid renderer.
- In progress: text-to-image / diffusion-based renderers that can generate coherent tiles across scale.

## Quickstart (Local)

Prereqs: Python 3.11+ and Node.js. We require both since we try to avoid duplicating logic across front-end and back-end by having a shared JS code folder.

```bash
pip install -r requirements.txt
./start.sh
```

Open `http://localhost:8001/` (redirects to `frontend/index.html`).

Fastest “it works” dataset:
```bash
python backend/render_tiles.py --dataset debug_quadtile
```

Then select `Debug Quadtile` in the UI.

Optional extras:
- Fractal datasets: `pip install fractalshades numba`
- Browser automation: `pip install playwright && playwright install chromium`

## How It Works

**Frontend (`frontend/`)**
- Vanilla JS viewer (no build step).
- Precision-safe camera math using `Decimal.js` + integer tile coordinates.
- Sparse quadtree tile selection + prioritized request queue.
- Optional “Live Render” mode that asks the backend to render missing tiles on demand.

**Backend (`backend/`)**
- `backend/live_server.py`: FastAPI server that renders a missing tile, writes it to disk, and returns it.
  - Endpoint: `GET /live/<dataset>/<level>/<x>/<y>.webp`
  - Health/progress: `GET /status`
- `backend/render_tiles.py`: offline/batch tile generator (full pyramid, path-driven, or explicit tile list).
- `backend/renderer_utils.py`: dynamic renderer loading + `tiles.json` manifest generation.

**Dataset format (`datasets/<id>/`)**
- `config.json`: dataset metadata + renderer wiring.
- `render.py`: the renderer class referenced by `config.json`.
- Rendered tiles (generated locally, gitignored): `datasets/<id>/<level>/<x>/<y>.webp`
- Optional manifest (generated locally, gitignored): `datasets/<id>/tiles.json`

## Rendering Tiles

**Batch render (recommended for reproducible demos)**
```bash
python backend/render_tiles.py --dataset debug_quadtile --mode full --max_level 5
python backend/render_tiles.py --dataset glossy_seahorse --mode path
python backend/render_tiles.py --dataset multibrot_p4 --tiles "0/0/0,1/0/0,1/1/0"
```

Notes:
- `--mode full` generates the full pyramid up to `--max_level`.
- `--mode path` generates tiles needed along the dataset’s camera path (`render_config.path`).
- Worker defaults come from each dataset’s `supports_multithreading` flag; override with `--workers`.

**Live render (great for exploration)**
- Start the repo with `./start.sh`
- Toggle “Live Render” in the UI
- Pan/zoom; missing tiles are rendered and cached to `datasets/<id>/...`

## Adding a New Renderer / Dataset

1. Create `datasets/<new_id>/render.py` with a renderer class:
   - Constructor takes `tile_size` (or reads it from kwargs).
   - Implements `render(level, x, y) -> PIL.Image.Image`.
2. Create `datasets/<new_id>/config.json`:
   - `renderer`: import path like `datasets.<new_id>.render:MyRenderer`
   - `tile_size`: 256/512/1024/…
   - Optional `renderer_args`, `render_config`, and `supports_multithreading`.
3. Add it to `datasets/index.json` so it appears in the UI.

## Text-to-Image Direction (WIP)

There isn’t a production T2I tile renderer wired into `datasets/` yet, but the repo already contains:
- A robust ComfyUI API client: `backend/comfyui_client.py`
- Workflow runner CLI: `backend/tools/run_comfyui_workflow.py`
- Experiments for text-to-image and “hallucination”/upscale analysis:
  - `experiments/z_image_turbo_t2i.py`
  - `experiments/comfyui_hallucination_test.py`

The intended next step is a dataset renderer that calls a model (local or ComfyUI) with coordinate- and scale-aware conditioning, so tiles remain coherent across:
adjacent tiles, parent/child tiles, and camera motion.

## Experiments & Tooling (Optional)

**Browser automation + telemetry**
- `scripts/run_browser_experiment.py` (Playwright) can inject `window.externalLoopHook` and record `window.telemetryData`.
- The viewer supports URL params like `?dataset=<id>&autoplay=true`.

**OpenRouter utilities**
- `scripts/perplexity_search.py` uses OpenRouter + Perplexity Sonar (needs `OPENROUTER_API_KEY`).
- `backend/tools/analyze_image.py` can run vision-model analysis for experiment outputs.

Environment variables live in `.env` (see `.env_template`).

## Tests

```bash
bash tests/run_all_tests.sh
```

This runs:
- Python parity tests for camera/path logic
- Node-based smoke tests for frontend math and view logic
- A path/tiles audit script

## Contributing

Contributions are welcome. 

## Credits

- `fractalshades` for deep-zoom fractal math and rendering
- FastAPI/Uvicorn for the live tile server
- ComfyUI for AI based image generation and editing
- Decimal.js for precision-safe camera math to reach very deep zoom levels

## License

No license is included yet. If you want to contribute or reuse this code, please open an issue so we can pick an appropriate license.
