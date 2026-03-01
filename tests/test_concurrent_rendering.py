import unittest
import os
import shutil
import tempfile
import sys
import subprocess
import time

# Add project root
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(PROJECT_ROOT)

class TestConcurrentRendering(unittest.TestCase):
    def test_render_tiles_concurrency(self):
        """
        Runs backend/render_tiles.py with workers=4 to verify fix for race conditions
        in FractalShadesRenderer temporary directory handling.
        """
        print("\n--- Test Concurrent Rendering (System Test) ---")
        
        # We use the existing 'perturbdeep_embedded_julia' dataset configuration
        # but override max_level to 1 to be fast (L0=1 tile, L1=4 tiles).
        # This is sufficient to trigger the dependency race (all 4 L1 workers will try to render L0).
        
        cmd = [
            sys.executable,
            os.path.join(PROJECT_ROOT, "backend", "render_tiles.py"),
            "--dataset", "perturbdeep_embedded_julia",
            "--max_level", "1",
            "--workers", "4",
            "--rebuild"
        ]
        
        print(f"Executing: {' '.join(cmd)}")
        
        # Capture output
        start_time = time.time()
        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True
        )
        duration = time.time() - start_time
        
        print(f"Duration: {duration:.2f}s")
        if result.returncode != 0:
            print("STDOUT:", result.stdout)
            print("STDERR:", result.stderr)
            
        self.assertEqual(result.returncode, 0, f"Render command failed with code {result.returncode}")
        self.assertNotIn("ValueError: mmap length is greater than file size", result.stderr)
        self.assertNotIn("FileNotFoundError", result.stderr)
        
        # Verify output exists
        dataset_path = os.path.join(PROJECT_ROOT, "datasets", "perturbdeep_embedded_julia")
        self.assertTrue(os.path.exists(os.path.join(dataset_path, "0", "0", "0.webp")), "L0 tile missing")
        self.assertTrue(os.path.exists(os.path.join(dataset_path, "1", "0", "0.webp")), "L1 tile missing")

if __name__ == '__main__':
    unittest.main()
