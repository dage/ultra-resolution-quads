import subprocess
import sys
import os

def run_command(command):
    print(f"Running: {' '.join(command)}")
    try:
        subprocess.check_call(command)
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {e}")
        sys.exit(1)

def main():
    base_cmd = [sys.executable, "backend/generate_dataset.py"]
    
    print("--- Setting up Debug Quadtile Dataset ---")
    # Generate full pyramid for debug dataset (levels 0-5)
    # Note: We use 'full' mode as it's cheap and provides context for the whole area.
    # The custom path we added is for playback, not generation guidance here.
    cmd_debug = base_cmd + [
        "--dataset", "debug_quadtile",
        "--renderer", "renderers.debug_renderer:DebugQuadtileRenderer",
        "--name", "Debug Quadtile",
        "--description", "Debug tiles to verify coordinate system",
        "--max_level", "5",
        "--mode", "full"
    ]
    run_command(cmd_debug)
    
    print("\n--- Setting up Mandelbrot Deep Zoom Dataset ---")
    # Generate only tiles along the path for deep zoom (levels 0-20)
    # This respects the existing paths.json if present.
    cmd_mandelbrot = base_cmd + [
        "--dataset", "mandelbrot_deep",
        "--renderer", "renderers.mandelbrot_renderer:MandelbrotDeepZoomRenderer",
        "--name", "Mandelbrot Deep Zoom",
        "--description", "Standard Mandelbrot set with deep zoom path",
        "--max_level", "20",
        "--mode", "path"
    ]
    run_command(cmd_mandelbrot)
    
    print("\nAll datasets generated successfully!")

if __name__ == "__main__":
    # Ensure we are in the project root
    if not os.path.exists("backend/generate_dataset.py"):
        print("Error: Please run this script from the project root.")
        sys.exit(1)
        
    main()
