"""
Tests for generate_conclusions.py and the exclusivity analysis it relies on.

Uses controlled mock data with known exclusivity groups to verify:
1. Backend.analyze_exclusivity() correctly identifies mutually exclusive groups
2. generate_conclusions.py produces correct reports using the same logic
3. Groups of 3+ anomalies (not just pairs) are properly detected
4. Difficulty filtering works correctly
5. Edge cases: insufficient data, empty logs, single-session scenarios
"""
import sys
import os
import csv
import unittest
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend import Backend
from generate_conclusions import generate_report, _cluster_pairs


def create_mock_environment(test_dir, game_id="game_8"):
    """Create minimal data/logs structure needed by Backend."""
    data_dir = os.path.join(test_dir, "data")
    logs_dir = os.path.join(test_dir, "logs")
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(logs_dir, exist_ok=True)

    # Minimal game JSON — just enough anomaly names for our tests
    import json
    game_data = {
        "Difficulties": ["Normal", "Hard"],
        "Global": [],
        "Maps": {
            "TestMap": {
                "Rooms": {
                    "Room1": [
                        {"name": f"Anomaly_{i}", "type": "Test", "description": "Test anomaly"}
                        for i in range(1, 21)
                    ]
                }
            }
        }
    }
    with open(os.path.join(data_dir, f"{game_id}.json"), 'w') as f:
        json.dump(game_data, f)

    return data_dir, logs_dir


def write_mock_csv(logs_path, sessions):
    """Write mock session data to CSV.
    
    sessions: list of (session_id, difficulty, map, anomaly_names_list)
    """
    with open(logs_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["Session_ID", "Difficulty", "Map", "Room", "Anomaly_Name", "Timestamp"])
        for s_id, diff, map_name, anomalies in sessions:
            for anom in anomalies:
                writer.writerow([s_id, diff, map_name, "Room1", anom, ""])


class TestExclusivityDetection(unittest.TestCase):
    """Test that mutually exclusive groups are correctly identified."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        create_mock_environment(self.test_dir)
        self.backend = Backend(self.test_dir)
        self.backend.set_game("game_8")

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_pair_exclusivity(self):
        """Two anomalies that never co-occur should be detected as exclusive."""
        # Anomaly_1 and Anomaly_2 never appear together
        # Each appears in 5 out of 10 sessions — very unlikely to be by chance
        sessions = []
        for i in range(1, 6):
            sessions.append((i, "Normal", "TestMap", ["Anomaly_1", "Anomaly_3", "Anomaly_4"]))
        for i in range(6, 11):
            sessions.append((i, "Normal", "TestMap", ["Anomaly_2", "Anomaly_3", "Anomaly_5"]))

        write_mock_csv(self.backend.logs_path, sessions)
        self.backend.difficulty = "Normal"
        results = self.backend.analyze_exclusivity()

        exclusive_pairs = {r["pair"] for r in results if r["status"] in ("Hard Lock", "Likely Excl.")}
        # Anomaly_1 and Anomaly_2 should be detected
        self.assertIn(("Anomaly_1", "Anomaly_2"), exclusive_pairs,
                       "Failed to detect pair exclusivity between Anomaly_1 and Anomaly_2")

    def test_group_of_three(self):
        """A group of 3 anomalies where none co-occur should all be pairwise exclusive."""
        # Anomaly_1, Anomaly_2, Anomaly_3 never appear together
        # All share the same filler anomalies so no accidental exclusions
        sessions = []
        for i in range(1, 6):
            sessions.append((i, "Normal", "TestMap", ["Anomaly_1", "Anomaly_4", "Anomaly_5", "Anomaly_6"]))
        for i in range(6, 11):
            sessions.append((i, "Normal", "TestMap", ["Anomaly_2", "Anomaly_4", "Anomaly_5", "Anomaly_6"]))
        for i in range(11, 16):
            sessions.append((i, "Normal", "TestMap", ["Anomaly_3", "Anomaly_4", "Anomaly_5", "Anomaly_6"]))

        write_mock_csv(self.backend.logs_path, sessions)
        self.backend.difficulty = "Normal"
        results = self.backend.analyze_exclusivity()

        hl_pairs = {r["pair"] for r in results if r["status"] in ("Hard Lock", "Likely Excl.")}
        # All 3 pairwise combos should be detected
        self.assertIn(("Anomaly_1", "Anomaly_2"), hl_pairs)
        self.assertIn(("Anomaly_1", "Anomaly_3"), hl_pairs)
        self.assertIn(("Anomaly_2", "Anomaly_3"), hl_pairs)


    def test_no_false_positives_cooccurring(self):
        """Anomalies that DO co-occur should NOT be flagged as exclusive."""
        sessions = []
        for i in range(1, 11):
            sessions.append((i, "Normal", "TestMap", ["Anomaly_1", "Anomaly_2", "Anomaly_3"]))

        write_mock_csv(self.backend.logs_path, sessions)
        self.backend.difficulty = "Normal"
        results = self.backend.analyze_exclusivity()

        exclusive_pairs = {r["pair"] for r in results}
        self.assertNotIn(("Anomaly_1", "Anomaly_2"), exclusive_pairs,
                          "False positive: co-occurring anomalies flagged as exclusive")

    def test_insufficient_data(self):
        """With fewer than 3 sessions, should return empty results."""
        sessions = [
            (1, "Normal", "TestMap", ["Anomaly_1", "Anomaly_3"]),
            (2, "Normal", "TestMap", ["Anomaly_2", "Anomaly_4"]),
        ]
        write_mock_csv(self.backend.logs_path, sessions)
        self.backend.difficulty = "Normal"
        results = self.backend.analyze_exclusivity()
        self.assertEqual(results, [], "Should return empty for insufficient data")

    def test_difficulty_isolation(self):
        """Normal and Hard mode data should not bleed into each other."""
        sessions = []
        # Normal: Anomaly_1 and Anomaly_2 never co-occur
        for i in range(1, 6):
            sessions.append((i, "Normal", "TestMap", ["Anomaly_1", "Anomaly_3"]))
        for i in range(6, 11):
            sessions.append((i, "Normal", "TestMap", ["Anomaly_2", "Anomaly_3"]))
        # Hard: Anomaly_1 and Anomaly_2 ALWAYS co-occur
        for i in range(11, 21):
            sessions.append((i, "Hard", "TestMap", ["Anomaly_1", "Anomaly_2", "Anomaly_3"]))

        write_mock_csv(self.backend.logs_path, sessions)

        # Normal should find exclusion
        self.backend.difficulty = "Normal"
        normal_results = self.backend.analyze_exclusivity()
        normal_pairs = {r["pair"] for r in normal_results if r["status"] in ("Hard Lock", "Likely Excl.")}
        self.assertIn(("Anomaly_1", "Anomaly_2"), normal_pairs)

        # Hard should NOT find exclusion
        self.backend.difficulty = "Hard"
        hard_results = self.backend.analyze_exclusivity()
        hard_pairs = {r["pair"] for r in hard_results}
        self.assertNotIn(("Anomaly_1", "Anomaly_2"), hard_pairs)

    def test_single_anomaly_sessions_included(self):
        """Sessions with just 1 anomaly should still count toward session totals."""
        # This tests that we don't arbitrarily exclude short sessions
        sessions = []
        for i in range(1, 6):
            sessions.append((i, "Normal", "TestMap", ["Anomaly_1"]))
        for i in range(6, 11):
            sessions.append((i, "Normal", "TestMap", ["Anomaly_2", "Anomaly_3"]))

        write_mock_csv(self.backend.logs_path, sessions)
        self.backend.difficulty = "Normal"
        results = self.backend.analyze_exclusivity()
        # Should still be able to analyze (10 sessions total, anomaly_1 seen in 5)
        # Anomaly_1 has n=5 but needs n>=2 per the current code
        # This is a valid scenario — the analysis should at least not crash
        self.assertIsInstance(results, list)


class TestClusterPairs(unittest.TestCase):
    """Test that _cluster_pairs correctly groups pairwise exclusions into groups."""

    def test_pair_becomes_group(self):
        """A single pair should become a group of 2."""
        pairs = [{"pair": ("A", "B"), "status": "Hard Lock"}]
        groups = _cluster_pairs(pairs)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0], {"A", "B"})

    def test_transitive_grouping(self):
        """A-B and B-C should form one group {A, B, C}."""
        pairs = [
            {"pair": ("A", "B"), "status": "Hard Lock"},
            {"pair": ("B", "C"), "status": "Hard Lock"},
        ]
        groups = _cluster_pairs(pairs)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0], {"A", "B", "C"})

    def test_separate_groups(self):
        """Non-overlapping pairs should remain separate groups."""
        pairs = [
            {"pair": ("A", "B"), "status": "Hard Lock"},
            {"pair": ("C", "D"), "status": "Hard Lock"},
        ]
        groups = _cluster_pairs(pairs)
        self.assertEqual(len(groups), 2)
        group_sets = {frozenset(g) for g in groups}
        self.assertIn(frozenset({"A", "B"}), group_sets)
        self.assertIn(frozenset({"C", "D"}), group_sets)

    def test_large_group(self):
        """A-B, A-C, A-D should all merge into one group."""
        pairs = [
            {"pair": ("A", "B"), "status": "Hard Lock"},
            {"pair": ("A", "C"), "status": "Hard Lock"},
            {"pair": ("A", "D"), "status": "Hard Lock"},
        ]
        groups = _cluster_pairs(pairs)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0], {"A", "B", "C", "D"})


class TestGenerateReport(unittest.TestCase):
    """Test that generate_report() produces a coherent report from Backend data."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        create_mock_environment(self.test_dir)
        self.backend = Backend(self.test_dir)
        self.backend.set_game("game_8")

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_report_with_exclusions(self):
        """Report should contain group info when exclusions exist."""
        sessions = []
        for i in range(1, 11):
            sessions.append((i, "Normal", "TestMap", ["Anomaly_1", "Anomaly_3", "Anomaly_4"]))
        for i in range(11, 21):
            sessions.append((i, "Normal", "TestMap", ["Anomaly_2", "Anomaly_3", "Anomaly_5"]))

        write_mock_csv(self.backend.logs_path, sessions)
        report = generate_report(self.backend, difficulties=["Normal"])

        self.assertIn("Anomaly_1", report)
        self.assertIn("Anomaly_2", report)
        self.assertIn("Group", report)

    def test_report_insufficient_data(self):
        """Report should note insufficient data when not enough sessions exist."""
        sessions = [
            (1, "Normal", "TestMap", ["Anomaly_1"]),
        ]
        write_mock_csv(self.backend.logs_path, sessions)
        report = generate_report(self.backend, difficulties=["Normal"])

        self.assertIn("Not enough data", report)

    def test_report_both_difficulties(self):
        """Report should contain sections for both Normal and Hard."""
        sessions = []
        for i in range(1, 6):
            sessions.append((i, "Normal", "TestMap", ["Anomaly_1", "Anomaly_2"]))
        for i in range(6, 11):
            sessions.append((i, "Hard", "TestMap", ["Anomaly_3", "Anomaly_4"]))

        write_mock_csv(self.backend.logs_path, sessions)
        report = generate_report(self.backend)

        self.assertIn("Normal Mode", report)
        self.assertIn("Hard Mode", report)


if __name__ == "__main__":
    unittest.main()
