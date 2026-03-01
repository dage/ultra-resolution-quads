from __future__ import annotations

import io
import json
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]

import sys

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.comfyui_client import ComfyUIClient, first_image_ref_from_history  # noqa: E402


@dataclass(frozen=True)
class NodeRef:
    node: str
    key: str


@dataclass(frozen=True)
class Bindings:
    # Common
    save_node: str
    prompt: NodeRef
    sampler_node: str
    seed_key: Optional[str]
    denoise_key: Optional[str]
    steps_key: Optional[str]
    cfg_key: Optional[str]

    # Only for i2i/inpaint
    ctx_image: Optional[NodeRef] = None
    mask_image: Optional[NodeRef] = None

    # Optional model override nodes
    unet: Optional[NodeRef] = None
    clip: Optional[NodeRef] = None
    vae: Optional[NodeRef] = None


def load_workflow(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    if not p.is_absolute():
        p = (REPO_ROOT / p).resolve()
    return json.loads(p.read_text(encoding="utf-8"))


def load_bindings(bindings_path: str | Path, *, kind: str) -> Bindings:
    """
    Bindings schema matches `workflow_bindings_default.json`.

    kind: "t2i" or "i2i"
    """
    p = Path(bindings_path)
    if not p.is_absolute():
        p = (REPO_ROOT / p).resolve()
    data = json.loads(p.read_text(encoding="utf-8"))
    d = data.get(kind) or {}
    sampler = d.get("sampler") or {}
    model = d.get("model") or {}

    def nr(obj: Any) -> NodeRef:
        return NodeRef(str(obj["node"]), str(obj["key"]))

    ctx_images = d.get("ctx_images") or []
    mask_images = d.get("mask_images") or []
    ctx = nr(ctx_images[0]) if ctx_images else None
    mask = nr(mask_images[0]) if mask_images else None

    return Bindings(
        save_node=str(d.get("save_node", "9")),
        prompt=nr(d["prompt"]),
        sampler_node=str(sampler.get("node", "3")),
        seed_key=(str(sampler["seed"]) if sampler.get("seed") else None),
        denoise_key=(str(sampler["denoise"]) if sampler.get("denoise") else None),
        steps_key=(str(sampler["steps"]) if sampler.get("steps") else None),
        cfg_key=(str(sampler["cfg"]) if sampler.get("cfg") else None),
        ctx_image=ctx,
        mask_image=mask,
        unet=(nr(model["unet"]) if model.get("unet") else None),
        clip=(nr(model["clip"]) if model.get("clip") else None),
        vae=(nr(model["vae"]) if model.get("vae") else None),
    )


def _set_input(wf: Dict[str, Any], ref: NodeRef, value: Any) -> None:
    node = wf.get(ref.node)
    if not isinstance(node, dict):
        raise KeyError(f"Workflow node '{ref.node}' not found")
    inputs = node.get("inputs")
    if not isinstance(inputs, dict):
        raise KeyError(f"Workflow node '{ref.node}' missing 'inputs'")
    inputs[ref.key] = value


def _set_sampler_param(wf: Dict[str, Any], *, node_id: str, key: Optional[str], value: Any) -> None:
    if not key:
        return
    node = wf.get(node_id)
    if not isinstance(node, dict):
        raise KeyError(f"Workflow sampler node '{node_id}' not found")
    inputs = node.get("inputs")
    if not isinstance(inputs, dict):
        raise KeyError(f"Workflow sampler node '{node_id}' missing 'inputs'")
    inputs[key] = value


def _apply_model_overrides(wf: Dict[str, Any], b: Bindings, *, unet: Optional[str], clip: Optional[str], vae: Optional[str]) -> None:
    if unet:
        if not b.unet:
            raise ValueError("unet override provided but bindings.model.unet is not configured")
        _set_input(wf, b.unet, unet)
    if clip:
        if not b.clip:
            raise ValueError("clip override provided but bindings.model.clip is not configured")
        _set_input(wf, b.clip, clip)
    if vae:
        if not b.vae:
            raise ValueError("vae override provided but bindings.model.vae is not configured")
        _set_input(wf, b.vae, vae)


def run_t2i(
    *,
    server: str,
    workflow: Dict[str, Any],
    bindings: Bindings,
    prompt: str,
    seed: Optional[int] = None,
    steps: Optional[int] = None,
    cfg: Optional[float] = None,
    unet: Optional[str] = None,
    clip: Optional[str] = None,
    vae: Optional[str] = None,
    mock: bool = False,
    timeout_s: float = 1200,
) -> Image.Image:
    wf = json.loads(json.dumps(workflow))

    _set_input(wf, bindings.prompt, prompt)
    _set_sampler_param(wf, node_id=bindings.sampler_node, key=bindings.seed_key, value=int(seed if seed is not None else random.randint(1, 10**14)))
    if steps is not None:
        _set_sampler_param(wf, node_id=bindings.sampler_node, key=bindings.steps_key, value=int(steps))
    if cfg is not None:
        _set_sampler_param(wf, node_id=bindings.sampler_node, key=bindings.cfg_key, value=float(cfg))
    _apply_model_overrides(wf, bindings, unet=unet, clip=clip, vae=vae)

    client = (_MockComfyUIClient(server) if mock else ComfyUIClient(server, f"iterate-t2i-{os.getpid()}-{random.randint(1000,9999)}"))
    try:
        prompt_id = client.queue_prompt(wf)
        client.wait_for_prompt(prompt_id, timeout_s=timeout_s)
        hist = client.get_history(prompt_id)
        data = hist.get(prompt_id, {})
        img_ref = first_image_ref_from_history(data, preferred_node=bindings.save_node)
        if not img_ref:
            raise RuntimeError(f"No image returned for prompt {prompt_id}")
        raw = client.get_image_data(img_ref)
        return Image.open(io.BytesIO(raw)).convert("RGB")
    finally:
        try:
            client.close()
        except Exception:
            pass


def run_i2i(
    *,
    server: str,
    workflow: Dict[str, Any],
    bindings: Bindings,
    ctx_path: Path,
    mask_path: Path,
    prompt: str,
    seed: Optional[int] = None,
    denoise: Optional[float] = None,
    steps: Optional[int] = None,
    cfg: Optional[float] = None,
    unet: Optional[str] = None,
    clip: Optional[str] = None,
    vae: Optional[str] = None,
    mock: bool = False,
    timeout_s: float = 1200,
) -> Image.Image:
    if not bindings.ctx_image or not bindings.mask_image:
        raise ValueError("i2i bindings must define ctx_images[0] and mask_images[0]")

    wf = json.loads(json.dumps(workflow))

    client = (_MockComfyUIClient(server) if mock else ComfyUIClient(server, f"iterate-i2i-{os.getpid()}-{random.randint(1000,9999)}"))
    try:
        ctx_name = client.upload_image(ctx_path)
        mask_name = client.upload_image(mask_path)
        _set_input(wf, bindings.ctx_image, ctx_name)
        _set_input(wf, bindings.mask_image, mask_name)

        _set_input(wf, bindings.prompt, prompt)
        _set_sampler_param(wf, node_id=bindings.sampler_node, key=bindings.seed_key, value=int(seed if seed is not None else random.randint(1, 10**14)))
        if denoise is not None:
            _set_sampler_param(wf, node_id=bindings.sampler_node, key=bindings.denoise_key, value=float(denoise))
        if steps is not None:
            _set_sampler_param(wf, node_id=bindings.sampler_node, key=bindings.steps_key, value=int(steps))
        if cfg is not None:
            _set_sampler_param(wf, node_id=bindings.sampler_node, key=bindings.cfg_key, value=float(cfg))
        _apply_model_overrides(wf, bindings, unet=unet, clip=clip, vae=vae)

        prompt_id = client.queue_prompt(wf)
        client.wait_for_prompt(prompt_id, timeout_s=timeout_s)
        hist = client.get_history(prompt_id)
        data = hist.get(prompt_id, {})
        img_ref = first_image_ref_from_history(data, preferred_node=bindings.save_node)
        if not img_ref:
            raise RuntimeError(f"No image returned for prompt {prompt_id}")
        raw = client.get_image_data(img_ref)
        return Image.open(io.BytesIO(raw)).convert("RGB")
    finally:
        try:
            client.close()
        except Exception:
            pass


def run_dir(*, kind: str) -> Path:
    ts = time.strftime("%Y%m%d_%H%M%S")
    base = REPO_ROOT / "artifacts" / "iterate_t2i" / kind / ts
    base.mkdir(parents=True, exist_ok=True)
    return base


class _MockComfyUIClient:
    """
    Minimal in-process stand-in for ComfyUIClient for smoke-testing scripts without a live server.

    - T2I: returns a deterministic gradient image.
    - I2I/inpaint: returns the center crop of the uploaded context canvas (assumes square).
    """

    def __init__(self, server_address: str):  # noqa: ARG002
        self._uploads: Dict[str, Path] = {}
        self._last_workflow: Optional[Dict[str, Any]] = None
        self._last_prompt_id = "mock_prompt_id"

    def close(self) -> None:
        return

    def upload_image(self, filepath: Path, *, overwrite: bool = True) -> str:  # noqa: ARG002
        name = filepath.name
        self._uploads[name] = Path(filepath)
        return name

    def queue_prompt(self, workflow: Dict[str, Any]) -> str:
        self._last_workflow = json.loads(json.dumps(workflow))
        return self._last_prompt_id

    def wait_for_prompt(self, prompt_id: str, timeout_s: float) -> None:  # noqa: ARG002
        return

    def get_history(self, prompt_id: str) -> Dict[str, Any]:  # noqa: ARG002
        return {
            self._last_prompt_id: {
                "outputs": {
                    "9": {"images": [{"filename": "mock_out.png", "subfolder": "", "type": "output"}]},
                }
            }
        }

    def _guess_tile_size(self, w: int, h: int) -> int:
        n = min(w, h)
        p = 1
        while p * 2 <= n:
            p *= 2
        return p

    def get_image_data(self, image_ref) -> bytes:  # noqa: ANN001
        wf = self._last_workflow or {}

        # If a context image exists (node "100" by convention), return its center crop.
        ctx_name = None
        node100 = wf.get("100") if isinstance(wf, dict) else None
        if isinstance(node100, dict):
            inputs = node100.get("inputs") or {}
            if isinstance(inputs, dict):
                ctx_name = inputs.get("image")

        if isinstance(ctx_name, str) and ctx_name in self._uploads and self._uploads[ctx_name].exists():
            ctx = Image.open(self._uploads[ctx_name]).convert("RGB")
            ts = self._guess_tile_size(*ctx.size)
            pad = max(0, (ctx.size[0] - ts) // 2)
            out = ctx.crop((pad, pad, pad + ts, pad + ts))
        else:
            # Deterministic gradient
            out = Image.new("RGB", (1024, 1024))
            px = out.load()
            for y in range(1024):
                for x in range(1024):
                    r = int(255 * x / 1023)
                    g = int(255 * y / 1023)
                    b = int(255 * (x ^ y) / 1023)
                    px[x, y] = (r, g, b)

        buf = io.BytesIO()
        out.save(buf, format="PNG")
        return buf.getvalue()
