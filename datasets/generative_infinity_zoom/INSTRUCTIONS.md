# Generative Infinity Zoom

This dataset demonstrates recursive infinite zoom using Generative AI (ComfyUI).

## Concept
1. **Root (Level 0)**: Generated via Text-to-Image (T2I).
2. **Zoom (Level > 0)**: Generated via Image-to-Image (Img2Img) Upscaling. 
   - Each child tile is a 2x upscale of a 512x512 quadrant of its parent.
   - This maintains consistency while hallucinating new details.

## Prerequisites
- **ComfyUI** running locally at `http://127.0.0.1:8000`.
- Workflows:
  - `experiments/z_image_turbo_t2i_workflow.json` (Required models: `z_image_turbo-Q5_K_S.gguf`)
  - `experiments/comfyui_hallucination_test_comfyui_workflow.json`

## Workflow

### 1. Generation
With the default high-quality configuration, generation takes ~3 minutes per tile. For a smooth experience, we recommend pre-generating the initial levels.

**Option A: Run the End-to-End Test (Recommended)**
Generates Level 0 and Level 1 (5 tiles total).
```bash
python experiments/test_generative_zoom.py --clean
```

**Option B: Generate Specific Levels**
```bash
python backend/render_tiles.py --dataset generative_infinity_zoom --level 0
python backend/render_tiles.py --dataset generative_infinity_zoom --level 1
# ... and so on
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
python experiments/test_generative_zoom.py --mock --clean
```
Expected Result: Very low MSE (~0.0 - 1.0) and "VLM Verdict: Identical".