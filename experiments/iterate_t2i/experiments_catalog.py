from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class Experiment:
    """
    An Experiment is a named template for generating a dataset config + running evaluation.

    These are intentionally descriptive (not v6/v7/etc) so future agents don't loop.
    """

    key: str
    name: str
    description: str
    tile_size: int
    comfy_server: str = "127.0.0.1:8000"
    prompt_t2i: str = "organic biological texture, intricate veins, microscopic, 8k, sharp focus"
    prompt_img2img: str = "Generate the missing center part of this image. Ensure seamless blending."
    denoise: float = 0.2
    t2i_workflow: str = "experiments/iterate_t2i/workflows/z_image_turbo_t2i_workflow.json"
    i2i_workflow: str = "experiments/iterate_t2i/workflows/genzoom_inpaint_diffdiff_workflow.json"

    # Canvas/inpaint controls (v5+ family).
    pad_px: Optional[int] = None
    mask_blur_px: int = 8
    fill_strategy: str = "neighbors_or_parent"
    inpaint_region: str = "full_tile"
    border_ring_px: int = 0
    inpaint_alpha: int = 0


EXPERIMENTS: Dict[str, Experiment] = {
    # V5: inpaint padded canvas with SetLatentNoiseMask (no mask blur in the python side).
    "inpaint_setlatent_256": Experiment(
        key="inpaint_setlatent_256",
        name="Inpaint (SetLatentNoiseMask) 256",
        description="Legacy V5: padded canvas, full-tile inpaint using SetLatentNoiseMask workflow.",
        tile_size=256,
        denoise=0.1,
        i2i_workflow="experiments/iterate_t2i/workflows/genzoom_inpaint_setlatent_workflow.json",
        pad_px=128,
        mask_blur_px=0,
        fill_strategy="neighbors_only",
        inpaint_region="full_tile",
    ),
    # V6: DifferentialDiffusion + InpaintModelConditioning; feathered mask.
    "inpaint_diffdiff_256": Experiment(
        key="inpaint_diffdiff_256",
        name="Inpaint (DifferentialDiffusion) 256",
        description="Legacy V6: padded canvas, full-tile inpaint using DifferentialDiffusion workflow.",
        tile_size=256,
        denoise=0.1,
        i2i_workflow="experiments/iterate_t2i/workflows/genzoom_inpaint_diffdiff_workflow.json",
        pad_px=128,
        mask_blur_px=8,
        fill_strategy="neighbors_only",
        inpaint_region="full_tile",
    ),
    # V6-2: Higher denoise variant.
    "inpaint_diffdiff_high_denoise_256": Experiment(
        key="inpaint_diffdiff_high_denoise_256",
        name="Inpaint (DifferentialDiffusion, High Denoise) 256",
        description="Legacy V6-2: same as V6 but higher denoise.",
        tile_size=256,
        denoise=0.3,
        i2i_workflow="experiments/iterate_t2i/workflows/genzoom_inpaint_diffdiff_workflow.json",
        pad_px=128,
        mask_blur_px=8,
        fill_strategy="neighbors_only",
        inpaint_region="full_tile",
    ),
    # V7: Fill missing context using parent tiles (avoid black padding), stronger feather.
    "inpaint_parent_fill_256": Experiment(
        key="inpaint_parent_fill_256",
        name="Inpaint (Parent-Filled Context) 256",
        description="Legacy V7: fill missing context tiles from parent quadrants; strong feather.",
        tile_size=256,
        denoise=0.1,
        i2i_workflow="experiments/iterate_t2i/workflows/genzoom_inpaint_diffdiff_workflow.json",
        pad_px=128,
        mask_blur_px=16,
        fill_strategy="neighbors_or_parent",
        inpaint_region="full_tile",
    ),
    # V7-2: same idea at 512.
    "inpaint_parent_fill_512": Experiment(
        key="inpaint_parent_fill_512",
        name="Inpaint (Parent-Filled Context) 512",
        description="Legacy V7-2: 512px tiles; parent-filled context; strong feather.",
        tile_size=512,
        denoise=0.15,
        i2i_workflow="experiments/iterate_t2i/workflows/genzoom_inpaint_parent_fill_512_workflow.json",
        pad_px=128,
        mask_blur_px=16,
        fill_strategy="neighbors_or_parent",
        inpaint_region="full_tile",
    ),
    # V8: 512 neighbor+parent fill, less mask blur, higher denoise for sharpness.
    "inpaint_neighbor_or_parent_512": Experiment(
        key="inpaint_neighbor_or_parent_512",
        name="Inpaint (Neighbor + Parent Context) 512",
        description="Legacy V8: 512px tiles; neighbor context where available, parent-fill fallback; moderate feather.",
        tile_size=512,
        denoise=0.3,
        i2i_workflow="experiments/iterate_t2i/workflows/genzoom_inpaint_neighbor_or_parent_512_workflow.json",
        pad_px=128,
        mask_blur_px=8,
        fill_strategy="neighbors_or_parent",
        inpaint_region="full_tile",
    ),
    # V9: preserve border ring and inpaint interior only.
    "inpaint_border_ring_512": Experiment(
        key="inpaint_border_ring_512",
        name="Inpaint (Border Ring Preserve) 512",
        description="Legacy V9: copy neighbor edge strips into border ring (if present), inpaint interior only.",
        tile_size=512,
        denoise=0.5,
        i2i_workflow="experiments/iterate_t2i/workflows/genzoom_inpaint_border_ring_512_workflow.json",
        pad_px=128,
        mask_blur_px=8,
        fill_strategy="neighbors_or_parent",
        inpaint_region="interior_only",
        border_ring_px=51,
    ),
    # V10: Heavy mask blur to force blending (using Differential Diffusion).
    "inpaint_heavy_blur_512": Experiment(
        key="inpaint_heavy_blur_512",
        name="Inpaint (Heavy Blur) 512",
        description="V10: 64px mask blur to force seamless blending with neighbors.",
        tile_size=512,
        denoise=0.3,
        i2i_workflow="experiments/iterate_t2i/workflows/genzoom_inpaint_neighbor_or_parent_512_workflow.json",
        pad_px=128,
        mask_blur_px=64,
        fill_strategy="neighbors_or_parent",
        inpaint_region="full_tile",
    ),
}


LEGACY_VERSION_TO_EXPERIMENT = {
    "v5": "inpaint_setlatent_256",
    "v6": "inpaint_diffdiff_256",
    "v6_2": "inpaint_diffdiff_high_denoise_256",
    "v7": "inpaint_parent_fill_256",
    "v7_2": "inpaint_parent_fill_512",
    "v8": "inpaint_neighbor_or_parent_512",
    "v9": "inpaint_border_ring_512",
}
