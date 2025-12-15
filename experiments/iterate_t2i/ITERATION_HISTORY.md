# Generative Infinity Zoom (ComfyUI) — Iteration History

This folder collects the scripts used to iterate on the **Generative Infinity Zoom** renderers that recursively generate deeper zoom tiles via ComfyUI.

The goal is **seamless tile stitching** (especially at the 4-tile intersection at Level 2), while preserving continuity from parent tiles and/or neighbors.

Start here for the current workflow: `experiments/iterate_t2i/INSTRUCTIONS.md`.

## Where Things Live

- Generated dataset definitions (renderer code + config): `datasets/genzoom_exp_*/` (created by the runner; tiles are disposable)
- ComfyUI workflow JSONs used by experiments: `experiments/iterate_t2i/workflows/*.json`
- Quick iteration scripts (this folder): `experiments/iterate_t2i/`
- Debug artifacts / reports / seam crops: `artifacts/`

## How We Score Seams

The current scoring loop is defined in `experiments/iterate_t2i/INSTRUCTIONS.md` and is intentionally standardized:
- render L0 + L1 (2×2)
- stitch L1 quad and crop around the intersection
- compute deterministic seam metric + optional VLM `SCORE: X/10`

## Key Gotchas Found

- **Mask polarity seems inverted** for our inpaint workflow wiring: in diagnostics, the intended inpaint region behaved most like “inpaint area” when the **mask alpha was 0 in the inpaint region** (not 255).
  - Diagnostic runner: `experiments/iterate_t2i/diagnose_inpaint_mechanism.py`
  - Example outputs: `artifacts/diagnostics_inpaint_v6/`
- **Denoise / steps tuning didn’t move seam scores much** across V5–V9; many attempts converged to ~3–4/10 VLM ratings.
  - This suggests either (a) the workflow/model combination lacks the required border adherence, (b) mask feathering still alters seam pixels, or (c) the scoring method is too noisy and needs a deterministic seam metric.
- **Some seam crops were initially wrong for 512px stitched images**. The crop centers were fixed in the v7/v7_2 test scripts so the VLM sees the true 4-tile junction.
- For 512px tiles, the stitched L1 quad is 1024×1024 and the intersection is at (512,512); a good crop window is ~128×128 around it.

## Experiments (Legacy → Named Templates)

We previously iterated using dataset ids like `generative_infinity_zoom_v6`, `v7_2`, etc.
Those datasets are **not worth keeping on disk** if the tiles are broken; the important part is the hypothesis and settings.

The runner now uses descriptive experiment keys (see `experiments/iterate_t2i/experiments_catalog.py`) and generates datasets under `datasets/genzoom_exp_<experiment>/`.
The **canonical source of truth** for exact knobs (denoise, mask blur, border ring, workflows, etc.) is `experiments/iterate_t2i/experiments_catalog.py`.

Legacy mapping:

- V5 → `inpaint_setlatent_256`
- V6 → `inpaint_diffdiff_256`
- V6-2 → `inpaint_diffdiff_high_denoise_256`
- V7 → `inpaint_parent_fill_256`
- V7-2 → `inpaint_parent_fill_512`
- V8 → `inpaint_neighbor_or_parent_512`
- V9 → `inpaint_border_ring_512`

## Historical Notes (Chronological)

### Baseline: `generative_infinity_zoom` (existing)
- Recursive zoom: parent tile → child tiles.
- Uses a non-inpainting img2img approach (older workflow).

### V2: `generative_infinity_zoom_v2` (512px)
- Idea: Provide a larger **context image** built from the parent level and draw a **red square** indicating the target region.
- Workflow: `experiments/iterate_t2i/workflows/genzoom_context_redsquare_qwen_workflow.json` (Qwen image-edit conditioning).

### V3: `generative_infinity_zoom_v3` (512px)
- Same as V2 but “precision mode”: **lower denoise** (0.15).

### V4: `generative_infinity_zoom_v4` (512px)
- Idea: Use **same-level neighbor context** (Left/Top/Top-Left) to reduce seams.
- We briefly experimented with forcing same-level dependencies, but this was reverted to keep the render dependency graph strictly acyclic (no same-level deps / “no multipath”).
  - Current rule: `get_required_tiles()` must return only lower levels (`dep_level < level`).

### V5: `generative_infinity_zoom_v5` (256px)
- Pivot to **soft inpainting** on a padded canvas.
- Builds a 2× canvas around the tile and uses:
  - `SetLatentNoiseMask` for masked latent noise injection
  - Then crops the center tile.
- Initial denoise was high; later reduced to **0.1**.
- Workflow: `experiments/iterate_t2i/workflows/genzoom_inpaint_setlatent_workflow.json`

### V6: `generative_infinity_zoom_v6` (256px)
- Upgrades inpainting workflow to:
  - `DifferentialDiffusion`
  - `InpaintModelConditioning`
  - blurred mask edges
- Denoise reduced to **0.1**.
- Workflow: `experiments/iterate_t2i/workflows/genzoom_inpaint_diffdiff_workflow.json`

### V6-2: `generative_infinity_zoom_v6_2` (256px)
- Same as V6 but higher denoise variant (**0.3**).

### V7: `generative_infinity_zoom_v7` (256px)
- Idea: avoid black padding by **filling missing context tiles from parent quadrants** (upscaled approximations).
- Still uses the V6 workflow.

### V7-2: `generative_infinity_zoom_v7_2` (512px)
- Same “parent-filled context” idea but at **512px tiles**.
- Uses a padded canvas and then crops the center tile.
- Workflow: `experiments/iterate_t2i/workflows/genzoom_inpaint_parent_fill_512_workflow.json`

### V8: `generative_infinity_zoom_v8` (512px)
- Idea: combine **neighbor context (L/T/TL)** + **parent-fill fallback**, reduce mask feather to preserve crispness, and increase denoise/steps/cfg a bit for detail.
- Workflow: `experiments/iterate_t2i/workflows/genzoom_inpaint_neighbor_or_parent_512_workflow.json`

### V9: `generative_infinity_zoom_v9` (512px, “border ring”)
- Constraint: “no multipath” (no enforced same-level deps).
- Idea: when neighbors already exist on disk, copy exact **edge strips** from neighbors into a **border ring**, then inpaint **only the interior**.
- Workflow: `experiments/iterate_t2i/workflows/genzoom_inpaint_border_ring_512_workflow.json`

## Results Snapshot (VLM seam score)

These scores come from the `report.html` generated by each test script and are only as reliable as the VLM’s interpretation.

- V5 (256): 3/10
- V6 (256): 3/10
- V6-2 (256): 4/10
- V7 (256): 4/10 (after seam-crop fix)
- V7-2 (512): 3/10 (after seam-crop fix)
- V8 (512): 3/10
- V9 (512): 3/10

Reports:
- `artifacts/gen_zoom_v5_debug/report.html`
- `artifacts/gen_zoom_v6_debug/report.html`
- `artifacts/gen_zoom_v6_2_debug/report.html`
- `artifacts/gen_zoom_v7_debug/report.html`
- `artifacts/gen_zoom_v7_2_debug/report.html`
- `artifacts/gen_zoom_v8_debug/report.html`
- `artifacts/gen_zoom_v9_debug/report.html`

## What Did Not Work (So Far)

This is the “avoid loops” checklist — the stuff we already tested and should not repeat without a new hypothesis:

- Simply lowering denoise to ~0.1 did **not** produce seamless borders (often made outputs blurrier or too close to the upscaled parent).
- Increasing denoise/steps/cfg in the same workflow did **not** reliably improve seams and sometimes worsened border drift.
- Parent-filled context (replacing black padding with parent quadrant approximations) helped avoid empty context but did **not** raise seam score significantly.
- Neighbor context (L/T/TL) did **not** substantially improve intersection seams in our current setup.
- “Border ring” idea (copy neighbor edge strips + inpaint interior) did **not** improve the VLM seam score yet, likely because the sampler still alters border pixels (mask blur / polarity / conditioning effects).

## New Model Focus (Next Phase)

Since you’re downloading new models, we need a benchmark that a better model should improve automatically.

### Deterministic Benchmarks (Preferred)

1. **Mask locality sanity**: the model must obey “change only masked region”.
2. **Border drift**: border ring pixels should remain unchanged (mean absolute diff near-zero).
3. **Pattern continuation**: given a synthetic context texture with lines entering a hole, inpaint should continue them without breaking at the hole edge.

Script scaffold: `experiments/iterate_t2i/benchmark_models.py`

### Model Checklist (Record in commits/issues)

- ComfyUI version + custom nodes list
- Model filenames + exact paths (UNet/CLIP/VAE) and precision settings
- Workflow JSON used
- Prompt(s), denoise/steps/cfg/sampler/scheduler
- Output tile(s) + deterministic metrics + VLM score (optional)

## Refactor Direction (To Reduce Code Duplication)

We discovered a structural limitation: renderers historically inferred their dataset directory from `__file__` because they lived inside `datasets/<id>/render.py`.
We keep the core framework unchanged, so shared renderers are used via tiny per-dataset wrappers that pass `dataset_path` explicitly.

New shared renderer module:
- `experiments/iterate_t2i/inpaint_zoom_renderer.py` (`ComfyInpaintZoomRenderer`)

New dataset generator:
- `experiments/iterate_t2i/generate_dataset.py`

New evaluation script:
- `experiments/iterate_t2i/evaluate_dataset.py` (renders L0+L1 and writes deterministic seam metrics + optional VLM report)

New experiment runner (recommended):
- `experiments/iterate_t2i/run_experiments.py` (runs experiments and writes `artifacts/iterate_t2i/report.html`)

## Scripts in This Folder

- Workflow generators (emit JSON into `experiments/`):
  - `experiments/iterate_t2i/create_v2_workflow.py`
  - `experiments/iterate_t2i/create_v5_workflow.py`
  - `experiments/iterate_t2i/create_v6_workflow.py`
  - `experiments/iterate_t2i/create_v8_workflow.py`
  - `experiments/iterate_t2i/create_v9_workflow.py`
- Dataset generator:
  - `experiments/iterate_t2i/generate_dataset.py`
- Dataset evaluation:
  - `experiments/iterate_t2i/evaluate_dataset.py`
- Experiment runner:
  - `experiments/iterate_t2i/run_experiments.py`
- Model benchmark:
  - `experiments/iterate_t2i/benchmark_models.py`
- Test runners:
  - `experiments/iterate_t2i/test_generative_zoom_v2.py` … `experiments/iterate_t2i/test_generative_zoom_v9.py`
- Diagnostics:
  - `experiments/iterate_t2i/diagnose_inpaint_mechanism.py`

## Recommended Next Iterations

1. **Fix mask polarity intentionally** in the renderers/workflows:
   - If alpha=0 truly corresponds to “inpaint region” for your ComfyUI mask extraction, update mask generation accordingly (or invert masks consistently).
2. Replace VLM-only scoring with a **deterministic seam metric**:
   - Compute pixel-diff along shared edges and at the intersection (mean absolute difference / SSIM in narrow seam strips).
3. If pursuing inpaint-based stitching:
   - Preserve seam pixels deterministically (copy edge strips) and ensure the mask feather does not modify the seam rows/cols.
4. Consider alternative approaches (research-backed):
   - overlap+crop blending; tiled diffusion nodes; ControlNet tile; crop-and-stitch inpaint workflows.
