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
        self.session_id = 1
        self.max_session_id = 1
        self.session_configs = {} # {str(id): {"Map": str, "Difficulty": str}}
        self.difficulty = "Normal"
        self.last_map = ""
        self.failures_path = ""
        self.unlocked_sessions = set()
        self.window_size = "1200x800"
        
        self.load_config() # This will set game_id and paths
    def set_game(self, game_id):
        self.game_id = game_id
        self.data_path = os.path.join(self.base_dir, "data", f"{self.game_id}.json")
        self.logs_path = os.path.join(self.base_dir, "logs", f"{self.game_id}.csv")
        self.failures_path = os.path.join(self.base_dir, "logs", f"{self.game_id}_failures.csv")
        
        os.makedirs(os.path.dirname(self.data_path), exist_ok=True)
        os.makedirs(os.path.dirname(self.logs_path), exist_ok=True)
        self.ensure_csv_header()
        self.ensure_failures_header()
        
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
                "Max_Session_ID": self.max_session_id,
                "Session_Configs": self.session_configs,
                "Difficulty": self.difficulty,
                "Last_Map": self.last_map,
                "Game_ID": self.game_id,
                "Window_Size": self.window_size
            }, f)

    def load_config(self):
        config = {}
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    config = json.load(f)
            except: pass
        
        self.session_id = config.get("Session_ID", 1)
        self.max_session_id = config.get("Max_Session_ID", self.session_id)
        self.session_configs = config.get("Session_Configs", {})
        
        # Pull current session defaults from session_configs if they exist
        curr_cfg = self.session_configs.get(str(self.session_id), {})
        self.difficulty = curr_cfg.get("Difficulty", config.get("Difficulty", "Normal"))
        self.last_map = curr_cfg.get("Map", config.get("Last_Map", ""))
        
        # Ensure max_session_id syncs with current if current is somehow higher
        self.max_session_id = max(self.max_session_id, self.session_id)
        
        self.window_size = config.get("Window_Size", "1200x800")
        self.game_id = config.get("Game_ID", "game_8")
        self.set_game(self.game_id)
        return config

    def set_map(self, map_name):
        self.last_map = map_name
        self.session_configs.setdefault(str(self.session_id), {})["Map"] = map_name
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

    def ensure_failures_header(self):
        if not os.path.exists(self.failures_path) or os.stat(self.failures_path).st_size == 0:
            with open(self.failures_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Session_ID", "Map", "Difficulty",
                    "Room1", "Type1", "Linked1",
                    "Room2", "Type2", "Linked2",
                    "Room3", "Type3", "Linked3",
                    "Timestamp"
                ])

    def set_difficulty(self, difficulty):
        self.difficulty = difficulty
        self.session_configs.setdefault(str(self.session_id), {})["Difficulty"] = difficulty
        self.save_config()

    def set_session(self, session_id):
        self.session_id = session_id
        # Update current state from saved session config if available
        cfg = self.session_configs.get(str(session_id), {})
        if "Difficulty" in cfg: self.difficulty = cfg["Difficulty"]
        if "Map" in cfg: self.last_map = cfg["Map"]
        self.save_config()

    def get_all_sessions(self):
        ids = set()
        # High-water mark from config
        ids.add(self.max_session_id)
        ids.add(self.session_id)
        
        # Check Main logs
        if os.path.exists(self.logs_path):
            with open(self.logs_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try: ids.add(int(row["Session_ID"]))
                    except: continue
        # Check Failure logs
        fail_path = os.path.join(self.base_dir, "logs", f"{self.game_id}_failures.csv")
        if os.path.exists(fail_path):
            with open(fail_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try: ids.add(int(row["Session_ID"]))
                    except: continue
        return sorted(list(ids))

    def increment_session(self):
        existing = self.get_all_sessions()
        max_in_logs = max(existing) if existing else 0
        
        # Increment based on whichever is higher: logs, config, or current state
        self.session_id = max(max_in_logs, self.session_id, self.max_session_id) + 1
        self.max_session_id = self.session_id

        # Pre-populate this new session with current settings so they stick
        self.session_configs[str(self.session_id)] = {
            "Map": self.last_map,
            "Difficulty": self.difficulty
        }
        
        self.save_config()
        return self.session_id

    def get_session_info(self, session_id):
        """Returns (Map, Difficulty) for a given session ID by checking configs first, then logs."""
        # 1. Check manual configs first (user's intent)
        cfg = self.session_configs.get(str(session_id), {})
        if "Map" in cfg and "Difficulty" in cfg:
            return cfg["Map"], cfg["Difficulty"]
            
        # 2. Check main logs fallback
        if os.path.exists(self.logs_path):
            with open(self.logs_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if int(row["Session_ID"]) == session_id:
                        return row["Map"], row["Difficulty"]
        
        # 2. Check failure logs
        fail_path = os.path.join(self.base_dir, "logs", f"{self.game_id}_failures.csv")
        if os.path.exists(fail_path):
            with open(fail_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if int(row["Session_ID"]) == session_id:
                        # Assuming at least one reported failure has a valid Map/Difficulty
                        return row["Map"], row["Difficulty"]
        return None, None

    def is_current_session_locked(self):
        """
        Policy: Any session < max_known_session is locked by default.
        ALSO: Any session that has an 'It's over' report is locked.
        Returns True if the current session_id is locked and NOT manually unlocked.
        """
        existing = self.get_all_sessions()
        if not existing: return False
        
        max_id = max(existing)
        
        # Check if it has a failure report (means it is 'finished')
        has_failure = len(self.get_missed_anomalies(self.last_map, self.session_id)) > 0

        if self.session_id < max_id or has_failure:
            # It's an old or finished session. Is it in the override list?
            return self.session_id not in self.unlocked_sessions
        return False

    def toggle_session_lock(self):
        """Toggles the manual 'unlocked' status for the current session ID."""
        if self.session_id in self.unlocked_sessions:
            self.unlocked_sessions.remove(self.session_id)
        else:
            self.unlocked_sessions.add(self.session_id)
        return self.is_current_session_locked()

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

    def add_failure_report(self, map_name, failures):
        """
        failures: list of 3 dicts {"room": str, "reported_type": str, "linked_anomaly": str}
        """
        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        row = [self.session_id, map_name, self.difficulty]
        
        updated_any_json = False
        for f in failures:
            room = f.get("room", "")
            reported_type = f.get("reported_type", "")
            linked_name = f.get("linked_anomaly", "None")
            row.extend([room, reported_type, linked_name])
            
            # Update master JSON if linked
            if linked_name != "None":
                if self.update_anomaly_end_game_type(map_name, room, linked_name, reported_type):
                    updated_any_json = True
                    
        row.append(timestamp)
        
        with open(self.failures_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(row)
            
        if updated_any_json:
            self.save_master_data()
            
        return True

    def update_anomaly_end_game_type(self, map_name, room_name, anomaly_name, end_game_type):
        """
        Look up the anomaly and update its game_end_type field.
        """
        # 1. Check specific room
        target_list = self.data.get("Maps", {}).get(map_name, {}).get("Rooms", {}).get(room_name, [])
        for anom in target_list:
            if anom["name"].lower() == anomaly_name.lower():
                anom["game_end_type"] = end_game_type
                return True
        
        # 2. Check Global section as fallback (every global anomaly is still in a room)
        global_list = self.data.get("Global", [])
        for anom in global_list:
            if anom["name"].lower() == anomaly_name.lower():
                anom["game_end_type"] = end_game_type
                return True
                
        return False

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

    def get_room_anomalies(self, map_name, room_name):
        if not map_name or not room_name: return []
        map_data = self.data.get("Maps", {}).get(map_name, {})
        rooms = map_data.get("Rooms", {})
        anoms = rooms.get(room_name, [])
        # Add global ones if map exists
        if room_name != "Global":
            anoms = anoms + self.data.get("Global", [])
            
        # Format with descriptions if available
        result = []
        for a in anoms:
            name = a["name"]
            desc = a.get("description", a.get("desc", ""))
            if desc:
                result.append(f"{name}: ({desc})")
            else:
                result.append(name)
        return sorted(result)

    def _get_tags(self, value):
        """Helper to extract tags from a string (comma separated) or a list."""
        if not value: return []
        if isinstance(value, list):
            return [str(t).strip() for t in value if t]
        if isinstance(value, str):
            return [t.strip() for t in value.split(',') if t.strip()]
        return [str(value)]

    def get_room_types(self, map_name, room_name):
        """Returns unique types found in a specific room + Global (Supports lists or comma strings)."""
        if not map_name or not room_name: return []
        types = set()
        
        # Local Room
        room_anoms = self.data.get("Maps", {}).get(map_name, {}).get("Rooms", {}).get(room_name, [])
        for anom in room_anoms:
            for t in self._get_tags(anom.get("type")): types.add(t)
            for t in self._get_tags(anom.get("game_end_type")): types.add(t)
            
        # Global
        for anom in self.data.get("Global", []):
            for t in self._get_tags(anom.get("type")): types.add(t)
            for t in self._get_tags(anom.get("game_end_type")): types.add(t)
            
        return sorted([t for t in types if t])

    def get_all_types(self):
        """
        Scans all anomalies in the JSON for unique types (Supports lists or comma strings).
        """
        types = set()
        # Scan Global
        for anom in self.data.get("Global", []):
            for t in self._get_tags(anom.get("type")): types.add(t)
            for t in self._get_tags(anom.get("game_end_type")): types.add(t)
            
        # Scan Maps
        for map_data in self.data.get("Maps", {}).values():
            for room_anoms in map_data.get("Rooms", {}).values():
                for anom in room_anoms:
                    for t in self._get_tags(anom.get("type")): types.add(t)
                    for t in self._get_tags(anom.get("game_end_type")): types.add(t)
                    
        return sorted([t for t in types if t])

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

    def get_stats(self, map_name, max_session_id=None):
        stats = {"total_sessions": 0, "anomaly_sessions": defaultdict(set)}
        if not os.path.exists(self.logs_path): return stats
        
        sessions = set()
        with open(self.logs_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["Difficulty"] == self.difficulty and row["Map"] == map_name:
                    s_id = int(row["Session_ID"])
                    if max_session_id and s_id > max_session_id: continue
                    
                    sessions.add(s_id)
                    stats["anomaly_sessions"][row["Anomaly_Name"]].add(s_id)
        
        stats["total_sessions"] = len(sessions)
        return stats

    def get_missed_anomalies(self, map_name, session_id):
        """Returns a list of anomaly names reported as missed in the given session."""
        missed = []
        fail_path = os.path.join(self.base_dir, "logs", f"{self.game_id}_failures.csv")
        if not os.path.exists(fail_path): return missed
        
        with open(fail_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if int(row["Session_ID"]) == session_id and row["Map"] == map_name:
                    # Collect from Linked1, Linked2, Linked3
                    for i in range(1, 4):
                        name = row.get(f"Linked{i}", "None")
                        if name and name != "None":
                            missed.append(name)
        return missed

    def get_failure_details(self, map_name, session_id):
        """Returns a list of dictionaries with full failure report details."""
        reports = []
        fail_path = os.path.join(self.base_dir, "logs", f"{self.game_id}_failures.csv")
        if not os.path.exists(fail_path): return reports
        
        with open(fail_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if int(row["Session_ID"]) == session_id and row["Map"] == map_name:
                    for i in range(1, 4):
                        room = row.get(f"Room{i}", "None")
                        if room and room != "None":
                            reports.append({
                                "room": room,
                                "type": row.get(f"Type{i}", "Unknown"),
                                "linked_anomaly": row.get(f"Linked{i}", "None")
                            })
        return reports

    def get_live_exclusions(self, map_name, current_anoms):
        if not current_anoms: return []
        # 'Truly LIVE': include everything up to and including the current session
        stats = self.get_stats(map_name, max_session_id=self.session_id)
        N = stats["total_sessions"]
        if N < 2: return []

        # Pre-calculate session sets for each reported anomaly
        session_sets = {a: stats["anomaly_sessions"].get(a, set()) for a in current_anoms}

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

            # Direct Blocker Logic: An anomaly is excluded if it conflicts with ANY individual report.
            blockers = []
            S_blockers_union = set()
            for r_name, S_r in session_sets.items():
                if not (S_r & S_a):
                    blockers.append(r_name)
                    S_blockers_union.update(S_r)
            
            if not blockers: continue

            # Surprise metric: Based on the union of sessions that cause the exclusion
            n_blockers = len(S_blockers_union)
            expected_overlap = (n_blockers * n_a) / N

            # Probability of zero intersection by chance (Hypergeometric p-value)
            if N - n_blockers < n_a:
                p_value = 0
            else:
                lp = log_comb(N - n_blockers, n_a) - log_comb(N, n_a)
                p_value = math.exp(lp)
            
            certainty = 1 - p_value
            
            # Map p-value to a more human-friendly Status
            certainty_status = "Initial Pattern"
            if n_blockers > 5:
                if p_value < 0.01: certainty_status = "Confirmed Rule"
                elif p_value < 0.1: certainty_status = "High Prob."
            elif n_blockers > 2:
                if p_value < 0.2: certainty_status = "Strong Pattern"

            exclusions.append({
                "name": a_name,
                "count": n_a,
                "expected_overlap": expected_overlap,
                "certainty": certainty,
                "certainty_status": certainty_status,
                "n_blockers": n_blockers,
                "N": N,
                "blockers": blockers
            })

        # Sort by Certainty first, then by Surprise (overlap)
        exclusions.sort(key=lambda x: (x["certainty"], x["expected_overlap"]), reverse=True)
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
                    certainty = 1 - math.exp(lp) if lp != -float('inf') else 1.0
                    
                    results.append({
                        "pair": (a1, a2),
                        "room1": format_rooms(a1),
                        "room2": format_rooms(a2),
                        "n1": n1, "n2": n2,
                        "expected": expected_overlap,
                        "actual": 0,
                        "certainty": certainty,
                        "N": total_sessions,
                        "status": "Hard Lock" if certainty > 0.95 else "Likely Excl."
                    })
                elif actual_overlap == 1 and expected_overlap > 5.0:
                    results.append({
                        "pair": (a1, a2),
                        "room1": format_rooms(a1),
                        "room2": format_rooms(a2),
                        "n1": n1, "n2": n2,
                        "expected": expected_overlap,
                        "actual": 1,
                        "certainty": 0,
                        "N": total_sessions,
                        "status": "Anti-Pattern"
                    })
        
        results.sort(key=lambda x: x["expected"], reverse=True)
        return results
