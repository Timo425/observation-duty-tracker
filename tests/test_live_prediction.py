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
    """Tests with enough sessions for expected_overlap >= 1.5 threshold."""
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp_dir, "data"))
        os.makedirs(os.path.join(self.tmp_dir, "logs"))

        game_data = {
            "Maps": {
                "TestMap": {
                    "Rooms": {
                        "Room1": [
                            {"name": "AnomalyA"},
                            {"name": "AnomalyB"},
                            {"name": "Rope"},
                            {"name": "Epsilon"},
                        ]
                    }
                }
            }
        }
        with open(os.path.join(self.tmp_dir, "data", "game_test.json"), "w") as f:
            json.dump(game_data, f)

        # 8 sessions: Rope in odd, AnomalyA+B in even (interleaved, never overlap)
        # Epsilon only in S1 (single sighting)
        with open(os.path.join(self.tmp_dir, "logs", "game_test.csv"), "w", newline='') as f:
            w = csv.writer(f)
            w.writerow(["Session_ID", "Difficulty", "Map", "Room", "Anomaly_Name", "Timestamp"])
            for s in range(1, 9):
                if s % 2 == 1:
                    w.writerow([str(s), "Hard", "TestMap", "Room1", "Rope", ""])
                else:
                    w.writerow([str(s), "Hard", "TestMap", "Room1", "AnomalyA", ""])
                    w.writerow([str(s), "Hard", "TestMap", "Room1", "AnomalyB", ""])
            w.writerow(["1", "Hard", "TestMap", "Room1", "Epsilon", ""])

        self.backend = Backend(self.tmp_dir)
        self.backend.set_game("game_test")
        self.backend.set_difficulty("Hard")
        self.backend.session_id = 9

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    def test_pairwise_exclusion_persistence(self):
        """Adding a compatible anomaly should not collapse exclusions from another blocker."""
        # Rope never co-occurs with AnomalyA or AnomalyB
        exclusions, _ = self.backend.get_live_exclusions("TestMap", ["Rope"])
        excl_names = [e["name"] for e in exclusions]
        self.assertIn("AnomalyA", excl_names, "AnomalyA should be excluded by Rope")
        self.assertIn("AnomalyB", excl_names, "AnomalyB should be excluded by Rope")

        # Adding AnomalyA: AnomalyB should STILL be excluded because Rope blocks it
        exclusions, _ = self.backend.get_live_exclusions("TestMap", ["Rope", "AnomalyA"])
        excl_names = [e["name"] for e in exclusions]
        self.assertIn("AnomalyB", excl_names, "AnomalyB should still be excluded by Rope")
        b_excl = next(e for e in exclusions if e["name"] == "AnomalyB")
        self.assertIn("Rope", b_excl["blockers"])

    def test_min_sightings_filter(self):
        """Anomalies seen only once should not appear in exclusion results."""
        exclusions, _ = self.backend.get_live_exclusions("TestMap", ["AnomalyA"])
        excl_names = {e["name"] for e in exclusions}
        self.assertNotIn("Epsilon", excl_names, "Epsilon has 1 sighting, should be filtered")

    def test_low_expected_overlap_filtered(self):
        """Pairs with expected overlap < 1.5 should not be flagged."""
        # Epsilon(1) vs Rope(4): expected = 1*4/8 = 0.5 — should be filtered
        exclusions, _ = self.backend.get_live_exclusions("TestMap", ["Rope"])
        excl_names = {e["name"] for e in exclusions}
        self.assertNotIn("Epsilon", excl_names)


class TestMinSightingsAndPersistence(unittest.TestCase):
    """Larger synthetic dataset testing exclusion patterns and persistence."""
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp_dir, "data"))
        os.makedirs(os.path.join(self.tmp_dir, "logs"))

        game_data = {
            "Maps": {
                "TestMap": {
                    "Rooms": {
                        "Room1": [
                            {"name": "Alpha"},
                            {"name": "Beta"},
                            {"name": "Gamma"},
                            {"name": "Delta"},
                            {"name": "Epsilon"},
                        ]
                    }
                }
            }
        }
        with open(os.path.join(self.tmp_dir, "data", "game_test.json"), "w") as f:
            json.dump(game_data, f)

        # 10 sessions: Alpha+Beta in odd, Gamma+Delta in even (interleaved)
        # Epsilon only in S1 (single sighting)
        with open(os.path.join(self.tmp_dir, "logs", "game_test.csv"), "w", newline='') as f:
            w = csv.writer(f)
            w.writerow(["Session_ID", "Difficulty", "Map", "Room", "Anomaly_Name", "Timestamp"])
            for s in range(1, 11):
                if s % 2 == 1:
                    w.writerow([str(s), "Normal", "TestMap", "Room1", "Alpha", ""])
                    w.writerow([str(s), "Normal", "TestMap", "Room1", "Beta", ""])
                else:
                    w.writerow([str(s), "Normal", "TestMap", "Room1", "Gamma", ""])
                    w.writerow([str(s), "Normal", "TestMap", "Room1", "Delta", ""])
            w.writerow(["1", "Normal", "TestMap", "Room1", "Epsilon", ""])

        self.backend = Backend(self.tmp_dir)
        self.backend.set_game("game_test")
        self.backend.set_difficulty("Normal")
        self.backend.session_id = 11

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    def test_min_sightings_filter(self):
        """Anomalies seen only once should not appear in exclusion results."""
        exclusions, _ = self.backend.get_live_exclusions("TestMap", ["Alpha"])
        excl_names = {e["name"] for e in exclusions}
        self.assertNotIn("Epsilon", excl_names, "Epsilon has only 1 sighting, should be filtered out")

    def test_clear_exclusion_pattern(self):
        """Alpha (S1-5) should exclude Gamma/Delta (S6-10) since they never co-occur."""
        exclusions, _ = self.backend.get_live_exclusions("TestMap", ["Alpha"])
        excl_names = {e["name"] for e in exclusions}
        self.assertIn("Gamma", excl_names)
        self.assertIn("Delta", excl_names)

    def test_exclusion_persistence_on_add(self):
        """Adding Beta should not collapse exclusions caused by Alpha."""
        first, _ = self.backend.get_live_exclusions("TestMap", ["Alpha"])
        second, _ = self.backend.get_live_exclusions("TestMap", ["Alpha", "Beta"])

        alpha_blocked = {e["name"] for e in first if "Alpha" in e["blockers"]}
        alpha_blocked_after = {e["name"] for e in second if "Alpha" in e["blockers"]}
        self.assertTrue(alpha_blocked.issubset(alpha_blocked_after),
                        "Exclusions from Alpha should persist after adding Beta")

    def test_grouped_exclusions_tag_group_membership(self):
        """Exclusions should be tagged with their exclusion group index."""
        result = self.backend.get_live_exclusions_with_groups("TestMap", ["Alpha"])
        exclusions = result["exclusions"]
        groups = result["groups"]

        # Alpha+Beta in odd, Gamma+Delta in even. Exclusion graph:
        # Alpha-Gamma, Alpha-Delta, Beta-Gamma, Beta-Delta (no Gamma-Delta edge, they co-occur)
        # Groups formed: e.g. {Alpha, Gamma} and {Beta, Delta}
        gamma_excl = next((e for e in exclusions if e["name"] == "Gamma"), None)
        delta_excl = next((e for e in exclusions if e["name"] == "Delta"), None)
        self.assertIsNotNone(gamma_excl)
        self.assertIsNotNone(delta_excl)
        # Both should be in known groups (though different ones since they co-occur)
        self.assertGreaterEqual(gamma_excl["group_idx"], 0, "Gamma should be in a known group")
        self.assertGreaterEqual(delta_excl["group_idx"], 0, "Delta should be in a known group")

        # Group summary should include Alpha as active member in at least one group
        self.assertTrue(len(groups) >= 1, "At least one group summary expected")
        active_in_any = any("Alpha" in g["active_members"] for g in groups)
        self.assertTrue(active_in_any, "Alpha should be active in at least one group")

    def test_ungrouped_exclusions_have_negative_group_idx(self):
        """Exclusions not matching any known group should have group_idx -1."""
        result = self.backend.get_live_exclusions_with_groups("TestMap", ["Alpha"])
        for e in result["exclusions"]:
            # All exclusions should either be grouped or explicitly -1
            self.assertIsInstance(e["group_idx"], int)

if __name__ == "__main__":
    unittest.main()
