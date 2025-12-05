import argparse
import json
import subprocess
import sys
import numpy as np
from pathlib import Path

# Paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
RUNNER_SCRIPT = PROJECT_ROOT / "scripts" / "run_browser_experiment.py"
HOOK_FILE = Path(__file__).parent / "hook.js"
OUTPUT_FILE = PROJECT_ROOT / "artifacts" / "check_dropped_frames" / "timestamps.json"
HTML_OUTPUT_FILE = PROJECT_ROOT / "artifacts" / "check_dropped_frames" / "report.html"

def generate_html_report(stats, worst_drops, output_path):
    rows = ""
    for drop in worst_drops:
        rows += f"<tr><td>{drop['delta']:.2f} ms</td><td>{drop['time']:.2f} s</td></tr>"
    
    if not rows:
        rows = "<tr><td colspan='2'>No significant drops detected.</td></tr>"

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Frame Drop Analysis: {stats['dataset']}</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; max-width: 800px; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; color: #333; }}
            h1 {{ border-bottom: 2px solid #eee; padding-bottom: 0.5rem; }}
            .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 2rem; }}
            .card {{ background: #f9f9f9; padding: 1rem; border-radius: 8px; border: 1px solid #eee; }}
            .card strong {{ display: block; font-size: 0.875rem; color: #666; margin-bottom: 0.25rem; }}
            .card span {{ font-size: 1.25rem; font-weight: 600; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 1rem; }}
            th, td {{ text-align: left; padding: 0.75rem; border-bottom: 1px solid #eee; }}
            th {{ background: #f1f1f1; }}
            .warning {{ color: #d32f2f; }}
        </style>
    </head>
    <body>
        <h1>Frame Analysis Report</h1>
        <p>Dataset: <strong>{stats['dataset']}</strong></p>
        
        <div class="grid">
            <div class="card"><strong>Total Frames</strong><span>{stats['total_frames']}</span></div>
            <div class="card"><strong>Duration</strong><span>{stats['duration']:.2f} s</span></div>
            <div class="card"><strong>Est. FPS</strong><span>{stats['target_fps']:.1f}</span></div>
            <div class="card"><strong>Mean Frame Time</strong><span>{stats['mean_delta']:.2f} ms</span></div>
            <div class="card"><strong>Std Dev</strong><span>{stats['std_dev']:.2f} ms</span></div>
            <div class="card"><strong>Dropped Frames</strong><span class="{ 'warning' if stats['num_dropped'] > 0 else '' }">{stats['num_dropped']}</span></div>
        </div>

        <h2>Worst Frame Drops</h2>
        <p>Threshold: &gt; {stats['threshold']:.1f} ms</p>
        <table>
            <thead>
                <tr>
                    <th>Frame Time (Delta)</th>
                    <th>Time into Playback</th>
                </tr>
            </thead>
            <tbody>
                {rows}
            </tbody>
        </table>
    </body>
    </html>
    """
    try:
        with open(output_path, 'w') as f:
            f.write(html_content)
        print(f"HTML report generated: {output_path}")
    except Exception as e:
        print(f"Failed to write HTML report: {e}")

def analyze_frames(timestamps_file, dataset_name):
    with open(timestamps_file, 'r') as f:
        timestamps = json.load(f)
    
    if not timestamps or len(timestamps) < 2:
        print("Insufficient data collected.")
        return

    # Convert to numpy array for easier math
    arr = np.array(timestamps)
    
    # Calculate deltas (time between frames)
    deltas = np.diff(arr)
    
    # Basic Stats
    mean_delta = np.mean(deltas)
    std_dev = np.std(deltas)
    min_delta = np.min(deltas)
    max_delta = np.max(deltas)
    
    # Infer Target FPS (e.g., 60fps -> ~16.66ms)
    # We'll assume the most common delta is the target
    # Round to nearest ms to find the mode
    rounded_deltas = np.round(deltas).astype(int)
    mode_delta = float(np.bincount(rounded_deltas).argmax())
    target_fps = 1000.0 / mode_delta if mode_delta > 0 else 0
    
    # Dropped Frames Detection
    # A frame is "dropped" if the delta is significantly larger than the expected interval.
    # e.g., > 1.5x the mode delta.
    threshold = mode_delta * 1.5
    dropped_indices = np.where(deltas > threshold)[0]
    num_dropped = len(dropped_indices)
    
    print("-" * 40)
    print(f"FRAME ANALYSIS REPORT")
    print("-" * 40)
    print(f"Total Frames:      {len(timestamps)}")
    print(f"Duration:          {(arr[-1] - arr[0]) / 1000:.2f} seconds")
    print(f"Estimated FPS:     {target_fps:.1f}")
    print(f"Mean Frame Time:   {mean_delta:.2f} ms")
    print(f"Std Dev:           {std_dev:.2f} ms")
    print(f"Min/Max Delta:     {min_delta:.2f} ms / {max_delta:.2f} ms")
    print("-" * 40)
    print(f"DROPPED FRAMES (> {threshold:.1f} ms): {num_dropped}")
    
    worst_drops = []
    if num_dropped > 0:
        print(f"Worst Drops:")
        # Sort dropped frames by severity
        drops = deltas[dropped_indices]
        sorted_drop_indices = dropped_indices[np.argsort(drops)][::-1]
        
        for i in sorted_drop_indices[:10]: # Collect top 10 for report
            t_occurrence = (timestamps[i+1] - timestamps[0]) / 1000.0
            worst_drops.append({
                'delta': deltas[i],
                'time': t_occurrence
            })
            # Print top 5 to console
            if len(worst_drops) <= 5:
                print(f"  - {deltas[i]:.2f} ms at {t_occurrence:.2f}s into playback")
    print("-" * 40)

    # Prepare stats for HTML report
    stats = {
        'dataset': dataset_name,
        'total_frames': len(timestamps),
        'duration': (arr[-1] - arr[0]) / 1000,
        'target_fps': target_fps,
        'mean_delta': mean_delta,
        'std_dev': std_dev,
        'min_delta': min_delta,
        'max_delta': max_delta,
        'num_dropped': num_dropped,
        'threshold': threshold
    }
    
    generate_html_report(stats, worst_drops, HTML_OUTPUT_FILE)

def main():
    parser = argparse.ArgumentParser(description="Run browser experiment and analyze frame drops.")
    parser.add_argument("--dataset", required=True, help="Dataset ID")
    parser.add_argument("--visible", action="store_true", help="Run browser visibly")
    args = parser.parse_args()

    # 1. Run Experiment
    cmd = [
        sys.executable, str(RUNNER_SCRIPT),
        "--dataset", args.dataset,
        "--hook", str(HOOK_FILE),
        "--output", str(OUTPUT_FILE)
    ]
    
    if args.visible:
        cmd.append("--visible")
        
    print(f"Running experiment with dataset: {args.dataset}...")
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error running experiment: {e}")
        sys.exit(1)

    # 2. Analyze Results
    print("\nAnalyzing results...")
    analyze_frames(OUTPUT_FILE, args.dataset)

if __name__ == "__main__":
    main()
