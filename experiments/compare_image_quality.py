#!/usr/bin/env python3
"""
Image Format Quality Comparison Tool for Ultra-Resolution Quads

Generates JPEG, WebP, and AVIF versions of a single tile at multiple quality
levels using Pillow, creates an interactive HTML viewer with zoom capability for
artifact inspection, and measures decode performance.

Usage:
    python experiments/compare_image_quality.py --dataset power_tower --tile 5/12/8
"""

import argparse
import json
import shutil
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, UnidentifiedImageError, features

PROJECT_ROOT = Path(__file__).parent.parent
DATASETS_DIR = PROJECT_ROOT / "datasets"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"


def find_tile(dataset_id: str, tile_spec: Optional[str] = None) -> Path:
    """
    Find a tile in the dataset. If tile_spec is provided (format: level/x/y),
    use that specific tile. Otherwise, find a representative tile.
    """
    dataset_path = DATASETS_DIR / dataset_id
    if not dataset_path.exists():
        raise ValueError(f"Dataset not found: {dataset_path}")
    
    if tile_spec:
        # Parse tile specification (e.g., "5/12/8")
        parts = tile_spec.split("/")
        if len(parts) != 3:
            raise ValueError(f"Invalid tile spec '{tile_spec}'. Use format: level/x/y")
        
        level, x, y = parts
        tile_path = dataset_path / level / x / f"{y}.png"
        
        if not tile_path.exists():
            raise ValueError(f"Tile not found: {tile_path}")
        
        return tile_path
    else:
        # Find a mid-level tile with interesting content
        # Look for tiles at level 4-6 (good detail without being too large)
        for level in [5, 4, 6, 3]:
            level_dir = dataset_path / str(level)
            if level_dir.exists():
                png_files = list(level_dir.rglob("*.png"))
                if png_files:
                    # Pick a tile near the middle of the set
                    return png_files[len(png_files) // 2]
        
        # Fallback: any PNG
        png_files = list(dataset_path.rglob("*.png"))
        if not png_files:
            raise ValueError(f"No PNG tiles found in dataset: {dataset_id}")
        
        return png_files[0]


def get_image_info(image_path: Path, fallback_dimensions: Tuple[int, int] = None) -> dict:
    """Get image dimensions and file size."""
    width, height = 0, 0
    try:
        with Image.open(image_path) as img:
            width, height = img.size
    except (UnidentifiedImageError, FileNotFoundError):
        if fallback_dimensions:
            width, height = fallback_dimensions
        else:
            print(f"Warning: Could not identify image {image_path}")
    
    file_size = 0
    if image_path.exists():
        file_size = image_path.stat().st_size
    
    return {
        "width": width,
        "height": height,
        "file_size": file_size,
        "file_size_kb": file_size / 1024,
        "megapixels": (width * height) / 1_000_000 if width and height else 0
    }


def convert_to_jpeg(input_path: Path, output_path: Path, quality: int):
    """Convert to JPEG using Pillow."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        with Image.open(input_path) as img:
            # JPEG does not support alpha; strip it if present.
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGB")
            img.save(output_path, format="JPEG", quality=quality, optimize=True, progressive=True)
    except OSError as exc:
        raise RuntimeError(f"Failed to convert to JPEG: {exc}") from exc


def convert_to_webp(input_path: Path, output_path: Path, quality: int):
    """Convert to WebP using Pillow."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    if not features.check("webp"):
        print("Warning: WebP encoding not supported by this Pillow build")
        return False
    
    try:
        with Image.open(input_path) as img:
            img.save(
                output_path,
                format="WEBP",
                quality=quality,
                method=6,  # 0-6, slower gives better compression
            )
        return True
    except OSError as exc:
        print(f"Warning: WebP encoding failed: {exc}")
        return False


def convert_to_avif(input_path: Path, output_path: Path, crf: int):
    """Convert to AVIF using Pillow."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        avif_supported = features.get_supported().get("avif", False)
    except Exception:
        avif_supported = False
    
    if not avif_supported:
        print("Warning: AVIF encoding not supported by this Pillow build")
        return False
    
    try:
        with Image.open(input_path) as img:
            img.save(output_path, format="AVIF", quality=crf)
        return True
    except OSError as exc:
        print(f"Warning: AVIF encoding failed: {exc}")
        return False


def generate_comparison_html(
    output_dir: Path,
    dataset_id: str,
    tile_name: str,
    variants: list,
    original_info: dict
) -> Path:
    """
    Generate interactive HTML comparison page with zoom capability.
    """
    
    # Convert variants list to JSON-safe format
    variants_json = json.dumps(variants, indent=4)
    original_json = json.dumps(original_info, indent=4)
    
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Image Quality Comparison - {dataset_id}</title>
    <style>
        :root {{
            --color-bg: #1f2121;
            --color-surface: #262828;
            --color-text: #f5f5f5;
            --color-text-secondary: #a7a9a9;
            --color-primary: #32b8c6;
            --color-border: rgba(119, 124, 124, 0.3);
            --color-success: #32b8c6;
            --color-warning: #e68161;
            --color-error: #ff5459;
        }}
        
        * {{ box-sizing: border-box; }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: var(--color-bg);
            color: var(--color-text);
            margin: 0;
            padding: 20px;
            line-height: 1.6;
        }}
        
        .container {{
            max-width: 1800px;
            margin: 0 auto;
        }}
        
        h1 {{
            font-size: 32px;
            margin-bottom: 8px;
            color: var(--color-primary);
        }}
        
        h2 {{
            font-size: 24px;
            margin-top: 40px;
            margin-bottom: 16px;
            border-bottom: 2px solid var(--color-border);
            padding-bottom: 8px;
        }}
        
        .controls {{
            margin: 24px 0;
            padding: 20px;
            background: var(--color-surface);
            border-radius: 8px;
            border: 1px solid var(--color-border);
            display: flex;
            gap: 16px;
            align-items: center;
            flex-wrap: wrap;
        }}
        
        .control-group {{
            display: flex;
            flex-direction: column;
            gap: 8px;
        }}
        
        .control-group label {{
            font-size: 14px;
            color: var(--color-text-secondary);
            font-weight: 500;
        }}
        
        select, button {{
            background: var(--color-surface);
            color: var(--color-text);
            border: 1px solid var(--color-border);
            padding: 8px 16px;
            border-radius: 6px;
            font-size: 14px;
            cursor: pointer;
        }}
        
        button {{
            background: var(--color-primary);
            color: var(--color-bg);
            border: none;
            font-weight: 500;
            transition: opacity 0.2s;
        }}
        
        button:hover {{ opacity: 0.9; }}
        button:disabled {{
            opacity: 0.5;
            cursor: not-allowed;
        }}
        
        .zoom-controls {{
            display: flex;
            gap: 8px;
            align-items: center;
        }}
        
        .zoom-controls button {{
            padding: 8px 12px;
            min-width: 40px;
        }}
        
        #zoomLevel {{
            min-width: 80px;
            text-align: center;
            font-weight: 600;
        }}
        
        .comparison-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin: 24px 0;
        }}
        
        .image-panel {{
            background: var(--color-surface);
            border: 2px solid var(--color-border);
            border-radius: 8px;
            padding: 16px;
            position: relative;
            transition: border-color 0.2s;
        }}
        
        .image-panel.selected {{
            border-color: var(--color-primary);
        }}
        
        .image-panel h3 {{
            margin: 0 0 12px 0;
            font-size: 18px;
            color: var(--color-primary);
        }}
        
        .image-container {{
            position: relative;
            width: 100%;
            overflow: hidden;
            background: #000;
            border-radius: 4px;
            cursor: move;
        }}
        
        .image-container img {{
            display: block;
            width: 100%;
            height: auto;
            image-rendering: pixelated;
            transform-origin: 0 0;
            transition: transform 0.1s ease-out;
        }}
        
        .image-info {{
            margin-top: 12px;
            font-size: 13px;
            line-height: 1.8;
        }}
        
        .info-row {{
            display: flex;
            justify-content: space-between;
            padding: 4px 0;
            border-bottom: 1px solid var(--color-border);
        }}
        
        .info-row:last-child {{
            border-bottom: none;
        }}
        
        .info-label {{
            color: var(--color-text-secondary);
        }}
        
        .info-value {{
            font-weight: 600;
        }}
        
        .size-reduction {{
            color: var(--color-success);
            font-weight: 600;
        }}
        
        .decode-time {{
            font-weight: 600;
        }}
        
        .decode-time.fast {{ color: var(--color-success); }}
        .decode-time.medium {{ color: var(--color-warning); }}
        .decode-time.slow {{ color: var(--color-error); }}
        
        .summary-table {{
            width: 100%;
            border-collapse: collapse;
            margin: 24px 0;
            background: var(--color-surface);
            border-radius: 8px;
            overflow: hidden;
        }}
        
        .summary-table th,
        .summary-table td {{
            padding: 12px 16px;
            text-align: left;
            border-bottom: 1px solid var(--color-border);
        }}
        
        .summary-table th {{
            background: rgba(50, 184, 198, 0.1);
            color: var(--color-primary);
            font-weight: 600;
        }}
        
        .summary-table tr:last-child td {{
            border-bottom: none;
        }}
        
        .status-indicator {{
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 600;
        }}
        
        .status-indicator.excellent {{ background: rgba(50, 184, 198, 0.2); color: var(--color-success); }}
        .status-indicator.good {{ background: rgba(230, 129, 97, 0.2); color: var(--color-warning); }}
        .status-indicator.poor {{ background: rgba(255, 84, 89, 0.2); color: var(--color-error); }}
        
        #benchmarkStatus {{
            margin: 16px 0;
            padding: 12px;
            background: var(--color-surface);
            border-radius: 6px;
            font-size: 14px;
            text-align: center;
        }}
        
        .instructions {{
            background: rgba(50, 184, 198, 0.1);
            border-left: 4px solid var(--color-primary);
            padding: 16px;
            margin: 24px 0;
            border-radius: 4px;
        }}
        
        .instructions h3 {{
            margin: 0 0 8px 0;
            color: var(--color-primary);
        }}
        
        .instructions ul {{
            margin: 8px 0 0 20px;
            padding: 0;
        }}
        
        .instructions li {{
            margin: 4px 0;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Image Quality Comparison</h1>
        <p><strong>Dataset:</strong> {dataset_id} | <strong>Tile:</strong> {tile_name}</p>
        
        <div class="instructions">
            <h3>How to Use</h3>
            <ul>
                <li><strong>Zoom:</strong> Use +/- buttons or slider to zoom in and inspect compression artifacts</li>
                <li><strong>Pan:</strong> Click and drag on any image to move around</li>
                <li><strong>Synchronized:</strong> All images zoom and pan together for direct comparison</li>
                <li><strong>Benchmark:</strong> Click "Run Performance Test" to measure decode times</li>
            </ul>
        </div>
        
        <div class="controls">
            <div class="control-group">
                <label>Comparison Mode</label>
                <select id="comparisonMode">
                    <option value="all">Show All Formats</option>
                    <option value="original">Original Only</option>
                    <option value="jpeg">JPEG Variants</option>
                    <option value="webp">WebP Variants</option>
                    <option value="avif">AVIF Variants</option>
                </select>
            </div>
            
            <div class="control-group zoom-controls">
                <label>Zoom Level</label>
                <div style="display: flex; gap: 8px; align-items: center;">
                    <button onclick="zoomOut()">-</button>
                    <span id="zoomLevel">100%</span>
                    <button onclick="zoomIn()">+</button>
                    <input type="range" id="zoomSlider" min="1" max="8" value="1" step="0.5" 
                           style="width: 150px;" oninput="setZoom(this.value)">
                    <button onclick="resetZoom()">Reset</button>
                </div>
            </div>
            
            <div class="control-group">
                <button onclick="runBenchmark()" id="benchmarkBtn">Run Performance Test</button>
            </div>
        </div>
        
        <div id="benchmarkStatus"></div>
        
        <h2>Visual Comparison</h2>
        <div class="comparison-grid" id="imageGrid"></div>
        
        <h2>Performance Summary</h2>
        <table class="summary-table" id="summaryTable">
            <thead>
                <tr>
                    <th>Format</th>
                    <th>Quality</th>
                    <th>File Size</th>
                    <th>Size Reduction</th>
                    <th>Decode Time</th>
                    <th>Performance</th>
                </tr>
            </thead>
            <tbody id="summaryBody"></tbody>
        </table>
    </div>
    
    <script>
        // Configuration
        const ORIGINAL_INFO = {original_json};
        const VARIANTS = {variants_json};
        
        let currentZoom = 1;
        let panOffset = {{ x: 0, y: 0 }};
        let isPanning = false;
        let panStart = {{ x: 0, y: 0 }};
        let benchmarkResults = {{}};
        let fileProtocolBlocked = false;
        
        // Initialize page
        window.addEventListener('DOMContentLoaded', () => {{
            // Disable benchmark when opened via file:// because fetch is blocked
            if (window.location.protocol === 'file:') {{
                fileProtocolBlocked = true;
                const btn = document.getElementById('benchmarkBtn');
                const status = document.getElementById('benchmarkStatus');
                btn.disabled = true;
                status.textContent = 'Benchmark disabled when opened via file:// (CORS blocks fetch). Please open through a local server, e.g. python -m http.server 8000 from repo root.';
            }}
            
            renderImageGrid();
            setupPanHandlers();
            document.getElementById('comparisonMode').addEventListener('change', renderImageGrid);
        }});
        
        function renderImageGrid() {{
            const grid = document.getElementById('imageGrid');
            const mode = document.getElementById('comparisonMode').value;
            grid.innerHTML = '';
            
            // Always show original first
            if (mode === 'all' || mode === 'original') {{
                const panel = createImagePanel('original', 'Original PNG', 'original.png', ORIGINAL_INFO);
                grid.appendChild(panel);
            }}
            
            // Show format variants
            VARIANTS.forEach(variant => {{
                const showThis = mode === 'all' || 
                                mode === variant.format.toLowerCase() ||
                                (mode === 'original' && false);
                
                if (showThis) {{
                    const panel = createImagePanel(
                        variant.id,
                        variant.label,
                        variant.filename,
                        variant.info
                    );
                    grid.appendChild(panel);
                }}
            }});
        }}
        
        function createImagePanel(id, label, filename, info) {{
            const panel = document.createElement('div');
            panel.className = 'image-panel';
            panel.id = `panel-${{id}}`;
            
            const sizeReduction = info.file_size_kb && ORIGINAL_INFO.file_size_kb 
                ? ((1 - info.file_size_kb / ORIGINAL_INFO.file_size_kb) * 100).toFixed(1)
                : 0;
            
            const decodeTime = benchmarkResults[id]?.decodeTime || 'Not tested';
            const decodeClass = typeof decodeTime === 'number' 
                ? (decodeTime < 20 ? 'fast' : decodeTime < 40 ? 'medium' : 'slow')
                : '';
            
            panel.innerHTML = `
                <h3>${{label}}</h3>
                <div class="image-container" data-image-id="${{id}}">
                    <img src="${{filename}}" alt="${{label}}" id="img-${{id}}">
                </div>
                <div class="image-info">
                    <div class="info-row">
                        <span class="info-label">Dimensions:</span>
                        <span class="info-value">${{info.width}} × ${{info.height}}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">File Size:</span>
                        <span class="info-value">${{info.file_size_kb.toFixed(1)}} KB</span>
                    </div>
                    ${{id !== 'original' ? `
                    <div class="info-row">
                        <span class="info-label">Size Reduction:</span>
                        <span class="size-reduction">-${{sizeReduction}}%</span>
                    </div>
                    ` : ''}}
                    <div class="info-row">
                        <span class="info-label">Decode Time:</span>
                        <span class="decode-time ${{decodeClass}}">${{typeof decodeTime === 'number' ? decodeTime.toFixed(2) + ' ms' : decodeTime}}</span>
                    </div>
                </div>
            `;
            
            return panel;
        }}
        
        function setupPanHandlers() {{
            document.addEventListener('mousedown', (e) => {{
                if (e.target.tagName === 'IMG') {{
                    isPanning = true;
                    panStart = {{ x: e.clientX - panOffset.x, y: e.clientY - panOffset.y }};
                    e.preventDefault();
                }}
            }});
            
            document.addEventListener('mousemove', (e) => {{
                if (isPanning) {{
                    panOffset.x = e.clientX - panStart.x;
                    panOffset.y = e.clientY - panStart.y;
                    updateAllTransforms();
                    e.preventDefault();
                }}
            }});
            
            document.addEventListener('mouseup', () => {{
                isPanning = false;
            }});
        }}
        
        function zoomIn() {{
            currentZoom = Math.min(currentZoom + 0.5, 8);
            document.getElementById('zoomSlider').value = currentZoom;
            updateZoomDisplay();
            updateAllTransforms();
        }}
        
        function zoomOut() {{
            currentZoom = Math.max(currentZoom - 0.5, 1);
            document.getElementById('zoomSlider').value = currentZoom;
            updateZoomDisplay();
            updateAllTransforms();
        }}
        
        function setZoom(value) {{
            currentZoom = parseFloat(value);
            updateZoomDisplay();
            updateAllTransforms();
        }}
        
        function resetZoom() {{
            currentZoom = 1;
            panOffset = {{ x: 0, y: 0 }};
            document.getElementById('zoomSlider').value = 1;
            updateZoomDisplay();
            updateAllTransforms();
        }}
        
        function updateZoomDisplay() {{
            document.getElementById('zoomLevel').textContent = `${{Math.round(currentZoom * 100)}}%`;
        }}
        
        function updateAllTransforms() {{
            document.querySelectorAll('.image-container img').forEach(img => {{
                img.style.transform = `scale(${{currentZoom}}) translate(${{panOffset.x / currentZoom}}px, ${{panOffset.y / currentZoom}}px)`;
            }});
        }}
        
        async function runBenchmark() {{
            const btn = document.getElementById('benchmarkBtn');
            const status = document.getElementById('benchmarkStatus');
            
            if (fileProtocolBlocked) {{
                status.textContent = 'Benchmark disabled when opened via file://. Serve over http://localhost instead.';
                return;
            }}
            
            btn.disabled = true;
            status.textContent = 'Running performance tests...';
            
            benchmarkResults = {{}};
            
            // Test original
            await benchmarkImage('original', 'original.png');
            
            // Test all variants
            for (const variant of VARIANTS) {{
                await benchmarkImage(variant.id, variant.filename);
            }}
            
            // Re-render to show results
            renderImageGrid();
            updateSummaryTable();
            
            btn.disabled = false;
            status.textContent = 'Performance test complete! Results updated below.';
            
            setTimeout(() => {{
                status.textContent = '';
            }}, 3000);
        }}
        
        async function benchmarkImage(id, filename) {{
            const iterations = 10;
            const times = [];
            
            for (let i = 0; i < iterations; i++) {{
                const startTime = performance.now();
                
                const response = await fetch(filename);
                const blob = await response.blob();
                const bitmap = await createImageBitmap(blob, {{
                    premultiplyAlpha: 'none',
                    colorSpaceConversion: 'none'
                }});
                
                const decodeTime = performance.now() - startTime;
                times.push(decodeTime);
                
                bitmap.close();
                
                // Small delay between iterations
                await new Promise(resolve => setTimeout(resolve, 50));
            }}
            
            // Calculate average, excluding first iteration (warm-up)
            const avgTime = times.slice(1).reduce((a, b) => a + b, 0) / (iterations - 1);
            
            benchmarkResults[id] = {{
                decodeTime: avgTime,
                times: times
            }};
        }}
        
        function updateSummaryTable() {{
            const tbody = document.getElementById('summaryBody');
            tbody.innerHTML = '';
            
            // Add original
            const originalRow = createSummaryRow('original', 'PNG', 'Original', ORIGINAL_INFO, 0);
            tbody.appendChild(originalRow);
            
            // Add variants
            VARIANTS.forEach(variant => {{
                const sizeReduction = ((1 - variant.info.file_size_kb / ORIGINAL_INFO.file_size_kb) * 100);
                const row = createSummaryRow(variant.id, variant.format, variant.quality, variant.info, sizeReduction);
                tbody.appendChild(row);
            }});
        }}
        
        function createSummaryRow(id, format, quality, info, sizeReduction) {{
            const row = document.createElement('tr');
            
            const decodeTime = benchmarkResults[id]?.decodeTime;
            const decodeDisplay = decodeTime ? `${{decodeTime.toFixed(2)}} ms` : 'Not tested';
            
            let perfRating = '-';
            let perfClass = '';
            if (decodeTime) {{
                if (decodeTime < 20) {{
                    perfRating = 'Excellent';
                    perfClass = 'excellent';
                }} else if (decodeTime < 40) {{
                    perfRating = 'Good';
                    perfClass = 'good';
                }} else {{
                    perfRating = 'Poor';
                    perfClass = 'poor';
                }}
            }}
            
            row.innerHTML = `
                <td><strong>${{format}}</strong></td>
                <td>${{quality}}</td>
                <td>${{info.file_size_kb.toFixed(1)}} KB</td>
                <td>${{id !== 'original' ? `-${{sizeReduction.toFixed(1)}}%` : '-'}}</td>
                <td>${{decodeDisplay}}</td>
                <td>${{perfRating !== '-' ? `<span class="status-indicator ${{perfClass}}">${{perfRating}}</span>` : '-'}}</td>
            `;
            
            return row;
        }}
        
        // Initialize summary table on load
        updateSummaryTable();
    </script>
</body>
</html>
"""
    
    html_path = output_dir / "comparison.html"
    html_path.write_text(html_content)
    print(f"✓ Generated comparison HTML: {html_path}")
    return html_path


def main():
    parser = argparse.ArgumentParser(
        description="Generate image format quality comparison for ultra-resolution-quads"
    )
    parser.add_argument(
        "--dataset",
        required=True,
        help="Dataset ID (e.g., power_tower)"
    )
    parser.add_argument(
        "--tile",
        default=None,
        help="Specific tile to compare (format: level/x/y, e.g., 5/12/8). If not provided, auto-selects a representative tile."
    )
    
    args = parser.parse_args()
    
    print(f"=== Image Format Quality Comparison ===")
    print(f"Dataset: {args.dataset}")
    print()
    
    # Find the tile
    print("Finding tile...")
    tile_path = find_tile(args.dataset, args.tile)
    tile_relative = tile_path.relative_to(DATASETS_DIR / args.dataset)
    tile_name = str(tile_relative)
    print(f"✓ Selected tile: {tile_name}")
    print()
    
    # Get original info
    original_info = get_image_info(tile_path)
    print(f"Original image: {original_info['width']}x{original_info['height']}, {original_info['file_size_kb']:.1f} KB")
    print()
    
    # Create output directory
    output_dir = ARTIFACTS_DIR / f"quality_comparison_{args.dataset}"
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {output_dir}")
    print()
    
    # Copy original PNG
    original_dest = output_dir / "original.png"
    shutil.copy2(tile_path, original_dest)
    print(f"✓ Copied original PNG")
    
    # Generate variants
    variants = []
    
    # JPEG variants
    jpeg_qualities = [
        (60, "Low"),
        (80, "Medium"),
        (95, "High")
    ]
    
    print("\nGenerating JPEG variants...")
    for web_quality, label in jpeg_qualities:
        filename = f"jpeg_q{web_quality}.jpg"
        output_path = output_dir / filename
        convert_to_jpeg(tile_path, output_path, web_quality)
        
        info = get_image_info(output_path, (original_info['width'], original_info['height']))
        variants.append({
            "id": f"jpeg_q{web_quality}",
            "format": "JPEG",
            "quality": label,
            "filename": filename,
            "label": f"JPEG {label}",
            "info": info
        })
        
        reduction = ((original_info['file_size_kb'] - info['file_size_kb']) / original_info['file_size_kb'] * 100)
        print(f"  ✓ JPEG q{web_quality} ({label}): {info['file_size_kb']:.1f} KB (-{reduction:.1f}%)")
    
    # WebP variants
    webp_qualities = [
        (70, "Low"),
        (85, "Medium"),
        (95, "High")
    ]
    
    print("\nGenerating WebP variants...")
    webp_available = True
    for quality, label in webp_qualities:
        filename = f"webp_q{quality}.webp"
        output_path = output_dir / filename
        
        if convert_to_webp(tile_path, output_path, quality):
            info = get_image_info(output_path, (original_info['width'], original_info['height']))
            variants.append({
                "id": f"webp_q{quality}",
                "format": "WebP",
                "quality": label,
                "filename": filename,
                "label": f"WebP {label}",
                "info": info
            })
            
            reduction = ((original_info['file_size_kb'] - info['file_size_kb']) / original_info['file_size_kb'] * 100)
            print(f"  ✓ WebP q{quality} ({label}): {info['file_size_kb']:.1f} KB (-{reduction:.1f}%)")
        else:
            webp_available = False
            print(f"  ✗ WebP encoding not available")
            break
    
    # AVIF variants
    avif_crfs = [
        (40, "Low"),
        (28, "Medium"),
        (18, "High")
    ]
    
    print("\nGenerating AVIF variants...")
    avif_available = True
    for crf, label in avif_crfs:
        filename = f"avif_crf{crf}.avif"
        output_path = output_dir / filename
        
        if convert_to_avif(tile_path, output_path, crf):
            info = get_image_info(output_path, (original_info['width'], original_info['height']))
            variants.append({
                "id": f"avif_crf{crf}",
                "format": "AVIF",
                "quality": label,
                "filename": filename,
                "label": f"AVIF {label}",
                "info": info
            })
            
            reduction = ((original_info['file_size_kb'] - info['file_size_kb']) / original_info['file_size_kb'] * 100)
            print(f"  ✓ AVIF crf{crf} ({label}): {info['file_size_kb']:.1f} KB (-{reduction:.1f}%)")
        else:
            avif_available = False
            print(f"  ✗ AVIF encoding not available")
            break
    
    if not avif_available:
        print("\nNote: AVIF support requires Pillow built with AVIF encoding support")
    
    print()
    
    # Generate HTML comparison page
    html_path = generate_comparison_html(
        output_dir,
        args.dataset,
        tile_name,
        variants,
        original_info
    )
    
    print("\n" + "=" * 60)
    print("✓ Quality comparison complete!")
    print()
    print("Next steps:")
    print(f"1. Start a local server: python -m http.server 8000")
    print(f"2. Open: http://localhost:8000/{html_path.relative_to(PROJECT_ROOT)}")
    print(f"3. Zoom in to inspect compression artifacts")
    print(f"4. Click 'Run Performance Test' to measure decode times")
    print()
    print(f"Output directory: {output_dir}")


if __name__ == "__main__":
    main()
