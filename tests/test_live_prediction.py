import sys
import os
import unittest
import json
import csv
import tempfile
import shutil

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend import Backend

class TestLiveExclusionLogic(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.tmp_dir, "data")
        os.makedirs(self.data_dir)
        self.logs_dir = os.path.join(self.tmp_dir, "logs")
        os.makedirs(self.logs_dir)
        
        # Create a mock game_test.json
        self.game_data = {
            "Maps": {
                "Lighthouse": {
                    "Rooms": {
                        "Room1": [
                            {"name": "AnomalyA"},
                            {"name": "AnomalyB"},
                            {"name": "AnomalyC"},
                            {"name": "Rope"}
                        ]
                    }
                }
            }
        }
        with open(os.path.join(self.data_dir, "game_test.json"), "w") as f:
            json.dump(self.game_data, f)
            
        # Create a mock CSV with clear co-occurrence patterns
        # Session 1: AnomalyA, AnomalyB (Hammer A & B are friends)
        # Session 2: Rope alone
        self.logs_file = os.path.join(self.logs_dir, "game_test.csv")
        with open(self.logs_file, "w", newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["Session_ID", "Difficulty", "Map", "Room", "Anomaly_Name", "Timestamp"])
            # Session 1: A and B co-occur
            writer.writerow(["1", "Hard", "Lighthouse", "Room1", "AnomalyA", "2024-01-01 10:00:00"])
            writer.writerow(["1", "Hard", "Lighthouse", "Room1", "AnomalyB", "2024-01-01 10:05:00"])
            # Session 2: Rope is alone
            writer.writerow(["2", "Hard", "Lighthouse", "Room1", "Rope", "2024-01-01 11:00:00"])

        self.backend = Backend(self.tmp_dir)
        self.backend.set_game("game_test")
        self.backend.set_difficulty("Hard")
        self.backend.session_id = 3 # Current session is 3

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    def test_pairwise_exclusion_persistence(self):
        """
        Verify that finding an anomaly compatible with B does NOT clear B's exclusion 
        if another reported anomaly still conflicts with B.
        """
        # Scenario: We have found 'Rope'.
        # History: Rope (S2), AnomalyA (S1), AnomalyB (S1).
        # Rope has NEVER been seen with AnomalyA or AnomalyB.
        # AnomalyA HAS been seen with AnomalyB.
        
        # 1. Report Rope
        current_anoms = ["Rope"]
        exclusions = self.backend.get_live_exclusions("Lighthouse", current_anoms)
        
        excl_names = [e["name"] for e in exclusions]
        self.assertIn("AnomalyA", excl_names, "AnomalyA should be excluded by Rope")
        self.assertIn("AnomalyB", excl_names, "AnomalyB should be excluded by Rope")
        
        # 2. Now report AnomalyA alongside Rope
        current_anoms = ["Rope", "AnomalyA"]
        exclusions = self.backend.get_live_exclusions("Lighthouse", current_anoms)
        
        excl_names = [e["name"] for e in exclusions]
        # In the OLD logic, AnomalyB would be REMOVED because it co-occurs with AnomalyA.
        # In the NEW logic, AnomalyB should STAY because it still conflicts with Rope.
        
        self.assertIn("AnomalyB", excl_names, "AnomalyB should STILL be excluded because Rope conflicts with it")
        
        # Find AnomalyB in results and check blockers
        b_excl = next(e for e in exclusions if e["name"] == "AnomalyB")
        self.assertIn("Rope", b_excl["blockers"], "Rope should be listed as a blocker for AnomalyB")

class TestRealWorldScenario(unittest.TestCase):
    def setUp(self):
        # Point to the REAL repository directory
        self.base_dir = "/media/timo/Storage/Repositories/observation-duty-tracker"
        self.backend = Backend(self.base_dir)
        self.backend.set_game("game_8") # Lighthouse
        self.backend.set_difficulty("Hard")
        self.backend.session_id = 7 # The session where the issue occurred

    def test_lighthouse_hard_report_sequence(self):
        """
        Actually replicates your exact scenario from game_8.csv session 7.
        """
        # 1. Report 'Rope' (which was New in session 7)
        # Verify it triggers exclusions from history (Session 3)
        exclusions = self.backend.get_live_exclusions("Lighthouse", ["Rope"])
        self.assertTrue(len(exclusions) > 0, "Rope should trigger exclusions based on historical differences")
        
        # 2. Now add 'Green mug'
        # In the old logic, this caused the collapse.
        # In the new logic, exclusions caused by 'Rope' MUST stay.
        reports = ["Rope", "Green mug"]
        new_exclusions = self.backend.get_live_exclusions("Lighthouse", reports)
        
        # Check an anomaly that was in Session 3 (and thus NOT with Rope)
        # For example: 'Drum' or 'Axel'
        for e in new_exclusions:
            if "Rope" in e["blockers"]:
                # Success! Rope is still blocking anomalies even though Green mug was found.
                return
        
        self.fail("The exclusion list collapsed! No anomalies are being blocked by 'Rope' after adding 'Green mug'.")

if __name__ == "__main__":
    unittest.main()
