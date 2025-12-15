#!/usr/bin/env python3
"""
Dataset generator for the iterative ComfyUI "Generative Infinity Zoom" experiments.

Goals:
- Keep the existing framework: `backend/render_tiles.py` + per-dataset `datasets/<id>/config.json`.
- Keep dataset renderers importable via standard paths (`datasets.<id>.render:Renderer`).
- Avoid copy/pasting large near-identical renderers by using a shared configurable renderer:
  `experiments/iterate_t2i/inpaint_zoom_renderer.py` (`ComfyInpaintZoomRenderer`).
- Ensure all transient files go under `artifacts/` (never into `datasets/`).

Example:
  python experiments/iterate_t2i/generate_dataset.py \\
    --id genzoom_exp_custom_trial \\
    --name "Gen Zoom (Custom Trial)" \\
    --description "Test new UNet with conservative denoise." \\
    --tile-size 512 \\
    --denoise 0.2 \\
    --i2i-workflow experiments/iterate_t2i/workflows/genzoom_inpaint_border_ring_512_workflow.json \\
    --pad 128 --mask-blur 4 \\
    --inpaint-region interior_only --border-ring 48 \\
    --update-index

To support new workflows:
- Use `--bindings-file <json>` to map node ids/keys for prompt, sampler params, ctx/mask uploads, save node, and model nodes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional


REPO_ROOT = Path(__file__).resolve().parents[2]


RENDER_PY_TEMPLATE = """\
from __future__ import annotations

import os
import sys
from pathlib import Path

# Add repo root to sys.path so `backend.*` imports work when invoked via render_tiles.
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root / "experiments" / "iterate_t2i"))

from inpaint_zoom_renderer import ComfyInpaintZoomRenderer


class Renderer(ComfyInpaintZoomRenderer):
    def __init__(self, tile_size={tile_size}, **kwargs):
        dataset_dir = Path(__file__).resolve().parent
        super().__init__(tile_size=int(tile_size), dataset_path=str(dataset_dir), **kwargs)
"""


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_text(path: Path, text: str, *, force: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"{path} already exists (use --force to overwrite)")
    path.write_text(text, encoding="utf-8")


def _update_datasets_index(dataset_id: str, name: str, description: str) -> None:
    index_path = REPO_ROOT / "datasets" / "index.json"
    data = _load_json(index_path)
    datasets = data.get("datasets")
    if not isinstance(datasets, list):
        raise ValueError(f"Unexpected schema in {index_path}: 'datasets' is not a list")

    for item in datasets:
        if isinstance(item, dict) and item.get("id") == dataset_id:
            item["name"] = name
            item["description"] = description
            break
    else:
        datasets.append({"id": dataset_id, "name": name, "description": description})

    index_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--description", default="")
    ap.add_argument("--tile-size", type=int, default=512)

    ap.add_argument("--comfy-server", default="127.0.0.1:8000")
    ap.add_argument("--prompt-t2i", default="organic biological texture, intricate veins, microscopic, 8k, sharp focus")
    ap.add_argument(
        "--prompt-img2img",
        default="Generate the missing center part of this image. Ensure seamless blending. Preserve border consistency.",
    )
    ap.add_argument("--denoise", type=float, default=0.2)
    ap.add_argument("--steps-t2i", type=int, default=None)
    ap.add_argument("--cfg-t2i", type=float, default=None)
    ap.add_argument("--steps-img2img", type=int, default=None)
    ap.add_argument("--cfg-img2img", type=float, default=None)

    ap.add_argument("--t2i-workflow", default="experiments/iterate_t2i/workflows/z_image_turbo_t2i_workflow.json")
    ap.add_argument("--i2i-workflow", default="experiments/iterate_t2i/workflows/genzoom_inpaint_diffdiff_workflow.json")

    ap.add_argument("--pad", type=int, default=None)
    ap.add_argument("--mask-blur", type=int, default=8)
    ap.add_argument("--fill", choices=["neighbors_only", "neighbors_or_parent", "parent_only"], default="neighbors_or_parent")
    ap.add_argument("--inpaint-region", choices=["full_tile", "interior_only"], default="full_tile")
    ap.add_argument("--border-ring", type=int, default=0)
    ap.add_argument("--inpaint-alpha", type=int, choices=[0, 255], default=0)

    ap.add_argument("--bindings-file", default=None, help="Optional JSON file with workflow node bindings.")
    ap.add_argument("--unet-name", default=None, help="Optional default UNet filename override (workflow model node mapping required).")
    ap.add_argument("--clip-name", default=None, help="Optional default CLIP filename override (workflow model node mapping required).")
    ap.add_argument("--vae-name", default=None, help="Optional default VAE filename override (workflow model node mapping required).")

    ap.add_argument("--update-index", action="store_true", help="Update datasets/index.json with this dataset.")
    ap.add_argument("--force", action="store_true", help="Overwrite existing config/render.py if present.")
    args = ap.parse_args()

    dataset_dir = REPO_ROOT / "datasets" / args.id
    dataset_dir.mkdir(parents=True, exist_ok=True)

    bindings: Optional[Dict[str, Any]] = None
    if args.bindings_file:
        bindings = _load_json(Path(args.bindings_file))

    pad = args.pad if args.pad is not None else (args.tile_size // 2)

    # Write render.py wrapper
    render_py_path = dataset_dir / "render.py"
    _write_text(
        render_py_path,
        RENDER_PY_TEMPLATE.format(tile_size=int(args.tile_size)),
        force=args.force,
    )

    config = {
        "id": args.id,
        "name": args.name,
        "description": args.description,
        "tile_size": int(args.tile_size),
        "renderer": f"datasets.{args.id}.render:Renderer",
        "renderer_args": {
            "comfy_server": args.comfy_server,
            "prompt_t2i": args.prompt_t2i,
            "prompt_img2img": args.prompt_img2img,
            "denoise": float(args.denoise),
            "steps_t2i": args.steps_t2i,
            "cfg_t2i": args.cfg_t2i,
            "steps_img2img": args.steps_img2img,
            "cfg_img2img": args.cfg_img2img,
            "t2i_workflow_path": args.t2i_workflow,
            "i2i_workflow_path": args.i2i_workflow,
            "unet_name": args.unet_name,
            "clip_name": args.clip_name,
            "vae_name": args.vae_name,
            "bindings": bindings,
            "canvas": {
                "pad_px": int(pad),
                "mask_blur_px": int(args.mask_blur),
                "fill_strategy": args.fill,
                "inpaint_region": args.inpaint_region,
                "border_ring_px": int(args.border_ring),
                "inpaint_alpha": int(args.inpaint_alpha),
            },
        },
        "supports_multithreading": False,
        "render_config": {
            "mode": "path",
            "max_level": 5,
            "path": {
                "id": "gen_zoom_path",
                "name": "Generative Dive",
                "keyframes": [
                    {"camera": {"level": 0, "x": 0.5, "y": 0.5, "rotation": 0}},
                    {"camera": {"level": 5, "x": 0.5, "y": 0.5, "rotation": 0}},
                ],
            },
        },
    }

    config_path = dataset_dir / "config.json"
    if config_path.exists() and not args.force:
        raise FileExistsError(f"{config_path} already exists (use --force to overwrite)")
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    if args.update_index:
        _update_datasets_index(args.id, args.name, args.description)

    print(f"Wrote {render_py_path}")
    print(f"Wrote {config_path}")
    if args.update_index:
        print("Updated datasets/index.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
