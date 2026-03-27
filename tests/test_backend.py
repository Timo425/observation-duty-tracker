import sys
import os
import unittest
import csv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from backend import Backend
from generate_mock_data import generate_mock_data

class TestDifficultyIndependence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = os.path.dirname(os.path.abspath(__file__))
        cls.base_dir = os.path.dirname(cls.test_dir)
        cls.mock_csv = os.path.join(cls.test_dir, "mock_session_logs.csv")
        
        # 200 sessions (100 Normal, 100 Hard)
        cls.g_norm, cls.g_hard = generate_mock_data(cls.base_dir, cls.mock_csv, num_sessions=200)

    def test_difficulty_filtering(self):
        backend = Backend(self.base_dir)
        backend.logs_path = self.mock_csv
        
        # Test Normal Mode
        backend.set_difficulty("Normal")
        pairs_norm = backend.analyze_exclusivity()
        
        print(f"\nChecking Normal Mode (Ground Truth: {self.g_norm})")
        found_norm_gt = False
        for p in pairs_norm:
            a1, a2 = p['pair']
            if a1 in self.g_norm and a2 in self.g_norm:
                found_norm_gt = True
                print(f"SUCCESS: Found Normal GT Pair {p['pair']}")
            # Ensure no Hard GT pairs are present
            if a1 in self.g_hard and a2 in self.g_hard:
                self.fail(f"Contamination: Hard mode group {p['pair']} found in Normal mode analysis!")

        self.assertTrue(found_norm_gt, "Normal mode analysis failed to find its ground truth group.")

        # Test Hard Mode
        backend.set_difficulty("Hard")
        pairs_hard = backend.analyze_exclusivity()
        
        print(f"\nChecking Hard Mode (Ground Truth: {self.g_hard})")
        found_hard_gt = False
        for p in pairs_hard:
            a1, a2 = p['pair']
            if a1 in self.g_hard and a2 in self.g_hard:
                found_hard_gt = True
                print(f"SUCCESS: Found Hard GT Pair {p['pair']}")
            # Ensure no Normal GT pairs are present
            if a1 in self.g_norm and a2 in self.g_norm:
                self.fail(f"Contamination: Normal mode group {p['pair']} found in Hard mode analysis!")

        self.assertTrue(found_hard_gt, "Hard mode analysis failed to find its ground truth group.")

if __name__ == "__main__":
    unittest.main()
