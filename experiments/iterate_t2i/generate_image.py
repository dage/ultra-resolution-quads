#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from comfy_runner import load_bindings, load_workflow, run_dir, run_t2i
from models_catalog import get_model_spec


def main(*, model_key: Optional[str] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=model_key, help="Model key (see models_catalog.py).")
    ap.add_argument("--server", default="127.0.0.1:8000")
    ap.add_argument("--mock", action="store_true", help="Run without a live ComfyUI server (deterministic output).")
    ap.add_argument("--prompt", default="organic biological texture, intricate veins, microscopic, 8k, sharp focus")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--steps", type=int, default=None)
    ap.add_argument("--cfg", type=float, default=None)
    ap.add_argument("--out", default=None, help="Output path; defaults to artifacts/iterate_t2i/generate/<ts>/image.png")
    args = ap.parse_args()

    if not args.model:
        raise SystemExit("Provide --model <key>.")
    spec = get_model_spec(str(args.model))

    wf = load_workflow(spec.t2i_workflow)
    b = load_bindings(spec.bindings_file or "experiments/iterate_t2i/workflow_bindings_default.json", kind="t2i")

    steps = args.steps if args.steps is not None else spec.t2i_steps
    cfg = args.cfg if args.cfg is not None else spec.t2i_cfg

    img = run_t2i(
        server=str(args.server),
        workflow=wf,
        bindings=b,
        prompt=str(args.prompt),
        seed=args.seed,
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
        out_path = run_dir(kind=f"generate_{spec.key}") / "image.png"

    img.save(out_path)
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
