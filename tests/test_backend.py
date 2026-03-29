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
        results_norm = backend.analyze_exclusivity()
        groups_norm = [{m["name"] for m in g["members"]} for g in results_norm["groups"]]

        print(f"\nChecking Normal Mode (Ground Truth: {self.g_norm})")
        gt_norm_set = set(self.g_norm)
        found_norm_gt = any(gt_norm_set.issubset(g) for g in groups_norm)

        # Check all GT pairs appear in some group
        for g in groups_norm:
            matched = gt_norm_set & g
            if len(matched) >= 2:
                for a in matched:
                    print(f"SUCCESS: Found Normal GT Member '{a}' in group")
                found_norm_gt = True

            # Ensure no Hard GT members are in a group together
            hard_in_group = set(self.g_hard) & g
            if len(hard_in_group) >= 2:
                self.fail(f"Contamination: Hard mode group members {hard_in_group} found in Normal mode group!")

        self.assertTrue(found_norm_gt, "Normal mode analysis failed to find its ground truth group.")

        # Test Hard Mode
        backend.set_difficulty("Hard")
        results_hard = backend.analyze_exclusivity()
        groups_hard = [{m["name"] for m in g["members"]} for g in results_hard["groups"]]

        print(f"\nChecking Hard Mode (Ground Truth: {self.g_hard})")
        gt_hard_set = set(self.g_hard)
        found_hard_gt = any(gt_hard_set.issubset(g) for g in groups_hard)

        for g in groups_hard:
            matched = gt_hard_set & g
            if len(matched) >= 2:
                for a in matched:
                    print(f"SUCCESS: Found Hard GT Member '{a}' in group")
                found_hard_gt = True

            norm_in_group = set(self.g_norm) & g
            if len(norm_in_group) >= 2:
                self.fail(f"Contamination: Normal mode group members {norm_in_group} found in Hard mode group!")

        self.assertTrue(found_hard_gt, "Hard mode analysis failed to find its ground truth group.")

if __name__ == "__main__":
    unittest.main()
