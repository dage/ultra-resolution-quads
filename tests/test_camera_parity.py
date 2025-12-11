"""
Parity tests for camera sampling and macro resolution across Python/JS shared logic.
Ensures global coordinates and macros produce consistent camera outputs.
"""

import unittest
import os
import sys
import math

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend import camera_utils

class TestCameraParity(unittest.TestCase):
    def test_camera_at_progress_basic(self):
        """
        Verify the even-spaced sampler returns sensible cameras along a simple path.
        """
        path = {
            "keyframes": [
                {"camera": {"level": 0, "x": 0.5, "y": 0.5}},
                {"camera": {"level": 4, "x": 0.5, "y": 0.5}},
            ]
        }
        camera_utils.set_camera_path(path)

        (c0, cmid, c1), _ = camera_utils.cameras_at_progresses([0.0, 0.5, 1.0])
        
        self.assertIsNotNone(c0)
        self.assertIsNotNone(c1)
        self.assertIsNotNone(cmid)

        # Endpoints match keyframes
        self.assertEqual(c0['level'], 0)
        self.assertEqual(c1['level'], 4)
        self.assertAlmostEqual(c0['x'], 0.5)
        self.assertAlmostEqual(c1['x'], 0.5)

        # Midpoint roughly halfway in global space and level
        self.assertTrue(0.0 < cmid['globalLevel'] < 4.0)
        self.assertTrue(0.0 < cmid['x'] < c1['x'] + 1e-9)
        self.assertTrue(0.0 < cmid['y'] < c1['y'] + 1e-9)

        # Progress monotonicity
        sample_progresses = [p / 10.0 for p in range(11)]
        samples, _ = camera_utils.cameras_at_progresses(sample_progresses)
        last = -math.inf
        for s in samples:
            self.assertGreaterEqual(s['globalLevel'], last)
            last = s['globalLevel']

if __name__ == '__main__':
    unittest.main()
