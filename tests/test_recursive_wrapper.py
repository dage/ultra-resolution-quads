import unittest
import os
import shutil
import tempfile
import sys
import threading
from PIL import Image
import time

# Add project root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock constants if needed, but we rely on backend.constants via renderer_utils
from backend.renderer_utils import RecursiveParentRendererWrapper

class MockRenderer:
    def __init__(self, tile_size=256):
        self.tile_size = tile_size
        self.calls = []
        self.lock = threading.Lock()

    def render(self, level, x, y):
        # Simulate work
        time.sleep(0.01)
        with self.lock:
            self.calls.append((level, x, y))
        # Return a simple solid color image
        return Image.new('RGB', (self.tile_size, self.tile_size), color=(50, 50, 50))

class TestRecursiveWrapper(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.mock_renderer = MockRenderer()
        self.wrapper = RecursiveParentRendererWrapper(self.mock_renderer, self.test_dir)

    def tearDown(self):
        try:
            shutil.rmtree(self.test_dir)
        except OSError:
            pass

    def test_recursive_generation(self):
        """
        Requesting Level 2 should verify/generate Level 1, which verifies/generates Level 0.
        """
        print("\n--- Test Recursive Generation (L2 -> L1 -> L0) ---")
        # Request Level 2. (0,0)
        self.wrapper.render(2, 0, 0)
        
        calls = self.mock_renderer.calls
        print(f"Renderer calls: {calls}")
        
        # We expect L0, L1, L2 to be rendered in that order of *completion*.
        # 1. wrapper(2) -> calls wrapper(1)
        # 2. wrapper(1) -> calls wrapper(0)
        # 3. wrapper(0) -> calls real(0) -> RETURNS IMG0
        # 4. wrapper(1) -> saves IMG0 (L0 file created) -> calls real(1) -> RETURNS IMG1
        # 5. wrapper(2) -> saves IMG1 (L1 file created) -> calls real(2) -> RETURNS IMG2
        
        self.assertTrue((0, 0, 0) in calls, "Level 0 should be rendered")
        self.assertTrue((1, 0, 0) in calls, "Level 1 should be rendered")
        self.assertTrue((2, 0, 0) in calls, "Level 2 should be rendered")
        
        # Verify files exist on disk (Parents L0 and L1 must be saved)
        l0_path = os.path.join(self.test_dir, '0', '0', '0.webp')
        l1_path = os.path.join(self.test_dir, '1', '0', '0.webp')
        
        self.assertTrue(os.path.exists(l0_path), f"Level 0 parent tile should exist at {l0_path}")
        self.assertTrue(os.path.exists(l1_path), f"Level 1 parent tile should exist at {l1_path}")
        
        print("Success: Parents L0 and L1 were auto-generated and saved.")

    def test_concurrency_race(self):
        """
        Simulate multiple threads requesting the same missing parent.
        Ensures atomic writes prevent crashes.
        """
        print("\n--- Test Concurrency (Atomic Writes) ---")
        # Threads will request L1. This forces L0 generation.
        # They will all race to generate and write L0.
        
        errors = []
        def task():
            try:
                self.wrapper.render(1, 0, 0)
            except Exception as e:
                errors.append(e)
                
        threads = [threading.Thread(target=task) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        if errors:
            print(f"Errors occurred: {errors}")
            
        self.assertEqual(len(errors), 0, "No exceptions should occur during concurrent rendering")
        
        # Verify L0 exists
        l0_path = os.path.join(self.test_dir, '0', '0', '0.webp')
        self.assertTrue(os.path.exists(l0_path), "Level 0 parent should exist after concurrent race")
        
        l0_calls = [c for c in self.mock_renderer.calls if c == (0, 0, 0)]
        print(f"Level 0 was actually rendered {len(l0_calls)} times (redundancy is expected, crashing is not).")

if __name__ == '__main__':
    unittest.main()
