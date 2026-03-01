#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from comfy_runner import load_bindings, load_workflow, run_dir, run_i2i
from models_catalog import get_model_spec


def main(*, model_key: Optional[str] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=model_key, help="Model key (see models_catalog.py).")
    ap.add_argument("--server", default="127.0.0.1:8000")
    ap.add_argument("--mock", action="store_true", help="Run without a live ComfyUI server (deterministic output).")
    ap.add_argument("--input", required=True, help="Input image path (context).")
    ap.add_argument("--mask", required=True, help="Mask image path (RGBA preferred; alpha controls inpaint region).")
    ap.add_argument("--prompt", default="Generate the missing center part of this image. Ensure seamless blending. Preserve border consistency.")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--denoise", type=float, default=None)
    ap.add_argument("--steps", type=int, default=None)
    ap.add_argument("--cfg", type=float, default=None)
    ap.add_argument("--out", default=None, help="Output path; defaults to artifacts/iterate_t2i/inpaint/<ts>/out.png")
    args = ap.parse_args()

    if not args.model:
        raise SystemExit("Provide --model <key>.")
    spec = get_model_spec(str(args.model))

    wf = load_workflow(spec.i2i_workflow)
    b = load_bindings(spec.bindings_file or "experiments/iterate_t2i/workflow_bindings_default.json", kind="i2i")

    denoise = args.denoise if args.denoise is not None else spec.i2i_denoise
    steps = args.steps if args.steps is not None else spec.i2i_steps
    cfg = args.cfg if args.cfg is not None else spec.i2i_cfg

    out = run_i2i(
        server=str(args.server),
        workflow=wf,
        bindings=b,
        ctx_path=Path(args.input),
        mask_path=Path(args.mask),
        prompt=str(args.prompt),
        seed=args.seed,
        denoise=denoise,
        steps=steps,
        cfg=cfg,
        unet=spec.unet_name,
        clip=spec.clip_name,
        vae=spec.vae_name,
        mock=bool(args.mock),
    )

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        out_path = run_dir(kind=f"inpaint_{spec.key}") / "out.png"

    out.save(out_path)
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
