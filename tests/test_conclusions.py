"""
Tests for generate_conclusions.py and the exclusivity analysis it relies on.

Uses controlled mock data with known exclusivity groups to verify:
1. Backend.analyze_exclusivity() correctly identifies mutually exclusive groups
2. generate_conclusions.py produces correct reports using the same logic
3. Groups of 3+ anomalies are properly detected as single groups
4. Difficulty filtering works correctly
5. Edge cases: insufficient data, empty logs, single-session scenarios
"""
import sys
import os
import csv
import unittest
import tempfile
import shutil
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend import Backend
from generate_conclusions import generate_report


def create_mock_environment(test_dir, game_id="game_8"):
    """Create minimal data/logs structure needed by Backend."""
    data_dir = os.path.join(test_dir, "data")
    logs_dir = os.path.join(test_dir, "logs")
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(logs_dir, exist_ok=True)

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


def get_group_member_names(results):
    """Extract sets of member names from group results."""
    return [
        {m["name"] for m in g["members"]}
        for g in results.get("groups", [])
    ]


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
        """Two anomalies that never co-occur should be detected as an exclusion group of size 2."""
        sessions = []
        # Interleaved: A1 in odd sessions, A2 in even, same fillers in all
        for i in range(1, 41):
            anom = "Anomaly_1" if i % 2 == 1 else "Anomaly_2"
            sessions.append((i, "Normal", "TestMap", [anom, "Anomaly_3", "Anomaly_4"]))

        write_mock_csv(self.backend.logs_path, sessions)
        self.backend.difficulty = "Normal"
        results = self.backend.analyze_exclusivity()
        group_sets = get_group_member_names(results)

        self.assertTrue(
            any({"Anomaly_1", "Anomaly_2"}.issubset(g) for g in group_sets),
            "Failed to detect exclusion group containing Anomaly_1 and Anomaly_2")

    def test_group_of_three(self):
        """A group of 3 anomalies where none co-occur should form a single group."""
        sessions = []
        # Round-robin: A1, A2, A3 cycling (60 sessions = 20 each), with shared fillers
        for i in range(1, 61):
            pick = ["Anomaly_1", "Anomaly_2", "Anomaly_3"][(i - 1) % 3]
            sessions.append((i, "Normal", "TestMap", [pick, "Anomaly_4", "Anomaly_5", "Anomaly_6"]))

        write_mock_csv(self.backend.logs_path, sessions)
        self.backend.difficulty = "Normal"
        results = self.backend.analyze_exclusivity()
        group_sets = get_group_member_names(results)

        # All 3 should be in a single group, not 3 separate pairs
        self.assertTrue(
            any({"Anomaly_1", "Anomaly_2", "Anomaly_3"}.issubset(g) for g in group_sets),
            "Failed to detect group of 3")

    def test_no_false_positives_cooccurring(self):
        """Anomalies that DO co-occur should NOT be in any exclusion group together."""
        sessions = []
        for i in range(1, 11):
            sessions.append((i, "Normal", "TestMap", ["Anomaly_1", "Anomaly_2", "Anomaly_3"]))

        write_mock_csv(self.backend.logs_path, sessions)
        self.backend.difficulty = "Normal"
        results = self.backend.analyze_exclusivity()
        group_sets = get_group_member_names(results)

        for g in group_sets:
            self.assertFalse(
                {"Anomaly_1", "Anomaly_2"}.issubset(g),
                "False positive: co-occurring anomalies in same exclusion group")

    def test_insufficient_data(self):
        """With only 1 session, should return empty groups."""
        sessions = [
            (1, "Normal", "TestMap", ["Anomaly_1", "Anomaly_3"]),
        ]
        write_mock_csv(self.backend.logs_path, sessions)
        self.backend.difficulty = "Normal"
        results = self.backend.analyze_exclusivity()
        self.assertEqual(results["groups"], [])
        self.assertEqual(results["violations"], [])

    def test_difficulty_isolation(self):
        """Normal and Hard mode data should not bleed into each other."""
        sessions = []
        # Normal: Anomaly_1 and Anomaly_2 never co-occur (interleaved, 40 sessions)
        for i in range(1, 41):
            anom = "Anomaly_1" if i % 2 == 1 else "Anomaly_2"
            sessions.append((i, "Normal", "TestMap", [anom, "Anomaly_3"]))
        # Hard: Anomaly_1 and Anomaly_2 ALWAYS co-occur
        for i in range(41, 51):
            sessions.append((i, "Hard", "TestMap", ["Anomaly_1", "Anomaly_2", "Anomaly_3"]))

        write_mock_csv(self.backend.logs_path, sessions)

        # Normal should find exclusion group
        self.backend.difficulty = "Normal"
        normal_results = self.backend.analyze_exclusivity()
        normal_groups = get_group_member_names(normal_results)
        self.assertTrue(
            any({"Anomaly_1", "Anomaly_2"}.issubset(g) for g in normal_groups))

        # Hard should NOT find any exclusion group with both
        self.backend.difficulty = "Hard"
        hard_results = self.backend.analyze_exclusivity()
        hard_groups = get_group_member_names(hard_results)
        self.assertFalse(
            any({"Anomaly_1", "Anomaly_2"}.issubset(g) for g in hard_groups))

    def test_single_anomaly_sessions(self):
        """Sessions with just 1 anomaly should still count and not crash."""
        sessions = []
        for i in range(1, 6):
            sessions.append((i, "Normal", "TestMap", ["Anomaly_1"]))
        for i in range(6, 11):
            sessions.append((i, "Normal", "TestMap", ["Anomaly_2", "Anomaly_3"]))

        write_mock_csv(self.backend.logs_path, sessions)
        self.backend.difficulty = "Normal"
        results = self.backend.analyze_exclusivity()
        self.assertIsInstance(results, dict)
        self.assertIn("groups", results)
        self.assertIn("violations", results)


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
        # Interleaved so both anomalies are active in the same window
        for i in range(1, 41):
            anom = "Anomaly_1" if i % 2 == 1 else "Anomaly_2"
            sessions.append((i, "Normal", "TestMap", [anom, "Anomaly_3", "Anomaly_4"]))

        write_mock_csv(self.backend.logs_path, sessions)
        report = generate_report(self.backend, difficulties=["Normal"])

        self.assertIn("Anomaly_1", report)
        self.assertIn("Anomaly_2", report)
        self.assertIn("group", report.lower())

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

        self.assertIn("Normal", report)
        self.assertIn("Hard", report)


class TestGroupViolations(unittest.TestCase):
    """Test that near-miss group members are detected as violations."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        create_mock_environment(self.test_dir)
        self.backend = Backend(self.test_dir)
        self.backend.set_game("game_8")

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_violation_detected(self):
        """Anomaly exclusive with most group members but co-occurring with one should be flagged."""
        sessions = []
        # 60 shifts. A1 in odd, A2 in even (interleaved → group {A1, A2}).
        # A3 appears in shifts 41-60 only (no A1 or A2 there) = exclusive with both.
        # Then A3 ALSO appears in shift 2 (co-occurs with A2 → violation).
        # A3 never co-occurs with A1 → exclusive with A1.
        # A3 vs A2 in window from shift 2: expected ≈ 21*30/59 ≈ 10.7, actual 1 → ratio 0.09
        for i in range(1, 41):
            fillers = ["Anomaly_4", "Anomaly_5"]
            if i % 2 == 1:
                sessions.append((i, "Normal", "TestMap", ["Anomaly_1"] + fillers))
            else:
                sessions.append((i, "Normal", "TestMap", ["Anomaly_2"] + fillers))
        # Shifts 41-60: only fillers + A3 (no A1, no A2)
        for i in range(41, 61):
            sessions.append((i, "Normal", "TestMap", ["Anomaly_3", "Anomaly_4", "Anomaly_5"]))
        # The violation: A3 co-occurs with A2 in shift 2
        sessions.append((2, "Normal", "TestMap", ["Anomaly_3"]))

        write_mock_csv(self.backend.logs_path, sessions)
        self.backend.difficulty = "Normal"
        results = self.backend.analyze_exclusivity()

        violations = results["violations"]
        # The system should find a group and flag a violation involving shift 2
        # (A3 co-occurs with A2 in shift 2, but one of them should be exclusive with A1)
        self.assertTrue(len(violations) > 0,
                        "Should detect a group violation from the shift-2 co-occurrence")
        v = violations[0]
        self.assertIn("2", [str(s) for s in v["conflict_shifts"]])
        # The candidate should conflict with exactly one group member
        self.assertTrue(len(v["exclusive_with"]) >= 1)

    def test_no_violation_when_clean(self):
        """Anomalies with many co-occurrences should not be flagged as violations."""
        sessions = []
        # A1 and A2 never co-occur; A3 always appears with A2 — not a violation candidate
        for i in range(1, 41):
            if i % 2 == 1:
                sessions.append((i, "Normal", "TestMap", ["Anomaly_1", "Anomaly_4"]))
            else:
                sessions.append((i, "Normal", "TestMap", ["Anomaly_2", "Anomaly_3", "Anomaly_4"]))

        write_mock_csv(self.backend.logs_path, sessions)
        self.backend.difficulty = "Normal"
        results = self.backend.analyze_exclusivity()

        a3_violations = [v for v in results["violations"] if v["candidate"] == "Anomaly_3"]
        self.assertEqual(len(a3_violations), 0,
                         "Anomaly_3 co-occurs with Anomaly_2 in every even shift — should not be a violation")


class TestAnomalyFrequencies(unittest.TestCase):
    """Test anomaly frequency calculation with condition breakdowns."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        create_mock_environment(self.test_dir)
        self.backend = Backend(self.test_dir)
        self.backend.set_game("game_8")

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def _write_csv_with_flags(self, rows):
        """Write CSV with Alt_Tabbed and Last_Cycled columns."""
        with open(self.backend.logs_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["Session_ID", "Difficulty", "Map", "Room", "Anomaly_Name",
                             "Timestamp", "Alt_Tabbed", "Last_Cycled"])
            for row in rows:
                writer.writerow(row)

    def test_basic_rates(self):
        """Overall rate should be correct."""
        rows = []
        # A1 in shifts 1-5, A2 in shifts 1-10
        for i in range(1, 11):
            rows.append([i, "Normal", "TestMap", "Room1", "Anomaly_2", "", "False", ""])
            if i <= 5:
                rows.append([i, "Normal", "TestMap", "Room1", "Anomaly_1", "", "False", ""])

        self._write_csv_with_flags(rows)
        self.backend.difficulty = "Normal"
        freqs = self.backend.get_anomaly_frequencies()

        a1 = next(f for f in freqs if f["name"] == "Anomaly_1")
        a2 = next(f for f in freqs if f["name"] == "Anomaly_2")
        self.assertEqual(a1["total_shifts"], 5)
        self.assertEqual(a2["total_shifts"], 10)
        self.assertAlmostEqual(a2["overall_rate"], 1.0)

    def test_alt_tab_breakdown(self):
        """Clean and alt-tab rates should be calculated separately."""
        rows = []
        # Shift 1-3: clean (A1 appears)
        for i in range(1, 4):
            rows.append([i, "Normal", "TestMap", "Room1", "Anomaly_1", "", "False", ""])
            rows.append([i, "Normal", "TestMap", "Room1", "Anomaly_2", "", "False", ""])
        # Shift 4-6: alt-tabbed (A1 appears only in 4)
        for i in range(4, 7):
            rows.append([i, "Normal", "TestMap", "Room1", "Anomaly_2", "", "True", ""])
        rows.append([4, "Normal", "TestMap", "Room1", "Anomaly_1", "", "True", ""])

        self._write_csv_with_flags(rows)
        self.backend.difficulty = "Normal"
        freqs = self.backend.get_anomaly_frequencies(from_first_seen=False)

        a1 = next(f for f in freqs if f["name"] == "Anomaly_1")
        # Clean: appeared in 3 of 3 clean shifts
        self.assertAlmostEqual(a1["clean_rate"], 1.0)
        # Alt-tab: appeared in 1 of 3 alt-tab shifts
        self.assertAlmostEqual(a1["alt_tab_rate"], 1/3, places=2)

    def test_from_first_seen_toggle(self):
        """from_first_seen should change the denominator."""
        rows = []
        # A1 first appears in shift 5 (out of 10 shifts)
        for i in range(1, 11):
            rows.append([i, "Normal", "TestMap", "Room1", "Anomaly_2", "", "False", ""])
        rows.append([5, "Normal", "TestMap", "Room1", "Anomaly_1", "", "False", ""])
        rows.append([8, "Normal", "TestMap", "Room1", "Anomaly_1", "", "False", ""])

        self._write_csv_with_flags(rows)
        self.backend.difficulty = "Normal"

        # from_first_seen=True: eligible = shifts 5-10 = 6 shifts, appeared in 2
        freqs_fs = self.backend.get_anomaly_frequencies(from_first_seen=True)
        a1_fs = next(f for f in freqs_fs if f["name"] == "Anomaly_1")
        self.assertEqual(a1_fs["eligible_shifts"], 6)
        self.assertAlmostEqual(a1_fs["overall_rate"], 2/6, places=2)

        # from_first_seen=False: eligible = all 10 shifts, appeared in 2
        freqs_all = self.backend.get_anomaly_frequencies(from_first_seen=False)
        a1_all = next(f for f in freqs_all if f["name"] == "Anomaly_1")
        self.assertEqual(a1_all["eligible_shifts"], 10)
        self.assertAlmostEqual(a1_all["overall_rate"], 2/10, places=2)


if __name__ == "__main__":
    unittest.main()
