import unittest
import os
import sys
import math
import unittest

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
                {"camera": {"level": 0, "tileX": 0, "tileY": 0, "offsetX": 0.5, "offsetY": 0.5}},
                {"camera": {"level": 4, "tileX": 8, "tileY": 8, "offsetX": 0.5, "offsetY": 0.5}},
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
        self.assertEqual(c0['tileX'], 0)
        self.assertEqual(c1['tileX'], 8)

        # Midpoint roughly halfway in global space and level
        self.assertTrue(0.0 < cmid['globalLevel'] < 4.0)
        self.assertTrue(0.0 < cmid['globalX'] < c1['globalX'])
        self.assertTrue(0.0 < cmid['globalY'] < c1['globalY'])

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
                {"camera": {"level": 5, "tileX": 8, "tileY": 24, "offsetX": 0.0, "offsetY": 0.0}}
            ]
        }

        cam_macro_global = sample_camera(macro_global_path)
        cam_explicit_global = sample_camera(explicit_global_path)

        self.assertEqual(cam_macro_global['tileX'], cam_explicit_global['tileX'])
        self.assertEqual(cam_macro_global['tileY'], cam_explicit_global['tileY'])
        self.assertAlmostEqual(cam_macro_global['offsetX'], cam_explicit_global['offsetX'], places=9)
        self.assertAlmostEqual(cam_macro_global['offsetY'], cam_explicit_global['offsetY'], places=9)
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
                {"camera": {"level": 3, "tileX": 4, "tileY": 4, "offsetX": 0.0, "offsetY": 0.0}}
            ]
        }

        cam_macro_mb = sample_camera(macro_mb_path)
        cam_explicit_mb = sample_camera(explicit_mb_path)

        self.assertEqual(cam_macro_mb['tileX'], cam_explicit_mb['tileX'])
        self.assertEqual(cam_macro_mb['tileY'], cam_explicit_mb['tileY'])
        self.assertAlmostEqual(cam_macro_mb['offsetX'], cam_explicit_mb['offsetX'], places=9)
        self.assertAlmostEqual(cam_macro_mb['offsetY'], cam_explicit_mb['offsetY'], places=9)
        self.assertAlmostEqual(cam_macro_mb['globalX'], cam_explicit_mb['globalX'], places=9)
        self.assertAlmostEqual(cam_macro_mb['globalY'], cam_explicit_mb['globalY'], places=9)

if __name__ == '__main__':
    unittest.main()
