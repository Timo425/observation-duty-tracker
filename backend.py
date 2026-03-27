import csv
import os
import json
import math
from collections import defaultdict
from datetime import datetime

class Backend:
    def __init__(self, base_dir=None):
        if base_dir is None:
            # Assumes base_dir is where the script is
            self.base_dir = os.path.dirname(os.path.abspath(__file__))
        else:
            self.base_dir = base_dir
            
        self.config_path = os.path.join(self.base_dir, "app_config.json")
        self.game_id = "game_8"
        self.data_path = ""
        self.logs_path = ""
        self.data = {}
        self.session_id = 1
        self.difficulty = "Normal"
        self.last_map = ""
        
        self.load_config() # This will set game_id and paths
    def set_game(self, game_id):
        self.game_id = game_id
        self.data_path = os.path.join(self.base_dir, "data", f"{self.game_id}.json")
        self.logs_path = os.path.join(self.base_dir, "logs", f"{self.game_id}.csv")
        
        os.makedirs(os.path.dirname(self.data_path), exist_ok=True)
        os.makedirs(os.path.dirname(self.logs_path), exist_ok=True)
        self.ensure_csv_header()
        
        self.data = self.load_master_data()
        self.anomaly_to_room = {}
        if self.data:
            for glob_anom in self.data.get("Global", []):
                self.anomaly_to_room[glob_anom["name"]] = "Global"
            for map_name, map_data in self.data.get("Maps", {}).items():
                for room_name, room_anoms in map_data.get("Rooms", {}).items():
                    for anom in room_anoms:
                        self.anomaly_to_room[anom["name"]] = room_name

    def save_config(self):
        with open(self.config_path, 'w') as f:
            json.dump({
                "Session_ID": self.session_id,
                "Difficulty": self.difficulty,
                "Last_Map": self.last_map,
                "Game_ID": self.game_id
            }, f)

    def load_config(self):
        config = {}
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    config = json.load(f)
            except: pass
        
        self.session_id = config.get("Session_ID", 1)
        self.difficulty = config.get("Difficulty", "Normal")
        self.last_map = config.get("Last_Map", "")
        self.game_id = config.get("Game_ID", "game_8")
        self.set_game(self.game_id)
        return config

    def set_map(self, map_name):
        self.last_map = map_name
        self.save_config()

    def load_master_data(self):
        if not os.path.exists(self.data_path):
            return {}
        with open(self.data_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def save_master_data(self):
        if not self.data_path: return
        with open(self.data_path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=4, ensure_ascii=False)

    def ensure_csv_header(self):
        if not os.path.exists(self.logs_path) or os.stat(self.logs_path).st_size == 0:
            with open(self.logs_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["Session_ID", "Difficulty", "Map", "Room", "Anomaly_Name", "Timestamp"])

    def set_difficulty(self, difficulty):
        self.difficulty = difficulty
        self.save_config()

    def set_session(self, session_id):
        self.session_id = session_id
        self.save_config()

    def get_all_sessions(self):
        ids = set()
        if os.path.exists(self.logs_path):
            with open(self.logs_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try: ids.add(int(row["Session_ID"]))
                    except: continue
        return sorted(list(ids))

    def increment_session(self):
        existing = self.get_all_sessions()
        max_id = max(existing) if existing else 0
        self.session_id = max_id + 1
        self.save_config()
        return self.session_id

    def delete_current_session(self):
        if not os.path.exists(self.logs_path):
            return
        rows = []
        with open(self.logs_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if int(row["Session_ID"]) != self.session_id:
                    rows.append(row)
        with open(self.logs_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=["Session_ID", "Difficulty", "Map", "Room", "Anomaly_Name", "Timestamp"])
            writer.writeheader()
            writer.writerows(rows)

    def add_observation(self, map_name, room_name, anomaly_name):
        if self.is_logged_in_current_session(map_name, room_name, anomaly_name):
            return False
        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        with open(self.logs_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([self.session_id, self.difficulty, map_name, room_name, anomaly_name, timestamp])
        return True

        return True

    def undo_observation(self, map_name, room_name, anomaly_name):
        if not os.path.exists(self.logs_path): return False
        rows = []
        removed = False
        with open(self.logs_path, 'r', encoding='utf-8') as f:
            reader = list(csv.DictReader(f))
            for row in reversed(reader):
                if not removed and \
                   int(row["Session_ID"]) == self.session_id and \
                   row["Difficulty"] == self.difficulty and \
                   row["Map"] == map_name and \
                   row["Room"] == room_name and \
                   row["Anomaly_Name"] == anomaly_name:
                    removed = True
                    continue
                rows.append(row)
        if removed:
            with open(self.logs_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=["Session_ID", "Difficulty", "Map", "Room", "Anomaly_Name", "Timestamp"])
                writer.writeheader()
                writer.writerows(reversed(rows))
        return removed

    def is_logged_in_current_session(self, map_name, room_name, anomaly_name):
        if not os.path.exists(self.logs_path): return False
        with open(self.logs_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if int(row["Session_ID"]) == self.session_id and \
                   row["Difficulty"] == self.difficulty and \
                   row["Map"] == map_name and \
                   row["Room"] == room_name and \
                   row["Anomaly_Name"] == anomaly_name:
                    return True
        return False

    def get_last_activity(self):
        last_time = "Never"
        if os.path.exists(self.logs_path):
            with open(self.logs_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if int(row["Session_ID"]) == self.session_id:
                        last_time = row.get("Timestamp", "N/A")
        return last_time

    def get_counts(self, map_name=None, room_name=None):
        counts = defaultdict(int)
        if not os.path.exists(self.logs_path): return counts
        with open(self.logs_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["Difficulty"] == self.difficulty:
                    if map_name and row["Map"] != map_name: continue
                    if room_name and row["Room"] != room_name: continue
                    counts[row["Anomaly_Name"]] += 1
        return counts

    def add_new_anomaly(self, map_name, room_name, anom_name, anom_type="Unknown", description=""):
        # 1. Update JSON
        new_entry = {
            "name": anom_name,
            "type": anom_type,
            "description": description
        }
        
        target_list = []
        if room_name == "Global":
            target_list = self.data.setdefault("Global", [])
        else:
            # Navigate to the correct room list
            maps = self.data.setdefault("Maps", {})
            m = maps.setdefault(map_name, {"Rooms": {}})
            rooms = m.setdefault("Rooms", {})
            target_list = rooms.setdefault(room_name, [])

        # Prevent duplicates in the anomaly list itself
        if any(a["name"].lower() == anom_name.lower() for a in target_list):
            return False # Already exists

        target_list.append(new_entry)
        self.save_master_data()
        return True

    def get_current_session_anomalies(self, map_name):
        anoms = []
        if not os.path.exists(self.logs_path): return anoms
        with open(self.logs_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if int(row["Session_ID"]) == self.session_id and \
                   row["Difficulty"] == self.difficulty and \
                   row["Map"] == map_name:
                    anoms.append(row["Anomaly_Name"])
        return anoms

    def get_stats(self, map_name):
        stats = {"total_sessions": 0, "anomaly_sessions": defaultdict(set)}
        if not os.path.exists(self.logs_path): return stats
        
        sessions = set()
        with open(self.logs_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["Difficulty"] == self.difficulty and row["Map"] == map_name:
                    s_id = row["Session_ID"]
                    sessions.add(s_id)
                    stats["anomaly_sessions"][row["Anomaly_Name"]].add(s_id)
        
        stats["total_sessions"] = len(sessions)
        return stats

    def get_live_exclusions(self, map_name, current_anoms):
        if not current_anoms: return []
        stats = self.get_stats(map_name)
        N = stats["total_sessions"]
        if N < 2: return []

        # Sessions where at least one current anomaly appeared
        S_current = set()
        for a in current_anoms:
            S_current.update(stats["anomaly_sessions"].get(a, set()))
        
        n_current = len(S_current)
        if n_current == 0: return []

        exclusions = []
        all_possible_anoms = set()
        # Get all anomalies for this map (including Global)
        all_possible_anoms.update(a["name"] for a in self.data.get("Global", []))
        map_rooms = self.data.get("Maps", {}).get(map_name, {}).get("Rooms", {})
        for r_name, r_anoms in map_rooms.items():
            all_possible_anoms.update(a["name"] for a in r_anoms)

        def log_comb(n, k):
            if k < 0 or k > n: return -float('inf')
            return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)

        for a_name in all_possible_anoms:
            if a_name in current_anoms: continue
            
            S_a = stats["anomaly_sessions"].get(a_name, set())
            n_a = len(S_a)
            if n_a == 0: continue

            # Expected overlap E = (n_current * n_a) / N
            expected_overlap = (n_current * n_a) / N

            # Check if they co-occur'd in ANY past session
            if not (S_current & S_a):
                # Probability of zero intersection by chance (Hypergeometric p-value)
                if N - n_current < n_a:
                    p_value = 0
                else:
                    lp = log_comb(N - n_current, n_a) - log_comb(N, n_a)
                    p_value = math.exp(lp)
                
                likelihood = 1 - p_value
                exclusions.append({
                    "name": a_name,
                    "count": n_a,
                    "expected_overlap": expected_overlap,
                    "likelihood": likelihood,
                    "rank_score": expected_overlap,
                    "N": N,
                    "current_set": list(current_anoms)
                })

        exclusions.sort(key=lambda x: x["rank_score"], reverse=True)
        return exclusions

    def analyze_exclusivity(self):
        sessions = defaultdict(set)
        anom_to_sessions = defaultdict(set)
        anom_to_room_counts = defaultdict(lambda: defaultdict(int))
        all_anomalies = set()
        if not os.path.exists(self.logs_path): return []
        
        with open(self.logs_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["Difficulty"] != self.difficulty: continue
                s_id = row["Session_ID"]; a_name = row["Anomaly_Name"]; room = row["Room"]
                sessions[s_id].add(a_name)
                anom_to_sessions[a_name].add(s_id)
                anom_to_room_counts[a_name][room] += 1
                all_anomalies.add(a_name)
        
        def format_rooms(anom):
            rooms = anom_to_room_counts[anom]
            parts = [f"{r} x{c}" for r, c in sorted(rooms.items(), key=lambda x: x[1], reverse=True)]
            return ", ".join(parts) if parts else "Unknown"

        total_sessions = len(sessions)
        if total_sessions < 3: return []
        
        anom_list = sorted(list(all_anomalies))
        results = []
        freq = {a: len(anom_to_sessions[a]) for a in anom_list}
        
        for i in range(len(anom_list)):
            a1 = anom_list[i]; s1 = anom_to_sessions[a1]; n1 = freq[a1]
            if n1 < 2: continue
            for j in range(i + 1, len(anom_list)):
                a2 = anom_list[j]; s2 = anom_to_sessions[a2]; n2 = freq[a2]
                if n2 < 2: continue
                
                actual_overlap = len(s1 & s2)
                expected_overlap = (n1 * n2) / total_sessions
                
                if actual_overlap == 0:
                    lp = math.lgamma(total_sessions - n1 + 1) + math.lgamma(total_sessions - n2 + 1) - \
                         math.lgamma(total_sessions + 1) - math.lgamma(total_sessions - n1 - n2 + 1) if (total_sessions - n1 >= n2) else -float('inf')
                    likelihood = 1 - math.exp(lp) if lp != -float('inf') else 1.0
                    
                    results.append({
                        "pair": (a1, a2),
                        "room1": format_rooms(a1),
                        "room2": format_rooms(a2),
                        "n1": n1, "n2": n2,
                        "expected": expected_overlap,
                        "actual": 0,
                        "likelihood": likelihood,
                        "N": total_sessions,
                        "status": "Hard Lock" if likelihood > 0.95 else "Likely Excl."
                    })
                elif actual_overlap == 1 and expected_overlap > 5.0:
                    results.append({
                        "pair": (a1, a2),
                        "room1": format_rooms(a1),
                        "room2": format_rooms(a2),
                        "n1": n1, "n2": n2,
                        "expected": expected_overlap,
                        "actual": 1,
                        "likelihood": 0,
                        "N": total_sessions,
                        "status": "POTENTIAL ERROR"
                    })
        
        results.sort(key=lambda x: x["expected"], reverse=True)
        return results
