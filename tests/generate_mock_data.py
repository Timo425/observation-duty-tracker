import json
import csv
import os
import random

def generate_mock_data(tracker_dir, output_csv, num_sessions=200):
    master_path = os.path.join(tracker_dir, "data", "game_8.json")
    with open(master_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    all_anomalies = []
    for a in data.get("Global", []):
        all_anomalies.append(a["name"])
    for map_data in data.get("Maps", {}).values():
        for room_anoms in map_data.get("Rooms", {}).values():
            for a in room_anoms:
                all_anomalies.append(a["name"])
    
    all_anomalies = list(set(all_anomalies))

    # Groups for Normal Mode
    g_norm = [all_anomalies[0], all_anomalies[1], all_anomalies[2]]
    # Groups for Hard Mode (Different!)
    g_hard = [all_anomalies[10], all_anomalies[11], all_anomalies[12]]
    
    with open(output_csv, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["Session_ID", "Difficulty", "Map", "Room", "Anomaly_Name"])

        for session_id in range(1, num_sessions + 1):
            difficulty = "Normal" if session_id <= num_sessions // 2 else "Hard"
            num_anomalies = random.randint(27, 30)
            
            included = set()
            active_group = g_norm if difficulty == "Normal" else g_hard
            
            if random.random() < 0.8: # High chance to see a group member
                member = random.choice(active_group)
                included.add(member)
            
            # Fill remaining slots with random anomalies (not in any test group)
            exclude = set(g_norm) | set(g_hard)
            pool = [a for a in all_anomalies if a not in exclude]
            
            while len(included) < num_anomalies:
                a = random.choice(pool)
                included.add(a)
                pool.remove(a)
            
            for anom in included:
                writer.writerow([session_id, difficulty, "Mock Map", "Mock Room", anom])

    return g_norm, g_hard

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_session_logs.csv")
    generate_mock_data(base_dir, output)
