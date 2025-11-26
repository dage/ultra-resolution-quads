import unittest
import subprocess
import json
import os
import sys

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend import camera_utils

class TestCameraParity(unittest.TestCase):
    def test_interpolation_parity(self):
        """
        Verifies that python camera_utils.interpolate_camera produces 
        the EXACT same values as the JS implementation.
        """
        
        k1 = {'level': 0, 'tileX': 0, 'tileY': 0, 'offsetX': 0.5, 'offsetY': 0.5}
        k2 = {'level': 4, 'tileX': 8, 'tileY': 8, 'offsetX': 0.5, 'offsetY': 0.5}
        t = 0.5
        
        input_data = json.dumps({'k1': k1, 'k2': k2, 't': t})
        
        # Run Node script
        process = subprocess.Popen(
            ['node', 'tests/node_camera_impl.js'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = process.communicate(input=input_data)
        
        if process.returncode != 0:
            self.fail(f"Node script failed: {stderr}")
            
        js_result = json.loads(stdout)
        py_result = camera_utils.interpolate_camera(k1, k2, t)
        
        # Compare
        # Allow tiny float epsilon differences
        self.assertEqual(js_result['level'], py_result['level'])
        self.assertAlmostEqual(js_result['zoomOffset'], py_result['zoomOffset'], places=7)
        self.assertEqual(js_result['tileX'], py_result['tileX'])
        self.assertEqual(js_result['tileY'], py_result['tileY'])
        self.assertAlmostEqual(js_result['offsetX'], py_result['offsetX'], places=7)
        self.assertAlmostEqual(js_result['offsetY'], py_result['offsetY'], places=7)
        
        print("\nParity Check Passed: Python and JS math match.")

if __name__ == '__main__':
    unittest.main()
