from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class ModelSpec:
    """
    A model choice = its own workflows + optional model filename overrides.

    If an override is None, the workflow JSON's default is used.
    """

    key: str
    name: str
    description: str

    t2i_workflow: str
    i2i_workflow: str

    # Optional bindings override (maps workflow node ids/keys). If None, use the shared default.
    bindings_file: Optional[str] = None

    # Optional model filename overrides.
    unet_name: Optional[str] = None
    clip_name: Optional[str] = None
    vae_name: Optional[str] = None

    # Default sampler knobs (can be overridden per script run).
    t2i_steps: Optional[int] = 8
    t2i_cfg: Optional[float] = 1.0
    i2i_steps: Optional[int] = 12
    i2i_cfg: Optional[float] = 1.0
    i2i_denoise: Optional[float] = 0.35


MODEL_SPECS: Dict[str, ModelSpec] = {
    # Current best seam-benchmark candidate: Qwen Edit conditioning + z_image_turbo UNet.
    "z_image_turbo_q5": ModelSpec(
        key="z_image_turbo_q5",
        name="z_image_turbo (Q5)",
        description="Qwen Image Edit conditioning + z_image_turbo UNet Q5 (default).",
        t2i_workflow="experiments/iterate_t2i/workflows/z_image_turbo_t2i_workflow.json",
        i2i_workflow="experiments/iterate_t2i/workflows/genzoom_inpaint_border_ring_512_workflow.json",
        bindings_file="experiments/iterate_t2i/workflow_bindings_default.json",
        unet_name="z_image_turbo-Q5_K_S.gguf",
        clip_name="Qwen3-4B-Instruct-2507-Q5_K_M.gguf",
        t2i_steps=8,
        t2i_cfg=1.0,
        i2i_steps=12,
        i2i_cfg=1.0,
        i2i_denoise=0.35,
    ),
}


def get_model_spec(key: str) -> ModelSpec:
    if key not in MODEL_SPECS:
        raise KeyError(f"Unknown model '{key}'. Available: {', '.join(sorted(MODEL_SPECS))}")
    return MODEL_SPECS[key]
