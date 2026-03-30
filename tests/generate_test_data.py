"""
Deterministic test data generator for the UI test launcher.

Generates game_test.csv and game_test_failures.csv with known patterns:
- Exclusion Group 1 (size 3): {Wall color, Painting, Curtains} — never co-occur
- Exclusion Group 2 (size 2): {Fridge, Dishes} — never co-occur
- Exclusion Group 3 (size 3): {Coat rack, Umbrella stand, Welcome mat} — never co-occur
- Exclusion Group 4 (size 5): {Dust cloud, Old painting, Trunk, Rocking chair, Music box}
- Deliberate mistakes: shifts 12 and 19 have Wall color + Painting together
- Alt-tab: shifts 1-5 all True, 6-40 all False, shift 15 mixed
- Camera cycling: shifts 10, 14, 18, 22 have Last_Cycled set
"""
import csv
import os
import json
import random

SEED = 42
NUM_SHIFTS = 100

# Exclusion rules
EXCL_GROUP_1 = {"Wall color", "Painting", "Curtains"}
EXCL_GROUP_2 = {"Fridge", "Dishes"}
EXCL_GROUP_3 = {"Coat rack", "Umbrella stand", "Welcome mat"}
EXCL_GROUP_4 = {"Dust cloud", "Old painting", "Trunk", "Rocking chair", "Music box"}
# Shifts where exclusion group 1 is deliberately broken (user errors)
MISTAKE_SHIFTS = {12, 19}
# Alt-tab: True for shifts 1-5, mixed for 15, False otherwise
ALT_TAB_FULL = {1, 2, 3, 4, 5}
ALT_TAB_MIXED = {15}  # first 5 clean, rest alt-tabbed
# Camera cycling shifts
CYCLED_SHIFTS = {10, 14, 18, 22}


def generate(base_dir):
    rng = random.Random(SEED)

    data_path = os.path.join(base_dir, "data", "game_test.json")
    csv_path = os.path.join(base_dir, "logs", "game_test.csv")
    fail_path = os.path.join(base_dir, "logs", "game_test_failures.csv")

    with open(data_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Build anomaly → room mapping
    anom_room = {}
    for a in data.get("Global", []):
        anom_room[a["name"]] = "Global"
    for map_data in data.get("Maps", {}).values():
        for room, anoms in map_data.get("Rooms", {}).items():
            for a in anoms:
                anom_room[a["name"]] = room

    all_anomalies = list(anom_room.keys())
    all_exclusive = EXCL_GROUP_1 | EXCL_GROUP_2 | EXCL_GROUP_3 | EXCL_GROUP_4
    non_exclusive = [a for a in all_anomalies if a not in all_exclusive]

    # Schedule helper: randomly pick one group member per shift
    def make_schedule(members, appearance_rate=0.90, skip_shifts=None):
        members = sorted(members)  # deterministic order
        schedule = {}
        for shift in range(1, NUM_SHIFTS + 1):
            if skip_shifts and shift in skip_shifts:
                schedule[shift] = None
            elif rng.random() < appearance_rate:
                schedule[shift] = rng.choice(members)
            else:
                schedule[shift] = None
        return schedule

    g1_schedule = make_schedule(EXCL_GROUP_1, 0.90, skip_shifts=MISTAKE_SHIFTS)
    g2_schedule = make_schedule(EXCL_GROUP_2, 0.85)
    g3_schedule = make_schedule(EXCL_GROUP_3, 0.90)
    g4_schedule = make_schedule(EXCL_GROUP_4, 0.90)

    rows = []
    for shift in range(1, NUM_SHIFTS + 1):
        num_anoms = rng.randint(18, 25)
        selected = set()

        # Add scheduled exclusion group members
        for schedule in [g1_schedule, g2_schedule, g3_schedule, g4_schedule]:
            if schedule.get(shift):
                selected.add(schedule[shift])

        # Deliberate mistakes: force both Wall color and Painting
        if shift in MISTAKE_SHIFTS:
            selected -= EXCL_GROUP_1  # clear any group 1 member
            selected.add("Wall color")
            selected.add("Painting")

        # Fill rest from non-exclusive pool
        pool = [a for a in non_exclusive if a not in selected]
        rng.shuffle(pool)
        while len(selected) < num_anoms and pool:
            selected.add(pool.pop())

        # Deterministic order for reproducibility
        selected = sorted(selected)

        # Timestamps and flags
        base_ts = f"{shift:02d}.03.2026 20"
        cycled_ts = "29.03.2026 20:00:00" if shift in CYCLED_SHIFTS else ""

        for i, anom in enumerate(selected):
            minutes = i * 2
            ts = f"{base_ts}:{minutes:02d}:00"

            if shift in ALT_TAB_FULL:
                alt = "True"
            elif shift in ALT_TAB_MIXED:
                alt = "False" if i < 5 else "True"
            else:
                alt = "False"

            rows.append({
                "Session_ID": shift,
                "Difficulty": "Normal",
                "Map": "TestHouse",
                "Room": anom_room[anom],
                "Anomaly_Name": anom,
                "Timestamp": ts,
                "Alt_Tabbed": alt,
                "Last_Cycled": cycled_ts,
            })

    # Write CSV
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=[
            "Session_ID", "Difficulty", "Map", "Room",
            "Anomaly_Name", "Timestamp", "Alt_Tabbed", "Last_Cycled"
        ])
        writer.writeheader()
        writer.writerows(rows)

    # Write failures CSV
    with open(fail_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            "Session_ID", "Map", "Difficulty",
            "Room1", "Type1", "Linked1",
            "Room2", "Type2", "Linked2",
            "Room3", "Type3", "Linked3",
            "Timestamp"
        ])
        writer.writerow([
            5, "TestHouse", "Normal",
            "Living Room", "Light Anomaly", "Lamp",
            "Kitchen", "Object Movement", "Knife block",
            "Bedroom", "Object Replacement", "Mirror",
            "25.03.2026 20:00:00"
        ])

    return csv_path, fail_path


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    csv_path, fail_path = generate(base_dir)
    print(f"Generated: {csv_path}")
    print(f"Generated: {fail_path}")
