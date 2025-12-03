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

def analyze_frames(timestamps_file):
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
    if num_dropped > 0:
        print(f"Worst Drops:")
        # Sort dropped frames by severity
        drops = deltas[dropped_indices]
        sorted_drop_indices = dropped_indices[np.argsort(drops)][::-1]
        
        for i in sorted_drop_indices[:5]: # Show top 5
            t_occurrence = timestamps[i+1] - timestamps[0]
            print(f"  - {deltas[i]:.2f} ms at {t_occurrence/1000:.2f}s into playback")
    print("-" * 40)

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
    analyze_frames(OUTPUT_FILE)

if __name__ == "__main__":
    main()
