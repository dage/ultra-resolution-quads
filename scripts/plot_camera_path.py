import sys
import os
import json
import math
import matplotlib.pyplot as plt
import glob

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from backend import camera_utils

DATA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'datasets'))
ARTIFACTS_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'artifacts'))

def plot_dataset_path(config_file, dataset_id):
    print(f"Loading config from {config_file}")
    try:
        with open(config_file, 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error reading {config_file}: {e}")
        return

    render_config = data.get('render_config', {})
    path_obj = render_config.get('path')
    
    if path_obj is None:
        print(f"No path found in render_config for {dataset_id}")
        return
    if not isinstance(path_obj, dict):
        print(f"Invalid path payload in {config_file}; expected object under 'path'.")
        return

    path_name = path_obj.get('name', 'Unnamed')
    print(f"Analyzing path: {path_name} ({dataset_id})")
    
    # Setup Sampler
    camera_utils.set_camera_path(path_obj)
    
    steps = 500
    dt = 1.0 / steps
    
    progress = []
    
    # Data arrays
    pos_x, pos_y, pos_l = [], [], []
    
    # Sampling loop
    # Optimized: Batch sample
    progress_values = [i / steps for i in range(steps + 1)]
    print(f"Sampling {len(progress_values)} points...")
    
    cameras, _ = camera_utils.cameras_at_progresses(progress_values)
    
    for t, cam in zip(progress_values, cameras):
        if not cam: continue
        
        gx = cam['globalX']
        gy = cam['globalY']
        gl = cam['globalLevel']
        
        progress.append(t)
        pos_x.append(gx)
        pos_y.append(gy)
        pos_l.append(gl)
    
    # Calculate Derivatives (Central Difference)
    def derive(data, dt):
        d = []
        for i in range(len(data)):
            if i == 0:
                val = (data[1] - data[0]) / dt
            elif i == len(data) - 1:
                val = (data[-1] - data[-2]) / dt
            else:
                val = (data[i+1] - data[i-1]) / (2 * dt)
            d.append(val)
        return d

    vel_x = derive(pos_x, dt)
    vel_y = derive(pos_y, dt)
    vel_l = derive(pos_l, dt)
    
    acc_x = derive(vel_x, dt)
    acc_y = derive(vel_y, dt)
    acc_l = derive(vel_l, dt)
    
    # Plotting
    fig, axes = plt.subplots(3, 3, figsize=(18, 12))
    fig.suptitle(f"Camera Path Analysis: {dataset_id} / {path_name}", fontsize=16)
    
    # Row 1: Position
    axes[0, 0].plot(progress, pos_x, 'b')
    axes[0, 0].set_title('Position X (Global)')
    axes[0, 0].grid(True)
    
    axes[0, 1].plot(progress, pos_y, 'b')
    axes[0, 1].set_title('Position Y (Global)')
    axes[0, 1].grid(True)
    
    axes[0, 2].plot(progress, pos_l, 'b')
    axes[0, 2].set_title('Zoom Level')
    axes[0, 2].grid(True)
    
    # Row 2: Velocity
    axes[1, 0].plot(progress, vel_x, 'g')
    axes[1, 0].set_title('Velocity X')
    axes[1, 0].grid(True)
    
    axes[1, 1].plot(progress, vel_y, 'g')
    axes[1, 1].set_title('Velocity Y')
    axes[1, 1].grid(True)
    
    axes[1, 2].plot(progress, vel_l, 'g')
    axes[1, 2].set_title('Velocity Level')
    axes[1, 2].grid(True)
    
    # Row 3: Acceleration
    axes[2, 0].plot(progress, acc_x, 'r')
    axes[2, 0].set_title('Acceleration X')
    axes[2, 0].grid(True)
    
    axes[2, 1].plot(progress, acc_y, 'r')
    axes[2, 1].set_title('Acceleration Y')
    axes[2, 1].grid(True)
    
    axes[2, 2].plot(progress, acc_l, 'r')
    axes[2, 2].set_title('Acceleration Level')
    axes[2, 2].grid(True)
    
    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    
    output_file = os.path.join(ARTIFACTS_ROOT, f"{dataset_id}_path.png")
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    plt.savefig(output_file, dpi=150)
    print(f"Analysis saved to {output_file}")
    plt.close(fig) # Close to free memory

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Plot camera path for datasets")
    parser.add_argument("--dataset", help="Specific dataset ID to plot (optional)")
    args = parser.parse_args()

    # Scan for config.json files
    if args.dataset:
        search_pattern = os.path.join(DATA_ROOT, args.dataset, 'config.json')
    else:
        search_pattern = os.path.join(DATA_ROOT, '*', 'config.json')
    
    config_files = glob.glob(search_pattern)
    
    if not config_files:
        print(f"No configs found in {search_pattern}")
        return

    print(f"Found {len(config_files)} datasets.")
    
    for c_file in config_files:
        dataset_id = os.path.basename(os.path.dirname(c_file))
        plot_dataset_path(c_file, dataset_id)

if __name__ == "__main__":
    main()