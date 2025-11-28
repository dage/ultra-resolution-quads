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
        camera_utils.set_camera_path(path, internal_resolution=500)

        c0, cmid, c1 = camera_utils.cameras_at_progresses([0.0, 0.5, 1.0])
        
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
        samples = camera_utils.cameras_at_progresses(sample_progresses)
        last = -math.inf
        for s in samples:
            self.assertGreaterEqual(s['globalLevel'], last)
            last = s['globalLevel']

    def test_macro_parity(self):
        """
        Macros should resolve to the same camera as explicit tile/offset definitions.
        """
        def sample_camera(path):
            camera_utils.set_camera_path(path, internal_resolution=100)
            return camera_utils.camera_at_progress(0.0)

        # Global macro vs explicit
        macro_global_path = {
            "keyframes": [
                {"camera": {"macro": "global", "level": 5, "globalX": 0.25, "globalY": 0.75}}
            ]
        }
        explicit_global_path = {
            "keyframes": [
                {"camera": {"level": 5, "x": 0.25, "y": 0.75}}
            ]
        }

        cam_macro_global = sample_camera(macro_global_path)
        cam_explicit_global = sample_camera(explicit_global_path)

        self.assertAlmostEqual(cam_macro_global['x'], cam_explicit_global['x'], places=9)
        self.assertAlmostEqual(cam_macro_global['y'], cam_explicit_global['y'], places=9)
        self.assertAlmostEqual(cam_macro_global['globalX'], cam_explicit_global['globalX'], places=9)
        self.assertAlmostEqual(cam_macro_global['globalY'], cam_explicit_global['globalY'], places=9)

        # Mandelbrot macro vs equivalent global position at center (-0.75 + 0i maps to 0.5, 0.5)
        macro_mb_path = {
            "keyframes": [
                {"camera": {"macro": "mandelbrot", "level": 3, "re": -0.75, "im": 0.0}}
            ]
        }
        explicit_mb_path = {
            "keyframes": [
                {"camera": {"level": 3, "x": 0.5, "y": 0.5}}
            ]
        }

        cam_macro_mb = sample_camera(macro_mb_path)
        cam_explicit_mb = sample_camera(explicit_mb_path)

        self.assertAlmostEqual(cam_macro_mb['x'], cam_explicit_mb['x'], places=9)
        self.assertAlmostEqual(cam_macro_mb['y'], cam_explicit_mb['y'], places=9)
        self.assertAlmostEqual(cam_macro_mb['globalX'], cam_explicit_mb['globalX'], places=9)
        self.assertAlmostEqual(cam_macro_mb['globalY'], cam_explicit_mb['globalY'], places=9)

if __name__ == '__main__':
    unittest.main()
