import argparse
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.comfyui_client import ComfyUIClient, ComfyUIError, first_image_ref_from_history  # noqa: E402


def load_workflow(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def set_if_present(workflow: Dict[str, Any], node_id: str, key: str, value: Any) -> None:
    if node_id not in workflow:
        raise KeyError(f"Workflow missing node id {node_id!r}")
    inputs = workflow[node_id].get("inputs")
    if not isinstance(inputs, dict):
        raise TypeError(f"Node {node_id!r} has no inputs dict")
    inputs[key] = value


def iter_model_filenames(workflow: Dict[str, Any]) -> Dict[str, str]:
    found: Dict[str, str] = {}
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for k, v in inputs.items():
            if not (isinstance(k, str) and k.endswith("_name")):
                continue
            if not isinstance(v, str):
                continue
            if "." not in v:
                continue
            found[f"{node_id}.{k}"] = v
    return found


def find_file(filename: str, base_dir: Path) -> Optional[Path]:
    if (base_dir / filename).exists():
        return base_dir / filename
    models_dir = base_dir / "models"
    search_roots = [models_dir] if models_dir.exists() else [base_dir]
    for root in search_roots:
        try:
            for p in root.rglob(filename):
                return p
        except Exception:
            continue
    return None


def preflight_check_models(workflow: Dict[str, Any], base_dir: Optional[Path]) -> None:
    models = iter_model_filenames(workflow)
    if not models:
        return
    if base_dir is None:
        raise SystemExit(
            "Preflight failed: workflow references model filenames but no base directory provided. "
            "Pass --preflight-base-dir or set COMFYUI_BASE_DIR."
        )
    missing = []
    for where, filename in models.items():
        if find_file(filename, base_dir) is None:
            missing.append((where, filename))
    if missing:
        lines = ["Preflight failed: some model files were not found:"]
        for where, filename in missing:
            lines.append(f"- {where}: {filename}")
        lines.append(f"Searched under: {base_dir}")
        raise SystemExit("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a ComfyUI workflow via HTTP+WebSocket and download the first image.")
    parser.add_argument("--server", default=os.environ.get("COMFYUI_SERVER", "127.0.0.1:8188"))
    parser.add_argument("--workflow", required=True, help="Path to a ComfyUI API workflow JSON")
    parser.add_argument("--timeout", type=float, default=3600.0, help="Timeout seconds for generation")

    parser.add_argument("--input-image", default=None, help="Optional: upload an input image and inject into a LoadImage node")
    parser.add_argument("--load-node", default="17", help="Node id for LoadImage (default: 17)")
    parser.add_argument("--load-key", default="image", help="Input key on the LoadImage node (default: image)")

    parser.add_argument("--prompt", default=None, help="Optional: set prompt text on a CLIPTextEncode node")
    parser.add_argument("--prompt-node", default="6", help="Node id for prompt text (default: 6)")
    parser.add_argument("--prompt-key", default="text", help="Input key for prompt text (default: text)")

    parser.add_argument("--seed", type=int, default=0, help="Seed (0 => random) injected into --seed-node")
    parser.add_argument("--seed-node", default="3", help="Node id for seed (default: 3)")
    parser.add_argument("--seed-key", default="seed", help="Input key for seed (default: seed)")

    parser.add_argument("--save-node", default="9", help="Preferred output node id to read from history (default: 9)")
    parser.add_argument("--output", default="comfyui_output.png", help="Output file path for the downloaded image")

    parser.add_argument(
        "--preflight-base-dir",
        default=os.environ.get("COMFYUI_BASE_DIR"),
        help="Optional: base directory to search for model files referenced by *_name fields (or set COMFYUI_BASE_DIR).",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Only run the preflight model-file check and exit (does not contact ComfyUI).",
    )

    args = parser.parse_args()

    workflow_path = Path(args.workflow).expanduser()
    if not workflow_path.exists():
        raise SystemExit(f"Workflow not found: {workflow_path}")
    workflow = load_workflow(workflow_path)

    base_dir = Path(args.preflight_base_dir).expanduser() if args.preflight_base_dir else None
    if args.preflight_only:
        preflight_check_models(workflow, base_dir)
        print("Preflight OK: model filenames found on disk.")
        return 0

    seed = args.seed if args.seed != 0 else random.randint(1, 10_000_000_000)
    if args.seed_node:
        set_if_present(workflow, args.seed_node, args.seed_key, seed)

    client_id = f"run-workflow-{os.getpid()}-{random.randint(1000, 9999)}"
    client: Optional[ComfyUIClient] = None
    try:
        client = ComfyUIClient(str(args.server), client_id)

        if args.input_image:
            input_path = Path(args.input_image).expanduser()
            if not input_path.exists():
                raise SystemExit(f"Input image not found: {input_path}")
            comfy_name = client.upload_image(input_path)
            set_if_present(workflow, args.load_node, args.load_key, comfy_name)

        if args.prompt is not None:
            set_if_present(workflow, args.prompt_node, args.prompt_key, args.prompt)

        t0 = time.perf_counter()
        prompt_id = client.queue_prompt(workflow)
        client.wait_for_prompt(prompt_id, timeout_s=float(args.timeout))
        dt = time.perf_counter() - t0

        history = client.get_history(prompt_id)
        history_for_prompt = history.get(prompt_id) or {}
        image_ref = first_image_ref_from_history(history_for_prompt, preferred_node=str(args.save_node))
        if not image_ref:
            raise RuntimeError(f"No images found in ComfyUI history for prompt_id={prompt_id}")

        raw = client.get_image_data(image_ref)
        out_path = Path(args.output).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(raw)

        print(json.dumps({"prompt_id": prompt_id, "seed": seed, "seconds": dt, "output": str(out_path)}, indent=2))
        return 0
    except ComfyUIError as e:
        print(str(e), file=sys.stderr)
        return 2
    finally:
        if client:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
