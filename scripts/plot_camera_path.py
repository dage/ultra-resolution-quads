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

def plot_dataset_path(path_file, dataset_id):
    print(f"Loading path from {path_file}")
    try:
        with open(path_file, 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error reading {path_file}: {e}")
        return

    path_obj = data.get('path')
    if path_obj is None:
        print(f"No path found in {dataset_id}")
        return
    if not isinstance(path_obj, dict):
        print(f"Invalid path payload in {path_file}; expected object under 'path'.")
        return

    path_name = path_obj.get('name', 'Unnamed')
    print(f"Analyzing path: {path_name} ({dataset_id})")
    
    # Setup Sampler
    camera_utils.set_camera_path(path_obj, internal_resolution=2000)
    
    steps = 500
    dt = 1.0 / steps
    
    progress = []
    
    # Data arrays
    pos_x, pos_y, pos_l = [], [], []
    
    # Sampling loop
    for i in range(steps + 1):
        t = i / steps
        cam = camera_utils.camera_at_progress(t)
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
    # Scan for paths.json files
    search_pattern = os.path.join(DATA_ROOT, '*', 'paths.json')
    path_files = glob.glob(search_pattern)
    
    if not path_files:
        print(f"No paths found in {search_pattern}")
        return

    print(f"Found {len(path_files)} datasets.")
    
    for p_file in path_files:
        dataset_id = os.path.basename(os.path.dirname(p_file))
        plot_dataset_path(p_file, dataset_id)

if __name__ == "__main__":
    main()
