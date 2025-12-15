# iterate_t2i — Autonomous Iteration Instructions

This folder is the “autonomous agent workspace” for improving **Generative Infinity Zoom** seam quality when generating tiles via ComfyUI.

The canonical experiment record is `experiments/iterate_t2i/ITERATION_HISTORY.md`. Keep it accurate and update it as new things are tried.

## Goals

- Produce a **seamless** stitch at the **L1 2×2 intersection** (4 tiles meeting).
- Make it easy to benchmark new models and new workflow ideas without creating “v10/v11/…” dataset sprawl.
- Keep all temporary files in `artifacts/`, not under `datasets/`.

## Non-Negotiables / Constraints

- **No framework changes** unless explicitly requested. Keep using `backend/render_tiles.py`.
- **No same-level dependency graph**: renderers must not require `dep_level == level`. The render dependency wrapper expects `dep_level < level`.
- **Generated datasets are disposable**. Don’t keep broken tiles around; keep knowledge in docs.

## Key Tools You Can Use

- Web research:
  - `python scripts/perplexity_search.py "<query>"`
  - Requires `OPENROUTER_API_KEY` (and optional `OPENROUTER_BASE_URL`).
- VLM seam scoring (optional, “score like before”):
  - `python backend/tools/analyze_image.py <image.png> --prompt "<prompt>"`
  - Requires `OPENROUTER_API_KEY`.

## Current System (How It Works Now)

### 1) Experiments are named templates

Experiments are defined in `experiments/iterate_t2i/experiments_catalog.py`.

- Use descriptive keys like `inpaint_border_ring_512`, not version numbers.
- Each experiment captures:
  - workflow JSON path (under `experiments/iterate_t2i/workflows/`)
  - tile size (target: 512×512)
  - denoise / mask blur / border ring / fill strategy

### 2) Datasets are generated from experiments (and ignored)

The runner generates a dataset folder at `datasets/genzoom_exp_<experiment_key>/` using:

- Generator: `experiments/iterate_t2i/generate_dataset.py`
- Shared renderer: `experiments/iterate_t2i/inpaint_zoom_renderer.py`

`datasets/genzoom_exp_*/` is ignored in git and can be deleted at any time.

### 3) Rendering and evaluation is standardized

- Rendering: L0 root + L1 quad (4 tiles)
- Evaluation: stitch L1 quad, crop around the 4-tile intersection, compute deterministic seam metric, and optionally ask a VLM for `SCORE: X/10`.

Evaluator: `experiments/iterate_t2i/evaluate_dataset.py`

### 4) Results are always written as an HTML table

Runner: `experiments/iterate_t2i/run_experiments.py`

Outputs:
- `artifacts/iterate_t2i/report.html` (append-only table of runs)
- `artifacts/iterate_t2i/rows.json` (machine-readable run data)
- `artifacts/iterate_t2i/runs/<timestamp>_<experiment>/` (images + `summary.json`)

## How To Run (Typical Loop)

1) Pick a hypothesis (1 change only):
   - example: “mask feathering is modifying border pixels → reduce mask blur or increase border ring”
2) Add or edit an experiment in `experiments/iterate_t2i/experiments_catalog.py`.
3) Run it:
   - `python experiments/iterate_t2i/run_experiments.py --experiment <key>`
4) Compare:
   - Deterministic metric: `seam_mad_avg` (lower is better)
   - Optional VLM: `SCORE: X/10` (higher is better, but noisier)
5) Document:
   - Update `experiments/iterate_t2i/ITERATION_HISTORY.md`:
     - what changed, why, what happened, and what to try next
     - explicitly add “What did not work” entries to prevent loops

## When To Use Research (Perplexity)

Use `scripts/perplexity_search.py` when you need *new* ideas, e.g.:
- “ComfyUI inpaint preserve border pixels mask feather”
- “tiled diffusion seamless stitching overlap crop”
- “ControlNet tile / MultiDiffusion seam reduction”

When you add a researched idea, document:
- the search query
- the key actionable takeaway
- how you translated it into an experiment knob/workflow change

## When To Use VLM Scoring

VLM scoring is useful for qualitative ranking, but:
- It can be noisy across runs.
- Prefer `seam_mad_avg` for regression detection.

If VLM is used, keep the prompt stable and record the score + model used.

## Hygiene / Repo Discipline

- Don’t add/commit generated tiles.
- Keep temp files in `artifacts/` only.
- Prefer editing experiments via `experiments_catalog.py` (single source of truth).
- If you delete old generated datasets, do not delete the documentation/history.
