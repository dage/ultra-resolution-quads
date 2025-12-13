import argparse
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.comfyui_client import ComfyUIClient, ComfyUIError, first_image_ref_from_history

def load_workflow(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def configure_workflow(workflow: Dict[str, Any], *, prompt: str, seed: int) -> None:
    # Set positive prompt (Node 6)
    workflow["6"]["inputs"]["text"] = prompt
    # Set seed (Node 3)
    workflow["3"]["inputs"]["seed"] = seed

async def analyze_result(image_path: Path, prompt: str, model: str) -> str:
    from backend.tools.analyze_image import analyze_images
    
    analysis_prompt = (
        f"Describe this image in detail and evaluate if it matches the user prompt: '{prompt}'. "
        "Provide a score from 1 to 10 on how well it matches the prompt."
    )
    return await analyze_images([str(image_path)], analysis_prompt, model=model)

def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="ComfyUI z-image turbo text-to-image generator.")
    parser.add_argument("prompt", help="Text prompt for generation")
    parser.add_argument("--server", default=os.environ.get("COMFYUI_SERVER", "127.0.0.1:8000"))
    parser.add_argument("--seed", type=int, default=0, help="Seed (0 => random)")
    parser.add_argument("--timeout", type=float, default=300.0, help="Timeout seconds for generation")
    parser.add_argument("--save-node", default="9", help="Preferred SaveImage node id in workflow (default: 9)")
    parser.add_argument(
        "--ai-analyze",
        action="store_true",
        help="Run backend/tools/analyze_image.py analysis (requires OPENROUTER_API_KEY).",
    )
    parser.add_argument("--ai-model", default="qwen/qwen3-vl-8b-instruct", help="OpenRouter model slug for --ai-analyze")

    args = parser.parse_args()
    seed = args.seed if args.seed != 0 else random.randint(1, 10_000_000_000)

    here = Path(__file__).resolve()
    workflow_path = here.with_name("z_image_turbo_t2i_workflow.json")
    out_dir = REPO_ROOT / "artifacts" / "z_image_turbo_t2i"
    out_dir.mkdir(parents=True, exist_ok=True)

    workflow = load_workflow(workflow_path)
    configure_workflow(workflow, prompt=args.prompt, seed=seed)

    client_id = f"z-image-turbo-{os.getpid()}-{random.randint(1000, 9999)}"
    client = None
    try:
        client = ComfyUIClient(str(args.server), client_id)
        
        print(f"Queuing workflow (seed={seed}) with prompt: '{args.prompt}' ...")
        prompt_id = client.queue_prompt(workflow)

        print("Waiting for generation ...")
        client.wait_for_prompt(prompt_id, timeout_s=float(args.timeout))

        history = client.get_history(prompt_id)
        history_for_prompt = history.get(prompt_id) or {}
        image_ref = first_image_ref_from_history(history_for_prompt, preferred_node=str(args.save_node))
        if not image_ref:
            raise RuntimeError(f"No images found in ComfyUI history for prompt_id={prompt_id}")

        print(f"Downloading {image_ref.filename} ...")
        raw = client.get_image_data(image_ref)
        output_filename = f"t2i_{seed}_{int(time.time())}.png"
        output_path = out_dir / output_filename
        output_path.write_bytes(raw)
        print(f"Saved to: {output_path}")

        if args.ai_analyze:
            if not os.environ.get("OPENROUTER_API_KEY"):
                print("Skipping --ai-analyze: OPENROUTER_API_KEY not set.", file=sys.stderr)
            else:
                import asyncio
                print("Running AI analysis ...")
                report = asyncio.run(analyze_result(output_path, args.prompt, str(args.ai_model)))
                print("\n--- AI Analysis ---")
                print(report)
                print("-------------------")
                
                # Save analysis to a text file
                analysis_path = output_path.with_suffix(".txt")
                analysis_path.write_text(report, encoding="utf-8")
                print(f"Analysis saved to: {analysis_path}")

        return 0
    except ComfyUIError as e:
        print(str(e), file=sys.stderr)
        return 2
    except requests.RequestException as e:
        print(f"HTTP error talking to ComfyUI at {args.server}: {e}", file=sys.stderr)
        return 2
    except ModuleNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 2
    except OSError as e:
        print(f"Connection error talking to ComfyUI at {args.server}: {e}", file=sys.stderr)
        return 2
    finally:
        if client:
            client.close()

if __name__ == "__main__":
    raise SystemExit(main())
