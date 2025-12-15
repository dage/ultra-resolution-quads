import io
import json
import math
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter

from backend.comfyui_client import ComfyUIClient, first_image_ref_from_history


FillStrategy = Literal["neighbors_only", "neighbors_or_parent", "parent_only"]
InpaintRegion = Literal["full_tile", "interior_only"]


@dataclass(frozen=True)
class InpaintCanvasSpec:
    pad_px: int
    mask_blur_px: int
    fill_strategy: FillStrategy
    inpaint_region: InpaintRegion
    border_ring_px: int = 0
    # Our current best guess for Comfy wiring is:
    # - alpha=0 => inpaint region
    # - alpha=255 => keep
    #
    # Some workflows may be opposite; set inpaint_alpha=255 to invert.
    inpaint_alpha: int = 0


@dataclass(frozen=True)
class NodeInputRef:
    node: str
    key: str


@dataclass(frozen=True)
class WorkflowBindings:
    prompt: NodeInputRef
    sampler_node: str
    seed_key: Optional[str]
    denoise_key: Optional[str]
    steps_key: Optional[str]
    cfg_key: Optional[str]
    ctx_images: Tuple[NodeInputRef, ...] = ()
    mask_images: Tuple[NodeInputRef, ...] = ()
    save_node: str = "9"
    unet: Optional[NodeInputRef] = None
    clip: Optional[NodeInputRef] = None
    vae: Optional[NodeInputRef] = None


def _as_node_ref(obj: Any) -> NodeInputRef:
    if isinstance(obj, NodeInputRef):
        return obj
    if not isinstance(obj, dict):
        raise TypeError(f"Expected dict for node ref, got {type(obj)}")
    node = obj.get("node")
    key = obj.get("key")
    if not node or not key:
        raise ValueError(f"Invalid node ref {obj}; expected {{'node': '...', 'key': '...'}}")
    return NodeInputRef(str(node), str(key))


def _as_node_ref_list(obj: Any) -> Tuple[NodeInputRef, ...]:
    if obj is None:
        return ()
    if isinstance(obj, list):
        return tuple(_as_node_ref(x) for x in obj)
    # Back-compat for a single dict
    if isinstance(obj, dict):
        return (_as_node_ref(obj),)
    raise TypeError(f"Expected list[dict] for node refs, got {type(obj)}")


def _merge_bindings(user: Optional[dict]) -> Tuple[WorkflowBindings, WorkflowBindings]:
    """
    Normalize workflow bindings for T2I and I2I patching.

    `user` is a dict that can override node ids/keys for prompts, sampler params,
    ctx/mask image nodes, save node, and optional model nodes.
    """
    defaults = {
        "t2i": {
            "prompt": {"node": "6", "key": "text"},
            "sampler": {"node": "3", "seed": "seed"},
            "save_node": "9",
            "model": {"unet": {"node": "13", "key": "unet_name"}, "clip": {"node": "16", "key": "clip_name"}},
        },
        "i2i": {
            "ctx_images": [{"node": "100", "key": "image"}],
            "mask_images": [{"node": "101", "key": "image"}],
            "prompt": {"node": "6", "key": "prompt"},
            "sampler": {"node": "3", "seed": "seed", "denoise": "denoise", "steps": "steps", "cfg": "cfg"},
            "save_node": "9",
            "model": {"unet": {"node": "13", "key": "unet_name"}, "clip": {"node": "16", "key": "clip_name"}},
        },
    }

    merged = json.loads(json.dumps(defaults))
    if user:
        for kind in ("t2i", "i2i"):
            if kind in user and isinstance(user[kind], dict):
                for k, v in user[kind].items():
                    merged[kind][k] = v

    def _one(kind: str) -> WorkflowBindings:
        d = merged[kind]
        sampler = d.get("sampler") or {}
        model = d.get("model") or {}
        return WorkflowBindings(
            prompt=_as_node_ref(d["prompt"]),
            sampler_node=str(sampler.get("node", "3")),
            seed_key=str(sampler["seed"]) if sampler.get("seed") else None,
            denoise_key=str(sampler["denoise"]) if sampler.get("denoise") else None,
            steps_key=str(sampler["steps"]) if sampler.get("steps") else None,
            cfg_key=str(sampler["cfg"]) if sampler.get("cfg") else None,
            ctx_images=_as_node_ref_list(d.get("ctx_images")),
            mask_images=_as_node_ref_list(d.get("mask_images")),
            save_node=str(d.get("save_node", "9")),
            unet=_as_node_ref(model["unet"]) if model.get("unet") else None,
            clip=_as_node_ref(model["clip"]) if model.get("clip") else None,
            vae=_as_node_ref(model["vae"]) if model.get("vae") else None,
        )

    return _one("t2i"), _one("i2i")


class ComfyInpaintZoomRenderer:
    """
    Shared renderer for the "inpaint padded canvas then crop tile" family (v5+).

    Design goals:
    - No per-dataset code duplication
    - All temp artifacts written under `artifacts/` (never into datasets/)
    - Renderer behavior configurable via constructor kwargs (so configs can be generated)
    """

    def __init__(
        self,
        *,
        tile_size: int = 256,
        dataset_path: Optional[str] = None,
        comfy_server: str = "127.0.0.1:8000",
        prompt_timeout_s: float = 3600.0,
        prompt_t2i: str = "abstract texture",
        prompt_img2img: str = "add detail",
        denoise: float = 0.2,
        steps_t2i: Optional[int] = None,
        cfg_t2i: Optional[float] = None,
        steps_img2img: Optional[int] = None,
        cfg_img2img: Optional[float] = None,
        t2i_workflow_path: str = "experiments/iterate_t2i/workflows/z_image_turbo_t2i_workflow.json",
        i2i_workflow_path: str = "experiments/iterate_t2i/workflows/genzoom_inpaint_diffdiff_workflow.json",
        bindings: Optional[dict] = None,
        unet_name: Optional[str] = None,
        clip_name: Optional[str] = None,
        vae_name: Optional[str] = None,
        canvas: Optional[dict] = None,
        debug_dir: Optional[str] = None,
    ):
        self.tile_size = int(tile_size)
        self.dataset_root = str(dataset_path) if dataset_path else None

        self.comfy_server = comfy_server
        self.prompt_timeout_s = float(prompt_timeout_s)
        self.prompt_t2i = prompt_t2i
        self.prompt_img2img = prompt_img2img
        self.denoise = float(denoise)
        self.steps_t2i = None if steps_t2i is None else int(steps_t2i)
        self.cfg_t2i = None if cfg_t2i is None else float(cfg_t2i)
        self.steps_img2img = None if steps_img2img is None else int(steps_img2img)
        self.cfg_img2img = None if cfg_img2img is None else float(cfg_img2img)

        self.unet_name = unet_name
        self.clip_name = clip_name
        self.vae_name = vae_name

        self.bindings_t2i, self.bindings_i2i = _merge_bindings(bindings)

        self.repo_root = Path(__file__).resolve().parents[2]
        self.t2i_workflow_path = (self.repo_root / t2i_workflow_path).resolve()
        self.i2i_workflow_path = (self.repo_root / i2i_workflow_path).resolve()

        self.wf_t2i = json.loads(self.t2i_workflow_path.read_text(encoding="utf-8"))
        self.wf_i2i = json.loads(self.i2i_workflow_path.read_text(encoding="utf-8"))

        c = canvas or {}
        self.canvas_spec = InpaintCanvasSpec(
            pad_px=int(c.get("pad_px", self.tile_size // 2)),
            mask_blur_px=int(c.get("mask_blur_px", 8)),
            fill_strategy=str(c.get("fill_strategy", "neighbors_or_parent")),
            inpaint_region=str(c.get("inpaint_region", "full_tile")),
            border_ring_px=int(c.get("border_ring_px", 0)),
            inpaint_alpha=int(c.get("inpaint_alpha", 0)),
        )
        if self.canvas_spec.inpaint_alpha not in (0, 255):
            raise ValueError("canvas.inpaint_alpha must be 0 or 255")
        if self.canvas_spec.inpaint_region == "interior_only" and self.canvas_spec.border_ring_px <= 0:
            raise ValueError("border_ring_px must be > 0 when inpaint_region=interior_only")

        self.debug_dir = debug_dir
        self.client_id = f"genzoom-shared-{os.getpid()}-{random.randint(1000, 9999)}"
        self.client = ComfyUIClient(self.comfy_server, self.client_id)

    def supports_multithreading(self):
        return False

    def get_required_tiles(self, level, x, y):
        """
        Dependency policy: only require *lower* levels.

        We need the direct parent plus any parent tiles needed to approximate the
        padded context window (so `_approx_tile_from_parent` never reads missing parents).

        Same-level neighbor tiles are used opportunistically if they already exist on disk,
        but are never returned as "required" (keeps the dependency graph acyclic).
        """
        level = int(level)
        x = int(x)
        y = int(y)
        if level <= 0:
            return []

        # Direct parent for the center tile seed.
        reqs = {(level - 1, x // 2, y // 2)}

        # Only require extra parent tiles when we may need parent-fill fallback for neighbors.
        if self.canvas_spec.fill_strategy in ("neighbors_or_parent", "parent_only"):
            ts = self.tile_size
            pad = self.canvas_spec.pad_px
            canvas_size = ts + 2 * pad
            win_left_px = x * ts - pad
            win_top_px = y * ts - pad

            limit = (1 << level) - 1
            min_tx = max(0, int(math.floor(win_left_px / ts)))
            max_tx = min(limit, int(math.floor((win_left_px + canvas_size - 1) / ts)))
            min_ty = max(0, int(math.floor(win_top_px / ts)))
            max_ty = min(limit, int(math.floor((win_top_px + canvas_size - 1) / ts)))

            for ty in range(min_ty, max_ty + 1):
                for tx in range(min_tx, max_tx + 1):
                    reqs.add((level - 1, tx // 2, ty // 2))

        return sorted(reqs)

    def _tile_path(self, level: int, x: int, y: int) -> Path:
        if not self.dataset_root:
            raise RuntimeError("dataset_path must be provided to ComfyInpaintZoomRenderer to load existing tiles")
        return Path(self.dataset_root) / str(level) / str(x) / f"{y}.webp"

    def _load_tile_rgb(self, level: int, x: int, y: int) -> Optional[Image.Image]:
        p = self._tile_path(level, x, y)
        if not p.exists():
            for ext in [".png", ".jpg", ".jpeg"]:
                alt = p.with_suffix(ext)
                if alt.exists():
                    return Image.open(alt).convert("RGB")
            return None
        return Image.open(p).convert("RGB")

    def _approx_tile_from_parent(self, level: int, x: int, y: int) -> Optional[Image.Image]:
        if level <= 0:
            return None

        ts = self.tile_size
        half_ts = ts // 2
        parent_level = level - 1
        parent_x = x // 2
        parent_y = y // 2

        parent_img = self._load_tile_rgb(parent_level, parent_x, parent_y)
        if parent_img is None:
            return None

        if parent_img.size != (ts, ts):
            parent_img = parent_img.resize((ts, ts), Image.Resampling.LANCZOS)

        qx = x % 2
        qy = y % 2
        left = qx * half_ts
        top = qy * half_ts
        quadrant = parent_img.crop((left, top, left + half_ts, top + half_ts))
        return quadrant.resize((ts, ts), Image.Resampling.LANCZOS)

    def _set_input(self, wf: Dict[str, Any], ref: NodeInputRef, value: Any) -> None:
        node = wf.get(ref.node)
        if not isinstance(node, dict):
            raise KeyError(f"Workflow node '{ref.node}' not found")
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            raise KeyError(f"Workflow node '{ref.node}' missing 'inputs'")
        inputs[ref.key] = value

    def _set_sampler_param(self, wf: Dict[str, Any], *, node_id: str, key: Optional[str], value: Any) -> None:
        if not key:
            return
        node = wf.get(node_id)
        if not isinstance(node, dict):
            raise KeyError(f"Workflow sampler node '{node_id}' not found")
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            raise KeyError(f"Workflow sampler node '{node_id}' missing 'inputs'")
        inputs[key] = value

    def _apply_model_overrides(self, wf: Dict[str, Any], b: WorkflowBindings) -> None:
        if self.unet_name:
            if not b.unet:
                raise ValueError("unet_name provided but bindings.<kind>.model.unet is not configured")
            self._set_input(wf, b.unet, self.unet_name)
        if self.clip_name:
            if not b.clip:
                raise ValueError("clip_name provided but bindings.<kind>.model.clip is not configured")
            self._set_input(wf, b.clip, self.clip_name)
        if self.vae_name:
            if not b.vae:
                raise ValueError("vae_name provided but bindings.<kind>.model.vae is not configured")
            self._set_input(wf, b.vae, self.vae_name)

    def _run_workflow_img2img(self, workflow: dict, *, ctx_path: Path, mask_path: Path) -> Image.Image:
        wf = json.loads(json.dumps(workflow))
        b = self.bindings_i2i

        ctx_name = self.client.upload_image(ctx_path)
        mask_name = self.client.upload_image(mask_path)

        for ref in b.ctx_images:
            self._set_input(wf, ref, ctx_name)
        for ref in b.mask_images:
            self._set_input(wf, ref, mask_name)

        self._set_input(wf, b.prompt, self.prompt_img2img)
        self._set_sampler_param(wf, node_id=b.sampler_node, key=b.seed_key, value=random.randint(1, 10**14))
        self._set_sampler_param(wf, node_id=b.sampler_node, key=b.denoise_key, value=float(self.denoise))
        if self.steps_img2img is not None:
            self._set_sampler_param(wf, node_id=b.sampler_node, key=b.steps_key, value=int(self.steps_img2img))
        if self.cfg_img2img is not None:
            self._set_sampler_param(wf, node_id=b.sampler_node, key=b.cfg_key, value=float(self.cfg_img2img))
        self._apply_model_overrides(wf, b)

        prompt_id = self.client.queue_prompt(wf)
        self.client.wait_for_prompt(prompt_id, timeout_s=self.prompt_timeout_s)

        history = self.client.get_history(prompt_id)
        data = history.get(prompt_id, {})
        img_ref = first_image_ref_from_history(data, preferred_node=b.save_node)
        if not img_ref:
            raise RuntimeError(f"No image returned for prompt {prompt_id}")
        raw = self.client.get_image_data(img_ref)
        return Image.open(io.BytesIO(raw)).convert("RGB")

    def _make_temp_paths(self, *, level: int, x: int, y: int) -> Tuple[Path, Path]:
        dataset_slug = Path(self.dataset_root).name if self.dataset_root else "unknown_dataset"
        base = Path(self.repo_root) / "artifacts" / "tmp_genzoom" / dataset_slug
        base.mkdir(parents=True, exist_ok=True)
        suffix = f"{level}_{x}_{y}_{os.getpid()}_{random.randint(1000,9999)}"
        return base / f"ctx_{suffix}.png", base / f"mask_{suffix}.png"

    def _build_center_tile(self, level: int, x: int, y: int) -> Image.Image:
        # Start from upscaled parent quadrant.
        base = self._approx_tile_from_parent(level, x, y)
        if base is None:
            return Image.new("RGB", (self.tile_size, self.tile_size), color=(0, 0, 0))

        # Optional: preserve a border ring by copying edge strips from existing neighbors (if present).
        if self.canvas_spec.inpaint_region != "interior_only":
            return base

        ts = self.tile_size
        br = self.canvas_spec.border_ring_px

        left_tile = self._load_tile_rgb(level, x - 1, y) if x > 0 else None
        top_tile = self._load_tile_rgb(level, x, y - 1) if y > 0 else None
        tl_tile = self._load_tile_rgb(level, x - 1, y - 1) if x > 0 and y > 0 else None

        if left_tile is not None:
            if left_tile.size != (ts, ts):
                left_tile = left_tile.resize((ts, ts), Image.Resampling.LANCZOS)
            base.paste(left_tile.crop((ts - br, 0, ts, ts)), (0, 0))

        if top_tile is not None:
            if top_tile.size != (ts, ts):
                top_tile = top_tile.resize((ts, ts), Image.Resampling.LANCZOS)
            base.paste(top_tile.crop((0, ts - br, ts, ts)), (0, 0))

        if tl_tile is not None:
            if tl_tile.size != (ts, ts):
                tl_tile = tl_tile.resize((ts, ts), Image.Resampling.LANCZOS)
            base.paste(tl_tile.crop((ts - br, ts - br, ts, ts)), (0, 0))

        return base

    def _build_canvas_and_mask(self, level: int, x: int, y: int, center_tile: Image.Image) -> Tuple[Image.Image, Image.Image]:
        ts = self.tile_size
        pad = self.canvas_spec.pad_px
        canvas_size = ts + 2 * pad

        canvas = Image.new("RGB", (canvas_size, canvas_size), color=(0, 0, 0))
        inpaint_a = int(self.canvas_spec.inpaint_alpha)
        keep_a = 255 if inpaint_a == 0 else 0
        mask = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, keep_a))

        win_left_px = x * ts - pad
        win_top_px = y * ts - pad
        limit = (1 << int(level)) - 1

        min_tx = max(0, int(win_left_px // ts))
        max_tx = min(limit, int((win_left_px + canvas_size - 1) // ts))
        min_ty = max(0, int(win_top_px // ts))
        max_ty = min(limit, int((win_top_px + canvas_size - 1) // ts))

        for ty in range(min_ty, max_ty + 1):
            for tx in range(min_tx, max_tx + 1):
                if tx == x and ty == y:
                    continue

                img = None
                if self.canvas_spec.fill_strategy in ("neighbors_only", "neighbors_or_parent"):
                    img = self._load_tile_rgb(level, tx, ty)

                if img is None and self.canvas_spec.fill_strategy in ("neighbors_or_parent", "parent_only"):
                    img = self._approx_tile_from_parent(level, tx, ty)

                if img is None:
                    continue

                if img.size != (ts, ts):
                    img = img.resize((ts, ts), Image.Resampling.LANCZOS)
                paste_x = tx * ts - win_left_px
                paste_y = ty * ts - win_top_px
                canvas.paste(img, (int(paste_x), int(paste_y)))

        canvas.paste(center_tile, (pad, pad))

        draw = ImageDraw.Draw(mask)
        if self.canvas_spec.inpaint_region == "full_tile":
            rect = [pad, pad, pad + ts, pad + ts]
        else:
            br = self.canvas_spec.border_ring_px
            rect = [pad + br, pad + br, pad + ts - br, pad + ts - br]
        # Mask uses alpha channel; fill rectangle is the inpaint region.
        draw.rectangle(rect, fill=(0, 0, 0, inpaint_a))

        if self.canvas_spec.mask_blur_px > 0:
            mask = mask.filter(ImageFilter.GaussianBlur(radius=self.canvas_spec.mask_blur_px))

        return canvas, mask

    def render(self, level, x, y):
        level = int(level)
        x = int(x)
        y = int(y)
        ts = self.tile_size

        if level == 0:
            wf = json.loads(json.dumps(self.wf_t2i))
            b = self.bindings_t2i
            self._set_input(wf, b.prompt, self.prompt_t2i)
            self._set_sampler_param(wf, node_id=b.sampler_node, key=b.seed_key, value=random.randint(1, 10**14))
            if self.steps_t2i is not None:
                self._set_sampler_param(wf, node_id=b.sampler_node, key=b.steps_key, value=int(self.steps_t2i))
            if self.cfg_t2i is not None:
                self._set_sampler_param(wf, node_id=b.sampler_node, key=b.cfg_key, value=float(self.cfg_t2i))
            self._apply_model_overrides(wf, b)

            prompt_id = self.client.queue_prompt(wf)
            self.client.wait_for_prompt(prompt_id, timeout_s=self.prompt_timeout_s)
            history = self.client.get_history(prompt_id)
            data = history.get(prompt_id, {})
            img_ref = first_image_ref_from_history(data, preferred_node=b.save_node)
            if not img_ref:
                raise RuntimeError(f"No image returned for prompt {prompt_id}")
            raw = self.client.get_image_data(img_ref)
            img = Image.open(io.BytesIO(raw)).convert("RGB")
            if img.size != (ts, ts):
                img = img.resize((ts, ts), Image.Resampling.LANCZOS)
            return img

        center_tile = self._build_center_tile(level, x, y)
        canvas_img, mask_img = self._build_canvas_and_mask(level, x, y, center_tile)

        ctx_path, mask_path = self._make_temp_paths(level=level, x=x, y=y)
        try:
            canvas_img.save(ctx_path)
            mask_img.save(mask_path)

            if self.debug_dir:
                debug_dir = Path(self.debug_dir)
                debug_dir.mkdir(parents=True, exist_ok=True)
                ts_ = int(time.time())
                canvas_img.save(debug_dir / f"context_{level}_{x}_{y}_{ts_}.png")
                mask_img.save(debug_dir / f"mask_{level}_{x}_{y}_{ts_}.png")

            out = self._run_workflow_img2img(self.wf_i2i, ctx_path=ctx_path, mask_path=mask_path)
            if out.size != (ts, ts):
                out = out.resize((ts, ts), Image.Resampling.LANCZOS)
            return out
        finally:
            for p in (ctx_path, mask_path):
                try:
                    if p.exists():
                        p.unlink()
                except Exception:
                    pass
