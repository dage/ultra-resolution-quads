# Generative Infinity Zoom

This dataset demonstrates recursive infinite zoom using Generative AI (ComfyUI).

## Concept
1. **Root (Level 0)**: Generated via Text-to-Image (T2I).
2. **Zoom (Level > 0)**: Generated via Image-to-Image (Img2Img) Upscaling. 
   - Each child tile is a 2x upscale of a 512x512 quadrant of its parent.
   - This maintains consistency while hallucinating new details.

## Iteration / Benchmarking (Do Not Duplicate Here)

This file documents the **baseline dataset** and how to render/view it.

For the current iterative experimentation workflow (named experiments, dataset generation, evaluation, and reporting), use:
- `experiments/iterate_t2i/INSTRUCTIONS.md`
- `experiments/iterate_t2i/ITERATION_HISTORY.md`

## Prerequisites
- **ComfyUI** running locally at `http://127.0.0.1:8000`.
- Workflows:
  - `experiments/iterate_t2i/workflows/z_image_turbo_t2i_workflow.json` (Required models: `z_image_turbo-Q5_K_S.gguf`)
  - `experiments/iterate_t2i/workflows/comfyui_hallucination_test_comfyui_workflow.json`

## Workflow

### 1. Generation
With the default high-quality configuration, generation takes ~3 minutes per tile. For a smooth experience, we recommend pre-generating the initial levels.

**Option A: Generate L0 + L1 (Recommended)**
Generates Level 0 and Level 1 (5 tiles total).
```bash
python backend/render_tiles.py --dataset generative_infinity_zoom --tiles 0/0/0,1/0/0,1/1/0,1/0/1,1/1/1
```

**Option B: Render via the view path**
The dataset config uses `render_config.path` to decide what tiles are visible; render a path up to a max level:
```bash
python backend/render_tiles.py --dataset generative_infinity_zoom --mode path --max_level 4
```

### 2. Viewing
Use the project's startup script to launch the viewer.
```bash
./start.sh
```
Open the viewer at:  
`http://localhost:8001/frontend/index.html?dataset=generative_infinity_zoom`

*Note: You can also rely on the backend's "live" rendering features by simply browsing to new areas in the viewer. Depending on your GPU and model settings, this may result in a delay while tiles are generated.*

## Logic Verification (Mock Mode)
To prove that the infinite zoom math (cropping/stitching) is correct without running ComfyUI:
```bash
python experiments/iterate_t2i/test_generative_zoom.py --mock --clean
```
Expected Result: Very low MSE (~0.0 - 1.0) and "VLM Verdict: Identical".
