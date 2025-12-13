import argparse
import html
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests
import numpy as np
from PIL import Image
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.comfyui_client import ComfyUIClient, ComfyUIError, first_image_ref_from_history  # noqa: E402

DEFAULT_PROMPT = (
    "Make the image ultrasharp by adding only tiny missing micro-details (1–2 pixels) where it's blurred. "
    "Do NOT remove, alter, replace, repaint, or smooth any original details or edges. "
    "Do NOT introduce new shapes/structures. Do NOT shift/offset/warp the image. "
    "Only add subtle detail that helps the 2x upscaling look perfect."
)


def default_tile_path() -> Path:
    here = Path(__file__).resolve()
    repo_root = here.parents[1]
    candidate = repo_root / "datasets" / "glossy_seahorse" / "61" / "1106827755856937119" / "991051327647092164.webp"
    if candidate.exists():
        return candidate
    datasets = repo_root / "datasets"
    if datasets.exists():
        for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
            found = next(datasets.rglob(ext), None)
            if found:
                return found
    return candidate


def file_url(path: Path) -> str:
    return path.resolve().as_uri()


def load_workflow(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def configure_workflow(workflow: Dict[str, Any], *, comfy_image_name: str, prompt: str, seed: int) -> None:
    workflow["17"]["inputs"]["image"] = comfy_image_name
    workflow["6"]["inputs"]["text"] = prompt
    workflow["3"]["inputs"]["seed"] = seed


def set_denoise(workflow: Dict[str, Any], denoise: float) -> None:
    if "3" not in workflow or not isinstance(workflow["3"], dict):
        raise KeyError("Workflow missing node '3' (KSampler)")
    inputs = workflow["3"].get("inputs")
    if not isinstance(inputs, dict):
        raise KeyError("Workflow node '3' missing inputs dict")
    inputs["denoise"] = float(denoise)


def downscale_image(input_path: Path, out_path: Path, factor: float) -> Dict[str, Any]:
    with Image.open(input_path) as im:
        im = im.convert("RGB")
        orig_w, orig_h = im.size
        factor = float(factor)
        if factor <= 0:
            raise ValueError("--downscale-input must be > 0")
        new_w = max(1, int(round(orig_w * factor)))
        new_h = max(1, int(round(orig_h * factor)))
        im2 = im.resize((new_w, new_h), resample=Image.Resampling.LANCZOS)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        im2.save(out_path)
        return {"original": {"w": orig_w, "h": orig_h}, "processed": {"w": new_w, "h": new_h}, "factor": factor}


def bicubic_upscale_2x(input_path: Path, out_path: Path) -> Dict[str, Any]:
    with Image.open(input_path) as im:
        im = im.convert("RGB")
        w, h = im.size
        up = im.resize((w * 2, h * 2), resample=Image.Resampling.BICUBIC)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        up.save(out_path)
        return {"reference": {"w": w * 2, "h": h * 2}, "method": "bicubic", "scale": 2}


def _to_gray_float(im: Image.Image) -> np.ndarray:
    arr = np.asarray(im.convert("L"), dtype=np.float32)
    arr -= float(arr.mean())
    return arr


def estimate_translation_phase_correlation(a_gray: np.ndarray, b_gray: np.ndarray) -> Tuple[int, int, float]:
    # Returns (dx, dy) such that b rolled by (-dx, -dy) best matches a.
    if a_gray.shape != b_gray.shape:
        raise ValueError(f"phase_correlation requires same shapes, got {a_gray.shape} vs {b_gray.shape}")
    fa = np.fft.fft2(a_gray)
    fb = np.fft.fft2(b_gray)
    cps = fa * np.conj(fb)
    denom = np.maximum(np.abs(cps), 1e-8)
    cps = cps / denom
    corr = np.fft.ifft2(cps)
    corr_abs = np.abs(corr)
    peak_y, peak_x = np.unravel_index(np.argmax(corr_abs), corr_abs.shape)
    h, w = corr_abs.shape
    dx = int(peak_x) if peak_x <= w // 2 else int(peak_x - w)
    dy = int(peak_y) if peak_y <= h // 2 else int(peak_y - h)
    peak = float(corr_abs[peak_y, peak_x])
    return dx, dy, peak


def crop_valid(a: np.ndarray, b: np.ndarray, dx: int, dy: int) -> Tuple[np.ndarray, np.ndarray]:
    # Crop arrays to exclude wrapped regions after shifting.
    h, w = a.shape[:2]
    x0 = max(0, dx)
    x1 = w + min(0, dx)
    y0 = max(0, dy)
    y1 = h + min(0, dy)
    return a[y0:y1, x0:x1], b[y0:y1, x0:x1]


def laplacian_std(gray: np.ndarray) -> float:
    # 3x3 laplacian kernel: [[0,1,0],[1,-4,1],[0,1,0]]
    g = gray.astype(np.float32)
    p = np.pad(g, ((1, 1), (1, 1)), mode="edge")
    lap = (p[0:-2, 1:-1] + p[2:, 1:-1] + p[1:-1, 0:-2] + p[1:-1, 2:] - 4.0 * p[1:-1, 1:-1])
    return float(lap.std())


def compute_similarity_metrics(reference_path: Path, output_path: Path) -> Dict[str, Any]:
    with Image.open(reference_path) as ref_im, Image.open(output_path) as out_im:
        ref_im = ref_im.convert("RGB")
        out_im = out_im.convert("RGB")
        if ref_im.size != out_im.size:
            # If ComfyUI output differs, compare at min-size by resizing output to reference.
            out_im = out_im.resize(ref_im.size, resample=Image.Resampling.BICUBIC)

        ref_gray = _to_gray_float(ref_im)
        out_gray = _to_gray_float(out_im)
        dx, dy, peak = estimate_translation_phase_correlation(ref_gray, out_gray)

        out_rgb = np.asarray(out_im, dtype=np.float32)
        ref_rgb = np.asarray(ref_im, dtype=np.float32)

        # Align output by shifting opposite direction, then crop valid region.
        out_aligned = np.roll(out_rgb, shift=(-dy, -dx), axis=(0, 1))
        ref_c, out_c = crop_valid(ref_rgb, out_aligned, dx, dy)

        diff = ref_c - out_c
        mse = float(np.mean(diff * diff))
        rmse = float(np.sqrt(mse))
        rms_similarity = float(max(0.0, 1.0 - (rmse / 255.0)))
        psnr = float("inf") if mse == 0 else float(20.0 * np.log10(255.0) - 10.0 * np.log10(mse))

        ref_flat = ref_c.reshape(-1, 3)
        out_flat = out_c.reshape(-1, 3)
        # Pearson correlation over luminance-like average.
        ref_l = ref_flat.mean(axis=1)
        out_l = out_flat.mean(axis=1)
        corr = float(np.corrcoef(ref_l, out_l)[0, 1]) if ref_l.size > 2 else 0.0

        ref_lap = laplacian_std(ref_gray)
        out_lap = laplacian_std(out_gray)
        detail_gain = float(out_lap / ref_lap) if ref_lap > 1e-6 else 0.0

        return {
            "alignment": {"dx": dx, "dy": dy, "phase_peak": peak},
            "similarity": {"rms_similarity": rms_similarity, "psnr": psnr, "luma_corr": corr},
            "detail": {"laplacian_std_reference": ref_lap, "laplacian_std_output": out_lap, "detail_gain": detail_gain},
            "notes": "reference is bicubic 2x; output is ComfyUI output; metrics computed after estimated translation alignment",
        }


async def ai_compare(reference_path: Path, output_path: Path, prompt: str, model: str) -> str:
    from backend.tools.analyze_image import analyze_images  # local tool; may require OPENROUTER_API_KEY

    compare_prompt = (
        "Compare the two images. The first is the bicubic 2x reference, the second is the ComfyUI output.\n"
        "Check for: (1) any removed/altered details, (2) added details, (3) any global shift/offset, "
        "(4) unwanted hallucinated structures.\n"
        f"User prompt used for generation: {prompt}\n"
        "Return a concise verdict and bullet list of issues if any."
    )
    return await analyze_images([str(reference_path), str(output_path)], compare_prompt, model=model)


def generate_html_report(
    *,
    reference_filename: str,
    output_filename: str,
    prompt: str,
    report_path: Path,
    seed: int,
    denoise: Optional[float],
    server_address: str,
    workflow_file: str,
    generation_time_s: Optional[float],
    comfyui_prompt_id: Optional[str],
    comfyui_output_filename: Optional[str],
    preprocessing: Dict[str, Any],
    similarity: Dict[str, Any],
    ai_report: Optional[str],
    meta_filename: str,
) -> None:
    title = f"Upscale Report: {reference_filename}"
    prompt_escaped = html.escape(prompt, quote=True)
    generation_time_text = "n/a" if generation_time_s is None else f"{generation_time_s:.3f}s"
    banner_text = "COMFYUI RUN: Output downloaded from ComfyUI after workflow execution."
    banner_bg = "#003a2c"

    preprocessing_text = html.escape(json.dumps(preprocessing, sort_keys=True), quote=True)
    similarity_pretty = json.dumps(similarity, indent=2, sort_keys=True)
    similarity_text = html.escape(similarity_pretty, quote=True)
    ai_text = html.escape((ai_report or "").strip(), quote=True)

    align = similarity.get("alignment") or {}
    sim = similarity.get("similarity") or {}
    detail = similarity.get("detail") or {}
    summary = (
        f"RMS similarity: {sim.get('rms_similarity', 'n/a')} | "
        f"Offset (dx,dy): ({align.get('dx','n/a')},{align.get('dy','n/a')}) | "
        f"Detail gain: {detail.get('detail_gain','n/a')}"
    )
    summary_text = html.escape(summary, quote=True)

    def _fmt(x: Any) -> str:
        if x is None:
            return "n/a"
        if isinstance(x, float):
            return f"{x:.4f}"
        return str(x)

    dx = align.get("dx")
    dy = align.get("dy")
    phase_peak = align.get("phase_peak")
    rms_sim = sim.get("rms_similarity")
    psnr = sim.get("psnr")
    luma_corr = sim.get("luma_corr")
    detail_gain = detail.get("detail_gain")
    similarity_table = f"""
    <table style="margin: 0 auto; border-collapse: collapse; font-size: 13px;">
      <tr><td style="padding:4px 8px; color: var(--muted);">Offset dx</td><td style="padding:4px 8px;">{html.escape(_fmt(dx))} px</td></tr>
      <tr><td style="padding:4px 8px; color: var(--muted);">Offset dy</td><td style="padding:4px 8px;">{html.escape(_fmt(dy))} px</td></tr>
      <tr><td style="padding:4px 8px; color: var(--muted);">Phase peak</td><td style="padding:4px 8px;">{html.escape(_fmt(phase_peak))}</td></tr>
      <tr><td style="padding:4px 8px; color: var(--muted);">RMS similarity</td><td style="padding:4px 8px;">{html.escape(_fmt(rms_sim))}</td></tr>
      <tr><td style="padding:4px 8px; color: var(--muted);">PSNR</td><td style="padding:4px 8px;">{html.escape(_fmt(psnr))} dB</td></tr>
      <tr><td style="padding:4px 8px; color: var(--muted);">Luma corr</td><td style="padding:4px 8px;">{html.escape(_fmt(luma_corr))}</td></tr>
      <tr><td style="padding:4px 8px; color: var(--muted);">Detail gain</td><td style="padding:4px 8px;">{html.escape(_fmt(detail_gain))}</td></tr>
    </table>
    """

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(title, quote=True)}</title>
  <style>
    :root {{
      --bg: #111;
      --panel: #1c1c1c;
      --border: #333;
      --text: #eee;
      --muted: #aaa;
      --accent: #00ffcc;
      --warn: #ffcc00;
    }}
    body {{
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      margin: 0;
      padding: 18px;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 10px;
    }}
    .banner {{
      width: min(1100px, 96vw);
      border-radius: 10px;
      padding: 10px 12px;
      border: 1px solid #2f2f2f;
      background: {banner_bg};
      color: #fff;
      font-size: 13px;
      font-weight: 600;
      letter-spacing: 0.02em;
    }}
    .controls {{
      width: min(1100px, 96vw);
      background: var(--panel);
      padding: 10px 12px;
      border: 1px solid var(--border);
      border-radius: 10px;
      display: flex;
      flex-wrap: wrap;
      gap: 12px 16px;
      align-items: center;
      justify-content: space-between;
    }}
    .controls-left {{
      display: flex;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
    }}
    label {{
      color: var(--muted);
      font-size: 14px;
      margin-right: 6px;
    }}
    select, button {{
      padding: 6px 10px;
      background: #222;
      color: var(--text);
      border: 1px solid #444;
      border-radius: 8px;
      font-size: 14px;
    }}
    button:hover {{ border-color: #666; }}
    .viewport {{
      width: min(1100px, 96vw);
      height: min(1100px, 80vh);
      border: 2px solid #444;
      border-radius: 12px;
      overflow: hidden;
      position: relative;
      cursor: grab;
      background: #000;
      user-select: none;
      touch-action: none;
    }}
    .viewport:active {{ cursor: grabbing; }}
    #displayImage {{
      transform-origin: 0 0;
      position: absolute;
      top: 0;
      left: 0;
      image-rendering: pixelated;
      -webkit-user-drag: none;
    }}
    .status-bar {{
      width: min(1100px, 96vw);
      font-size: 14px;
      letter-spacing: 0.06em;
      font-weight: 700;
      color: var(--accent);
      text-align: center;
    }}
    .info {{
      width: min(1100px, 96vw);
      color: var(--muted);
      font-size: 13px;
      text-align: center;
      line-height: 1.35;
      word-break: break-word;
    }}
    .mono {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, \"Liberation Mono\", \"Courier New\", monospace;
      font-size: 12px;
      white-space: pre-wrap;
    }}
  </style>
</head>
<body>
  <div class="banner">{html.escape(banner_text, quote=True)}</div>
  <div class="controls">
    <div class="controls-left">
      <div>
        <label for="zoomSelect">Zoom</label>
        <select id="zoomSelect">
          <option value="1">1x</option>
          <option value="2">2x</option>
          <option value="4">4x</option>
          <option value="8">8x</option>
          <option value="16">16x</option>
        </select>
      </div>
      <button id="resetBtn" type="button">Reset view</button>
    </div>
    <div style="color: var(--muted); font-size: 13px;">
      Click image to toggle Input/Output. Drag to pan.
    </div>
  </div>

  <div class="viewport" id="viewport">
    <img id="displayImage" src="{html.escape(output_filename, quote=True)}" draggable="false" alt="Upscale output">
  </div>

  <div class="status-bar" id="statusLabel">OUTPUT IMAGE</div>
  <div class="info">
    <div>
      <strong>Seed:</strong> {seed} &nbsp;
      <strong>Denoise:</strong> {html.escape("n/a" if denoise is None else f"{denoise:.3f}")} &nbsp;
      <strong>Server:</strong> {html.escape(server_address, quote=True)} &nbsp;
      <strong>Generation time:</strong> {generation_time_text}
    </div>
    <div>
      <strong>Workflow:</strong> {html.escape(workflow_file, quote=True)} &nbsp;
      <strong>Meta:</strong> {html.escape(meta_filename, quote=True)}
    </div>
    <div>
      <strong>ComfyUI prompt_id:</strong> {html.escape(comfyui_prompt_id or "n/a", quote=True)} &nbsp;
      <strong>ComfyUI output filename:</strong> {html.escape(comfyui_output_filename or "n/a", quote=True)}
    </div>
    <div><strong>Prompt:</strong> {prompt_escaped}</div>
    <div class="mono"><strong>Summary:</strong> {summary_text}</div>
    <div class="mono"><strong>Preprocess:</strong> {preprocessing_text}</div>
    <div class="mono"><strong>Similarity:</strong></div>
    {similarity_table}
    <details style="margin-top: 6px;">
      <summary style="cursor: pointer; color: var(--muted);">Show raw similarity JSON</summary>
      <pre class="mono" style="text-align:left; margin: 8px auto; max-width: min(1100px, 96vw);">{similarity_text}</pre>
    </details>
    <div class="mono" style="margin-top: 6px;"><strong>AI Compare:</strong></div>
    <pre class="mono" style="text-align:left; margin: 8px auto; max-width: min(1100px, 96vw);">{ai_text}</pre>
  </div>

  <script>
    const img = document.getElementById('displayImage');
    const viewport = document.getElementById('viewport');
    const statusLabel = document.getElementById('statusLabel');
    const zoomSelect = document.getElementById('zoomSelect');
    const resetBtn = document.getElementById('resetBtn');

    const srcReference = "{html.escape(reference_filename, quote=True)}";
    const srcOutput = "{html.escape(output_filename, quote=True)}";

    window.__UPSCALE_REPORT__ = {{
      seed: {seed},
      denoise: {("null" if denoise is None else f"{float(denoise):.6f}")},
      generationTimeSeconds: {("null" if generation_time_s is None else f"{generation_time_s:.6f}")},
      server: {json.dumps(server_address)},
      workflow: {json.dumps(workflow_file)},
      meta: {json.dumps(meta_filename)},
      comfyui: {{
        promptId: {("null" if comfyui_prompt_id is None else json.dumps(comfyui_prompt_id))},
        outputFilename: {("null" if comfyui_output_filename is None else json.dumps(comfyui_output_filename))},
      }},
      preprocessing: {json.dumps(preprocessing)},
      reference: srcReference,
      output: srcOutput,
      similarity: {json.dumps(similarity)},
      aiCompare: {("null" if ai_report is None else json.dumps(ai_report))},
      prompt: `{prompt_escaped}`,
    }};

    let mode = "output"; // "reference" | "output"
    let zoom = 1;
    let panX = 0; // screen px
    let panY = 0; // screen px

    let referenceNatural = null;
    let outputNatural = null;
    let pointerDown = false;
    let didDrag = false;
    let startClientX = 0;
    let startClientY = 0;
    let startPanX = 0;
    let startPanY = 0;
    const DRAG_THRESHOLD_PX = 3;

    function updateLabel() {{
      if (mode === "output") {{
        statusLabel.innerText = "OUTPUT IMAGE";
        statusLabel.style.color = "var(--accent)";
      }} else {{
        statusLabel.innerText = "REFERENCE (BICUBIC 2×)";
        statusLabel.style.color = "var(--warn)";
      }}
    }}

    function applyInputSizingIfReady() {{
      // Reference and output are same size; no sizing needed.
      return;
    }}

    function applyOutputSizing() {{
      img.style.width = "auto";
      img.style.height = "auto";
    }}

    function updateTransform() {{
      img.style.transform = `translate(${{panX}}px, ${{panY}}px) scale(${{zoom}})`;
    }}

    function resetView() {{
      zoom = 1;
      panX = 0;
      panY = 0;
      zoomSelect.value = "1";
      updateTransform();
    }}

    function setZoom(newZoom) {{
      zoom = Math.max(1, Math.min(16, newZoom));
      updateTransform();
    }}

    function toggleMode() {{
      mode = (mode === "output") ? "reference" : "output";
      img.src = (mode === "output") ? srcOutput : srcReference;
      updateLabel();
      if (mode === "output") {{
        applyOutputSizing();
      }} else {{
        applyInputSizingIfReady();
      }}
    }}

    function loadNaturalSizes() {{
      const refProbe = new Image();
      const outputProbe = new Image();

      refProbe.onload = () => {{
        referenceNatural = {{ w: refProbe.naturalWidth, h: refProbe.naturalHeight }};
      }};
      outputProbe.onload = () => {{
        outputNatural = {{ w: outputProbe.naturalWidth, h: outputProbe.naturalHeight }};
      }};

      refProbe.src = srcReference;
      outputProbe.src = srcOutput;
    }}

    zoomSelect.addEventListener('change', () => {{
      setZoom(parseFloat(zoomSelect.value));
    }});

    resetBtn.addEventListener('click', () => resetView());

    viewport.addEventListener('pointerdown', (e) => {{
      pointerDown = true;
      didDrag = false;
      startClientX = e.clientX;
      startClientY = e.clientY;
      startPanX = panX;
      startPanY = panY;
      viewport.setPointerCapture(e.pointerId);
    }});

    viewport.addEventListener('pointermove', (e) => {{
      if (!pointerDown) return;
      const dx = e.clientX - startClientX;
      const dy = e.clientY - startClientY;
      if (!didDrag && (Math.abs(dx) > DRAG_THRESHOLD_PX || Math.abs(dy) > DRAG_THRESHOLD_PX)) {{
        didDrag = true;
      }}
      if (didDrag) {{
        panX = startPanX + dx;
        panY = startPanY + dy;
        updateTransform();
      }}
    }});

    viewport.addEventListener('pointerup', (e) => {{
      pointerDown = false;
      viewport.releasePointerCapture(e.pointerId);
    }});

    viewport.addEventListener('click', (e) => {{
      if (didDrag) return;
      toggleMode();
    }});

    updateLabel();
    resetView();
    loadNaturalSizes();
  </script>
</body>
</html>
"""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(html_content, encoding="utf-8")


def regen_html_only(*, out_dir: Path, seed: int, workflow_file: str, server: str) -> None:
    meta_path = out_dir / f"meta_{seed}.json"
    if not meta_path.exists():
        raise SystemExit(f"Missing meta file: {meta_path}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    ref_path = out_dir / f"reference_{seed}.png"
    if not ref_path.exists():
        raise SystemExit(f"Missing reference image: {ref_path}")
    output_path = out_dir / f"upscaled_{seed}.png"
    if not output_path.exists():
        raise SystemExit(f"Missing output image: {output_path}")

    similarity = compute_similarity_metrics(ref_path, output_path)

    report_path = out_dir / f"report_{seed}.html"
    generate_html_report(
        reference_filename=ref_path.name,
        output_filename=output_path.name,
        prompt=str(meta.get("prompt", "")),
        report_path=report_path,
        seed=seed,
        denoise=meta.get("denoise"),
        server_address=server,
        workflow_file=workflow_file,
        generation_time_s=meta.get("generation_time_s"),
        comfyui_prompt_id=meta.get("comfyui_prompt_id"),
        comfyui_output_filename=meta.get("comfyui_output_filename"),
        preprocessing=meta.get("preprocessing") or {},
        similarity=similarity,
        ai_report=meta.get("ai_compare"),
        meta_filename=meta_path.name,
    )
    print(f"Report regenerated: {report_path}")


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="ComfyUI hallucination test runner for a fixed workflow.")
    parser.add_argument(
        "input_image",
        nargs="?",
        default=str(default_tile_path()),
        help="Path to input image (default: top tile from datasets/glossy_seahorse)",
    )
    parser.add_argument("prompt", nargs="?", default=DEFAULT_PROMPT, help="Prompt for node 6")

    parser.add_argument("--server", default=os.environ.get("COMFYUI_SERVER", "127.0.0.1:8188"))
    parser.add_argument("--seed", type=int, default=0, help="Seed (0 => random)")
    parser.add_argument("--timeout", type=float, default=3600.0, help="Timeout seconds for generation")
    parser.add_argument("--no-open", action="store_true", help="Do not open the report in a browser")
    parser.add_argument("--save-node", default="9", help="Preferred SaveImage node id in workflow (default: 9)")
    parser.add_argument("--denoise", type=float, default=None, help="Override KSampler denoise (node 3). Example: 0.15")

    parser.add_argument(
        "--downscale-input",
        type=float,
        default=0.5,
        help="Preprocess: downscale input by this factor before upload (default: 0.5).",
    )
    parser.add_argument(
        "--regen-html",
        action="store_true",
        help="Regenerate report HTML for an existing run (requires meta_{seed}.json and images in output dir).",
    )
    parser.add_argument(
        "--ai-compare",
        action="store_true",
        help="Run backend/tools/analyze_image.py comparison (requires OPENROUTER_API_KEY).",
    )
    parser.add_argument("--ai-model", default="qwen/qwen3-vl-8b-instruct", help="OpenRouter model slug for --ai-compare")

    args = parser.parse_args()
    seed = args.seed if args.seed != 0 else random.randint(1, 10_000_000_000)

    here = Path(__file__).resolve()
    workflow_path = here.with_name("comfyui_hallucination_test_comfyui_workflow.json")
    out_dir = REPO_ROOT / "artifacts" / "comfyui_hallucination_test"
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.regen_html:
        if args.seed == 0:
            raise SystemExit("--regen-html requires an explicit --seed")
        if args.ai_compare:
            meta_path = out_dir / f"meta_{args.seed}.json"
            if not meta_path.exists():
                raise SystemExit(f"Missing meta file: {meta_path}")
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            ref_path = out_dir / f"reference_{args.seed}.png"
            out_path = out_dir / f"upscaled_{args.seed}.png"
            if not ref_path.exists() or not out_path.exists():
                raise SystemExit("Missing reference/output images for --regen-html --ai-compare.")
            if not os.environ.get("OPENROUTER_API_KEY"):
                print("Skipping --ai-compare: OPENROUTER_API_KEY not set.", file=sys.stderr)
            else:
                import asyncio

                meta["ai_compare"] = asyncio.run(
                    ai_compare(ref_path, out_path, str(meta.get("prompt", "")), model=str(args.ai_model))
                )
                meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
        regen_html_only(out_dir=out_dir, seed=args.seed, workflow_file=str(workflow_path), server=str(args.server))
        return 0

    input_path = Path(args.input_image).expanduser()
    if not input_path.exists():
        raise SystemExit(f"Input image not found: {input_path}")

    processed_input_path = out_dir / f"input_{seed}.png"
    preprocessing = downscale_image(input_path, processed_input_path, float(args.downscale_input))

    reference_path = out_dir / f"reference_{seed}.png"
    reference_meta = bicubic_upscale_2x(processed_input_path, reference_path)
    preprocessing = {**preprocessing, **reference_meta}

    workflow = load_workflow(workflow_path)
    if args.denoise is not None:
        set_denoise(workflow, float(args.denoise))
    client_id = f"hallucination-test-{os.getpid()}-{random.randint(1000, 9999)}"
    client = None
    try:
        client = ComfyUIClient(str(args.server), client_id)
        print(f"Uploading (preprocessed) {processed_input_path} ...")
        comfy_filename = client.upload_image(processed_input_path)

        configure_workflow(workflow, comfy_image_name=comfy_filename, prompt=args.prompt, seed=seed)

        t0 = time.perf_counter()
        print(f"Queuing workflow (seed={seed}) ...")
        prompt_id = client.queue_prompt(workflow)

        print("Waiting for generation ...")
        client.wait_for_prompt(prompt_id, timeout_s=float(args.timeout))
        generation_time_s = time.perf_counter() - t0

        history = client.get_history(prompt_id)
        history_for_prompt = history.get(prompt_id) or {}
        image_ref = first_image_ref_from_history(history_for_prompt, preferred_node=str(args.save_node))
        if not image_ref:
            raise RuntimeError(f"No images found in ComfyUI history for prompt_id={prompt_id}")

        print(f"Downloading {image_ref.filename} ...")
        raw = client.get_image_data(image_ref)
        output_path = out_dir / f"upscaled_{seed}.png"
        output_path.write_bytes(raw)

        similarity = compute_similarity_metrics(reference_path, output_path)
        ai_report = None
        if args.ai_compare:
            if not os.environ.get("OPENROUTER_API_KEY"):
                print("Skipping --ai-compare: OPENROUTER_API_KEY not set.", file=sys.stderr)
            else:
                import asyncio

                ai_report = asyncio.run(ai_compare(reference_path, output_path, args.prompt, model=str(args.ai_model)))

        meta_path = out_dir / f"meta_{seed}.json"
        meta = {
            "seed": seed,
            "server": str(args.server),
            "workflow": str(workflow_path),
            "prompt": args.prompt,
            "denoise": (workflow.get("3", {}).get("inputs", {}) or {}).get("denoise"),
            "generation_time_s": generation_time_s,
            "comfyui_prompt_id": str(prompt_id),
            "comfyui_output_filename": str(image_ref.filename),
            "preprocessing": preprocessing,
            "similarity": similarity,
            "ai_compare": ai_report,
            "original_input_path": str(input_path),
            "processed_input_path": str(processed_input_path),
            "reference_path": str(reference_path),
            "output_path": str(output_path),
        }
        meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")

        report_path = out_dir / f"report_{seed}.html"
        generate_html_report(
            reference_filename=reference_path.name,
            output_filename=output_path.name,
            prompt=args.prompt,
            report_path=report_path,
            seed=seed,
            denoise=(workflow.get("3", {}).get("inputs", {}) or {}).get("denoise"),
            server_address=str(args.server),
            workflow_file=str(workflow_path),
            generation_time_s=generation_time_s,
            comfyui_prompt_id=str(prompt_id),
            comfyui_output_filename=str(image_ref.filename),
            preprocessing=preprocessing,
            similarity=similarity,
            ai_report=ai_report,
            meta_filename=meta_path.name,
        )

        print(f"Report generated: {report_path}")
        if not args.no_open:
            import webbrowser

            webbrowser.open(file_url(report_path))
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
