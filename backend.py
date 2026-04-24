import csv
import os
import json
import math
import uuid
import shutil
from collections import defaultdict
from datetime import datetime

class Backend:
    CSV_FIELDS = ["Session_ID", "Difficulty", "Map", "Room", "Anomaly_ID", "Anomaly_Name", "Timestamp", "Alt_Tabbed", "Last_Cycled"]
    FAILURES_FIELDS = [
        "Session_ID", "Map", "Difficulty",
        "Room1", "Type1", "Linked1_ID", "Linked1",
        "Room2", "Type2", "Linked2_ID", "Linked2",
        "Room3", "Type3", "Linked3_ID", "Linked3",
        "Timestamp",
    ]
    # Where one-shot CSV/JSON backups go before a migration. Lives in the user's
    # Obsidian vault so Proton Drive picks it up on next sync.
    BACKUP_DIR = "/media/timo/Storage/Proton Drive/Obsidian/Obsidian hoidla/Arvutimängud/observation-duty-tracker-backups"

    def __init__(self, base_dir=None):
        if base_dir is None:
            # Assumes base_dir is where the script is
            self.base_dir = os.path.dirname(os.path.abspath(__file__))
        else:
            self.base_dir = base_dir

        self.config_path = os.path.join(self.base_dir, "app_config.json")
        self.game_id = None  # Populated by load_config
        self.session_id = 1
        self.max_session_id = 1
        self.session_configs = {} # {str(id): {"Map": str, "Difficulty": str}}
        self.difficulty = "Normal"
        self.last_map = ""
        self.failures_path = ""
        self.unlocked_sessions = set()
        self.manually_locked_sessions = set()
        self.window_size = "1200x800"
        self.show_all_candidates = False

        # Per-game persisted state: {game_id: {Session_ID, Max_Session_ID, Session_Configs, ...}}
        self.games_state = {}

        # Performance Cache
        self._cache = {} # {path: list_of_dicts}
        self._cache_mtimes = {} # {path: float}

        self.load_config() # This will set game_id and paths

    def _default_game_state(self):
        return {
            "Session_ID": 1,
            "Max_Session_ID": 1,
            "Session_Configs": {},
            "Difficulty": "Normal",
            "Last_Map": "",
            "Unlocked_Sessions": [],
            "Manually_Locked_Sessions": [],
        }

    def _sync_active_to_games_state(self):
        """Push the active in-memory attributes back into games_state[game_id]."""
        if not self.game_id:
            return
        self.games_state[self.game_id] = {
            "Session_ID": self.session_id,
            "Max_Session_ID": self.max_session_id,
            "Session_Configs": self.session_configs,
            "Difficulty": self.difficulty,
            "Last_Map": self.last_map,
            "Unlocked_Sessions": sorted(self.unlocked_sessions),
            "Manually_Locked_Sessions": sorted(self.manually_locked_sessions),
        }

    def _load_active_from_games_state(self):
        """Populate the active attributes from games_state[game_id]."""
        state = self.games_state.setdefault(self.game_id, self._default_game_state())
        self.session_id = state.get("Session_ID", 1)
        self.max_session_id = state.get("Max_Session_ID", self.session_id)
        self.session_configs = state.setdefault("Session_Configs", {})
        self.difficulty = state.get("Difficulty", "Normal")
        self.last_map = state.get("Last_Map", "")
        self.unlocked_sessions = set(state.get("Unlocked_Sessions", []))
        self.manually_locked_sessions = set(state.get("Manually_Locked_Sessions", []))
        self.max_session_id = max(self.max_session_id, self.session_id)

    def set_game(self, game_id):
        # Switching games: flush the current game's active state back to its slot first
        if self.game_id and self.game_id != game_id:
            self._sync_active_to_games_state()

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

        # Pull this game's saved state into the active attributes
        self._load_active_from_games_state()

        # One-shot cleanup: drop Map/Difficulty from any Session_Configs entry
        # whose shift already has CSV rows (CSV is the source of truth).
        if self._cleanup_stale_session_configs():
            self.save_config()

        # Stable anomaly IDs — backfill JSON and migrate CSVs if needed.
        if self._ensure_anomaly_ids():
            self.save_master_data()
        needs_main = self._main_csv_needs_id_migration()
        needs_fail = self._failures_csv_needs_id_migration()
        if needs_main or needs_fail:
            backup_dir = self._backup_data_files("pre-anomaly-id-migration")
            if backup_dir:
                print(f"[migration] backed up data/logs to {backup_dir}")
            if needs_main: self._migrate_main_csv_add_ids()
            if needs_fail: self._migrate_failures_csv_add_ids()
        is_real_data = self.base_dir == os.path.dirname(os.path.abspath(__file__))
        # Rename propagation: JSON is authoritative for names. Runs every start,
        # cheap no-op once everything is in sync.
        self._sync_csv_names_from_json()
        # Orphan detection: rows reference IDs that no longer exist in JSON.
        # Non-fatal — just a heads-up so the user knows if a JSON edit dropped
        # an anomaly that still had logged rows.
        if is_real_data:
            orphans = self.find_orphan_anomaly_ids()
            if orphans:
                print(f"[{self.game_id}] {len(orphans)} anomaly ID(s) in CSV no longer exist in JSON (data/{self.game_id}.json). These rows are preserved with their stored names but won't aggregate correctly:")
                for aid, info in list(orphans.items())[:5]:
                    print(f"  - {info['name'] or '(blank name)'}: {info['main_rows']} main row(s), {info['failure_rows']} failure row(s)")

    def save_config(self):
        self._sync_active_to_games_state()
        with open(self.config_path, 'w') as f:
            json.dump({
                "Game_ID": self.game_id,
                "Window_Size": self.window_size,
                "Show_All_Candidates": self.show_all_candidates,
                "Games": self.games_state,
            }, f)

    def load_config(self):
        config = {}
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    config = json.load(f)
            except: pass

        self.window_size = config.get("Window_Size", "1200x800")
        # UI preference: when False, room buttons hide anomalies that are
        # confirmed to only appear on the OTHER difficulty (≥1 sighting on
        # other, zero on current). When True, they're still visible but
        # rendered muted so the user can still read descriptions mid-game
        # or log them if the sighting history turns out to have misled us.
        # Never-seen anomalies (zero sightings anywhere) are always shown
        # regardless, so a first sighting is always reachable.
        self.show_all_candidates = bool(config.get("Show_All_Candidates", False))

        if "Games" in config:
            self.games_state = config.get("Games", {}) or {}
            self.game_id = config.get("Game_ID", "game_8")
        else:
            # Migrate old single-game-at-top-level shape into per-game Games dict
            self.games_state, self.game_id, migrated = self._migrate_old_config(config)
            if migrated:
                # Persist the new shape immediately so the old keys are gone
                # set_game below will call save_config via first write
                pass

        self.set_game(self.game_id)
        # Always save after load so the on-disk shape is canonical
        self.save_config()
        return config

    def _migrate_old_config(self, config):
        """Convert pre-Games config (keys at top level) into per-game Games dict.

        Splits Session_Configs and lock lists by which game's CSV contains each
        Session_ID. If a game's IDs don't start at 1, renumbers both its
        Session_Configs and CSV rows so each game's shift IDs start at 1.
        """
        game_id = config.get("Game_ID", "game_8")
        has_old_keys = any(k in config for k in (
            "Session_ID", "Max_Session_ID", "Session_Configs",
            "Unlocked_Sessions", "Manually_Locked_Sessions", "Difficulty", "Last_Map"))
        if not has_old_keys:
            # Brand new config: no migration, just a single default slot for the current game
            return {game_id: self._default_game_state()}, game_id, False

        old_session_configs = dict(config.get("Session_Configs", {}) or {})
        collectibles = old_session_configs.pop("_collectibles", None)
        unlocked = set(config.get("Unlocked_Sessions", []) or [])
        manual_locked = set(config.get("Manually_Locked_Sessions", []) or [])

        # Map each session ID to the game whose CSV contains it
        session_to_game = {}
        logs_dir = os.path.join(self.base_dir, "logs")
        if os.path.isdir(logs_dir):
            for fn in sorted(os.listdir(logs_dir)):
                if not fn.endswith(".csv") or fn.endswith("_failures.csv"):
                    continue
                g = fn[:-len(".csv")]
                path = os.path.join(logs_dir, fn)
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        for row in csv.DictReader(f):
                            try: sid = int(row["Session_ID"])
                            except: continue
                            session_to_game[sid] = g
                except: pass

        # Bucket session_configs / locks by target game
        game_configs = defaultdict(dict)
        for sid_str, cfg in old_session_configs.items():
            try: sid = int(sid_str)
            except: continue
            target = session_to_game.get(sid, game_id)
            game_configs[target][sid_str] = cfg

        game_unlocked = defaultdict(set)
        game_manual = defaultdict(set)
        for sid in unlocked:
            game_unlocked[session_to_game.get(sid, game_id)].add(sid)
        for sid in manual_locked:
            game_manual[session_to_game.get(sid, game_id)].add(sid)

        all_games = set(game_configs) | set(game_unlocked) | set(game_manual) | {game_id}

        games_state = {}
        for g in all_games:
            sids = [int(s) for s in game_configs[g].keys()]
            sids.extend(game_unlocked[g])
            sids.extend(game_manual[g])
            # Also include any CSV-known sessions for this game (so renumbering covers the full range)
            for sid, target in session_to_game.items():
                if target == g:
                    sids.append(sid)

            if sids:
                offset = min(sids) - 1 if min(sids) > 1 else 0
                max_sid = max(sids) - offset
            else:
                offset = 0
                max_sid = 1

            def shift(sid_int):
                return sid_int - offset

            renumbered = {str(shift(int(s))): cfg for s, cfg in game_configs[g].items()}

            # Infer defaults for non-active games from their most recent session_config
            if g == game_id:
                default_diff = config.get("Difficulty", "Normal")
                default_map = config.get("Last_Map", "")
            else:
                default_diff = "Normal"
                default_map = ""
                for s_key in sorted((int(s) for s in renumbered.keys()), reverse=True):
                    entry = renumbered.get(str(s_key), {})
                    if not default_map and entry.get("Map"):
                        default_map = entry["Map"]
                    if default_diff == "Normal" and entry.get("Difficulty"):
                        default_diff = entry["Difficulty"]
                    if default_map and default_diff != "Normal":
                        break

            state = {
                "Session_ID": max_sid,
                "Max_Session_ID": max_sid,
                "Session_Configs": renumbered,
                "Difficulty": default_diff,
                "Last_Map": default_map,
                "Unlocked_Sessions": sorted(shift(s) for s in game_unlocked[g]),
                "Manually_Locked_Sessions": sorted(shift(s) for s in game_manual[g]),
            }

            if offset:
                self._renumber_csv_rows(g, offset)

            games_state[g] = state

        # _collectibles is per-map but was stored as a single blob — keep it with the active game
        if collectibles:
            games_state.setdefault(game_id, self._default_game_state())
            games_state[game_id].setdefault("Session_Configs", {})["_collectibles"] = collectibles

        return games_state, game_id, True

    def _renumber_csv_rows(self, game_id, offset):
        """Subtract offset from all Session_ID fields in this game's main + failures CSV."""
        for fn in (f"{game_id}.csv", f"{game_id}_failures.csv"):
            path = os.path.join(self.base_dir, "logs", fn)
            if not os.path.exists(path):
                continue
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    rows = list(csv.reader(f))
            except:
                continue
            if not rows:
                continue
            header = rows[0]
            try: sid_idx = header.index("Session_ID")
            except ValueError: continue
            for row in rows[1:]:
                if len(row) <= sid_idx: continue
                try:
                    row[sid_idx] = str(int(row[sid_idx]) - offset)
                except: pass
            with open(path, 'w', newline='', encoding='utf-8') as f:
                csv.writer(f).writerows(rows)

    def set_map(self, map_name):
        self.last_map = map_name
        # Only persist Map into Session_Configs for empty (not-yet-logged) shifts.
        # Once the shift has CSV rows, the CSV is the ground truth and a config
        # copy can only cause drift (see get_session_info).
        if not self._session_has_logged_rows(self.session_id):
            self.session_configs.setdefault(str(self.session_id), {})["Map"] = map_name
        self.save_config()

    def _session_has_logged_rows(self, session_id):
        """True if the given shift has at least one row in either the main
        logs CSV or the failures CSV. Used to decide when Session_Configs
        should stop storing Map/Difficulty for that shift (the CSVs become
        the source of truth)."""
        for row in self._get_csv_data(self.logs_path):
            try:
                if int(row["Session_ID"]) == session_id: return True
            except: pass
        for row in self._get_csv_data(self.failures_path):
            try:
                if int(row["Session_ID"]) == session_id: return True
            except: pass
        return False

    def _strip_map_diff_from_session_config(self, session_id):
        """Remove Map/Difficulty from a single shift's Session_Configs entry
        (the CSV is now the ground truth for those). Delete the entry if it
        becomes empty. Idempotent."""
        key = str(session_id)
        entry = self.session_configs.get(key)
        if not isinstance(entry, dict): return
        changed = False
        for field in ("Map", "Difficulty"):
            if field in entry:
                entry.pop(field)
                changed = True
        if not entry:
            del self.session_configs[key]
            changed = True
        return changed

    def _cleanup_stale_session_configs(self):
        """One-shot cleanup: for any shift that already has CSV rows, drop the
        Map/Difficulty fields from its Session_Configs entry — the CSVs are the
        ground truth for those fields. Other fields (Alt_Tabbed_At, Last_Cycled,
        Alt_Tab_Disabled, Cycling_Disabled) are preserved since they have no
        CSV counterpart. Runs every startup; idempotent."""
        changed = False
        for key in list(self.session_configs.keys()):
            if not key.isdigit(): continue  # skip _collectibles etc.
            try: sid = int(key)
            except: continue
            if not self._session_has_logged_rows(sid): continue
            entry = self.session_configs[key]
            for field in ("Map", "Difficulty"):
                if field in entry:
                    entry.pop(field)
                    changed = True
            if not entry:
                del self.session_configs[key]
                changed = True
        return changed

    # -----------------------------------------------------------------
    # Stable anomaly IDs. Each anomaly gets a UUID that never changes,
    # even when renamed. CSVs store both the ID (for matching/ownership)
    # and the name (for human readability / legacy fallback).
    # -----------------------------------------------------------------

    def _ensure_anomaly_ids(self):
        """Walk the master JSON and assign a UUID to any anomaly that lacks one.
        Returns True if anything was changed (caller is responsible for saving)."""
        changed = False
        def assign(anom):
            nonlocal changed
            if "id" not in anom or not anom["id"]:
                anom["id"] = str(uuid.uuid4())
                changed = True
        for a in self.data.get("Global", []):
            assign(a)
        for map_data in self.data.get("Maps", {}).values():
            for room_anoms in map_data.get("Rooms", {}).values():
                for a in room_anoms:
                    assign(a)
        return changed

    def _build_id_lookups(self):
        """Two lookups built from the current JSON:
          - room_lookup[(map_name, room_name, name_lower)] = id
          - global_lookup[name_lower] = id
        Used for resolving a name to an ID during migration and new writes."""
        room_lookup = {}
        global_lookup = {}
        for a in self.data.get("Global", []):
            if "id" in a:
                global_lookup[a["name"].lower()] = a["id"]
        for map_name, map_data in self.data.get("Maps", {}).items():
            for room_name, anoms in map_data.get("Rooms", {}).items():
                for a in anoms:
                    if "id" in a:
                        room_lookup[(map_name, room_name, a["name"].lower())] = a["id"]
        return room_lookup, global_lookup

    def _resolve_anomaly_id(self, map_name, room_name, anomaly_name, _lookups=None):
        """Return the stable ID for an anomaly given its current name and
        location. Global anomalies match by name alone (they appear in any
        room on the CSV, but are keyed by name in JSON). Returns '' if no
        match — caller writes an empty ID rather than failing, so the row
        is still useful as a name-only record."""
        room_lookup, global_lookup = _lookups if _lookups else self._build_id_lookups()
        nm = (anomaly_name or "").lower()
        key = (map_name, room_name, nm)
        if key in room_lookup:
            return room_lookup[key]
        return global_lookup.get(nm, "")

    def _backup_data_files(self, reason):
        """Snapshot the current JSON + CSVs into the Obsidian backup folder
        before a destructive one-shot migration. Keyed by game + reason + ts
        so parallel migrations across multiple games don't collide. Skipped
        when the Backend is operating against a test fixture (base_dir != the
        repo root) so unit tests don't pollute the real backup folder."""
        if self.base_dir != os.path.dirname(os.path.abspath(__file__)): return None
        try:
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            dest = os.path.join(self.BACKUP_DIR, f"{self.game_id}-{reason}-{ts}")
            os.makedirs(dest, exist_ok=True)
            for src in (self.data_path, self.logs_path, self.failures_path):
                if src and os.path.exists(src):
                    shutil.copy2(src, os.path.join(dest, os.path.basename(src)))
            return dest
        except Exception as e:
            print(f"[backup] failed ({e}); migration will proceed without a backup")
            return None

    def _main_csv_needs_id_migration(self):
        if not os.path.exists(self.logs_path): return False
        try:
            with open(self.logs_path, 'r', encoding='utf-8') as f:
                header = next(csv.reader(f), [])
            return "Anomaly_Name" in header and "Anomaly_ID" not in header
        except Exception:
            return False

    def _failures_csv_needs_id_migration(self):
        if not os.path.exists(self.failures_path): return False
        try:
            with open(self.failures_path, 'r', encoding='utf-8') as f:
                header = next(csv.reader(f), [])
            return "Linked1" in header and "Linked1_ID" not in header
        except Exception:
            return False

    def _migrate_main_csv_add_ids(self):
        """Insert an Anomaly_ID column into the main CSV, backfilling each row
        by looking up (Map, Room, Anomaly_Name). Orphan rows (no matching
        anomaly in JSON) get an empty ID — they're still preserved. Idempotent."""
        if not self._main_csv_needs_id_migration(): return 0
        lookups = self._build_id_lookups()
        with open(self.logs_path, 'r', encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        orphans = 0
        for row in rows:
            aid = self._resolve_anomaly_id(
                row.get("Map", ""), row.get("Room", ""), row.get("Anomaly_Name", ""),
                _lookups=lookups,
            )
            row["Anomaly_ID"] = aid
            if not aid:
                orphans += 1
        with open(self.logs_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=self.CSV_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        if orphans:
            print(f"[migration] {os.path.basename(self.logs_path)}: {orphans} row(s) could not be matched to a current anomaly; kept with empty Anomaly_ID (name preserved).")
        return len(rows)

    def _migrate_failures_csv_add_ids(self):
        """Insert Linked1_ID/Linked2_ID/Linked3_ID columns into the failures
        CSV. Each Linked column may be 'None' (no ID) or an anomaly name to
        look up. Idempotent."""
        if not self._failures_csv_needs_id_migration(): return 0
        lookups = self._build_id_lookups()
        with open(self.failures_path, 'r', encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        orphans = 0
        for row in rows:
            map_name = row.get("Map", "")
            for i in (1, 2, 3):
                linked = row.get(f"Linked{i}", "None")
                room = row.get(f"Room{i}", "")
                if linked and linked != "None":
                    aid = self._resolve_anomaly_id(map_name, room, linked, _lookups=lookups)
                    row[f"Linked{i}_ID"] = aid
                    if not aid: orphans += 1
                else:
                    row[f"Linked{i}_ID"] = ""
        with open(self.failures_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=self.FAILURES_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        if orphans:
            print(f"[migration] {os.path.basename(self.failures_path)}: {orphans} linked anomaly name(s) could not be resolved; kept with empty Linked_ID.")
        return len(rows)

    def _sync_csv_names_from_json(self):
        """For each CSV row that has an Anomaly_ID matching an anomaly in JSON,
        overwrite its stored name with the current JSON name. This is the
        rename-propagation mechanism: edit the name in JSON, next startup the
        CSVs reflect it automatically (no manual find-and-replace needed)."""
        # Build id -> current name
        id_to_name = {}
        for a in self.data.get("Global", []):
            if "id" in a: id_to_name[a["id"]] = a["name"]
        for map_data in self.data.get("Maps", {}).values():
            for anoms in map_data.get("Rooms", {}).values():
                for a in anoms:
                    if "id" in a: id_to_name[a["id"]] = a["name"]

        total_updated = 0

        # Main CSV
        if os.path.exists(self.logs_path):
            with open(self.logs_path, 'r', encoding='utf-8') as f:
                rows = list(csv.DictReader(f))
            if rows and "Anomaly_ID" in (rows[0].keys() if rows else []):
                changed = 0
                for row in rows:
                    aid = row.get("Anomaly_ID", "")
                    if aid and aid in id_to_name:
                        cur = id_to_name[aid]
                        if row.get("Anomaly_Name", "") != cur:
                            row["Anomaly_Name"] = cur
                            changed += 1
                if changed:
                    with open(self.logs_path, 'w', newline='', encoding='utf-8') as f:
                        writer = csv.DictWriter(f, fieldnames=self.CSV_FIELDS)
                        writer.writeheader()
                        writer.writerows(rows)
                    total_updated += changed

        # Failures CSV
        if os.path.exists(self.failures_path):
            with open(self.failures_path, 'r', encoding='utf-8') as f:
                rows = list(csv.DictReader(f))
            if rows and "Linked1_ID" in (rows[0].keys() if rows else []):
                changed = 0
                for row in rows:
                    for i in (1, 2, 3):
                        aid = row.get(f"Linked{i}_ID", "")
                        if aid and aid in id_to_name:
                            cur = id_to_name[aid]
                            if row.get(f"Linked{i}", "") != cur:
                                row[f"Linked{i}"] = cur
                                changed += 1
                if changed:
                    with open(self.failures_path, 'w', newline='', encoding='utf-8') as f:
                        writer = csv.DictWriter(f, fieldnames=self.FAILURES_FIELDS)
                        writer.writeheader()
                        writer.writerows(rows)
                    total_updated += changed

        if total_updated:
            print(f"[sync] renamed {total_updated} stored anomaly name(s) in CSVs to match JSON.")
        return total_updated

    def find_orphan_anomaly_ids(self):
        """Detect anomaly IDs referenced in CSVs that no longer exist in JSON —
        i.e., the user removed the anomaly from the data file but logged rows
        still point at it. Returns a dict of {id: {"name": stored_name,
        "main_rows": N, "failure_rows": M}} so the UI/CLI can surface a
        'data you're about to lose' warning before accepting deletions."""
        known_ids = set()
        for a in self.data.get("Global", []):
            if "id" in a: known_ids.add(a["id"])
        for map_data in self.data.get("Maps", {}).values():
            for anoms in map_data.get("Rooms", {}).values():
                for a in anoms:
                    if "id" in a: known_ids.add(a["id"])
        orphans = {}
        if os.path.exists(self.logs_path):
            with open(self.logs_path, 'r', encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    aid = row.get("Anomaly_ID", "")
                    if aid and aid not in known_ids:
                        entry = orphans.setdefault(aid, {"name": row.get("Anomaly_Name", ""), "main_rows": 0, "failure_rows": 0})
                        entry["main_rows"] += 1
        if os.path.exists(self.failures_path):
            with open(self.failures_path, 'r', encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    for i in (1, 2, 3):
                        aid = row.get(f"Linked{i}_ID", "")
                        if aid and aid not in known_ids:
                            entry = orphans.setdefault(aid, {"name": row.get(f"Linked{i}", ""), "main_rows": 0, "failure_rows": 0})
                            entry["failure_rows"] += 1
        return orphans

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
                writer.writerow(self.CSV_FIELDS)

    def ensure_failures_header(self):
        if not os.path.exists(self.failures_path) or os.stat(self.failures_path).st_size == 0:
            with open(self.failures_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(self.FAILURES_FIELDS)

    def set_difficulty(self, difficulty):
        self.difficulty = difficulty
        # Only persist Difficulty into Session_Configs for empty (not-yet-logged)
        # shifts. Once the shift has CSV rows, the CSV is the ground truth.
        if not self._session_has_logged_rows(self.session_id):
            self.session_configs.setdefault(str(self.session_id), {})["Difficulty"] = difficulty
        self.save_config()

    def set_session(self, session_id):
        self.session_id = session_id
        # Restore from the same source get_session_info uses (CSV logs first,
        # config fallback) so an accidental config write on a logged session can't
        # resurrect a stale difficulty/map here.
        s_map, s_diff = self.get_session_info(session_id)
        if s_diff: self.difficulty = s_diff
        if s_map: self.last_map = s_map
        # Persist so closing the app right after navigation reopens on this shift.
        self.save_config()

    def _get_csv_data(self, path):
        """Helper to get CSV data from cache or disk if changed."""
        if not os.path.exists(path): return []
        
        current_mtime = os.path.getmtime(path)
        if path in self._cache and self._cache_mtimes.get(path) == current_mtime:
            return self._cache[path]
            
        # Re-read from disk
        data = []
        try:
            with open(path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                data = list(reader)
            self._cache[path] = data
            self._cache_mtimes[path] = current_mtime
        except: pass
        return data

    def get_all_sessions(self):
        ids = set()
        # High-water mark from config
        ids.add(self.max_session_id)
        ids.add(self.session_id)
        
        # Check Main logs
        for row in self._get_csv_data(self.logs_path):
            try: ids.add(int(row["Session_ID"]))
            except: continue
            
        # Check Failure logs
        fail_path = os.path.join(self.base_dir, "logs", f"{self.game_id}_failures.csv")
        for row in self._get_csv_data(fail_path):
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
        """Returns (Map, Difficulty) for a given session ID. Main CSV logs are the
        ground truth and win when present — the config's Session_Configs entry is
        only a fallback for sessions that have no logged rows yet (e.g. a newly
        created empty shift). This prevents a stale or accidental combobox change
        on a historical session from silently overwriting what was actually logged."""
        # 1. Main logs are authoritative (anomalies were actually logged against these values)
        for row in self._get_csv_data(self.logs_path):
            if int(row["Session_ID"]) == session_id:
                return row["Map"], row["Difficulty"]

        # 2. Config fallback — covers sessions with no logged rows yet
        cfg = self.session_configs.get(str(session_id), {})
        if "Map" in cfg and "Difficulty" in cfg:
            return cfg["Map"], cfg["Difficulty"]

        # 3. Failure logs as last resort (session ended in 'It's over' with no prior reports)
        fail_path = os.path.join(self.base_dir, "logs", f"{self.game_id}_failures.csv")
        for row in self._get_csv_data(fail_path):
            if int(row["Session_ID"]) == session_id:
                return row["Map"], row["Difficulty"]
        return None, None

    def is_current_session_locked(self):
        """
        Policy: Any session < max_known_session is locked by default.
        ALSO: Any session that has an 'It's over' report is locked.
        ALSO: Any session manually locked via toggle is locked.
        Returns True if the current session_id is locked and NOT manually unlocked.
        """
        # Manual lock takes priority
        if self.session_id in self.manually_locked_sessions:
            return True

        existing = self.get_all_sessions()
        if not existing: return False

        max_id = max(existing)

        # Check if it has a failure report (means it is 'finished')
        has_failure = self.has_failure_report(self.session_id)

        if self.session_id < max_id or has_failure:
            # It's an old or finished session. Is it in the override list?
            return self.session_id not in self.unlocked_sessions
        return False

    def toggle_session_lock(self):
        """Toggles lock status. For current/latest session: manual lock. For old sessions: unlock override."""
        existing = self.get_all_sessions()
        max_id = max(existing) if existing else 0
        has_failure = self.has_failure_report(self.session_id)

        if self.session_id < max_id or has_failure:
            # Old/finished session: toggle unlock override
            if self.session_id in self.unlocked_sessions:
                self.unlocked_sessions.remove(self.session_id)
            else:
                self.unlocked_sessions.add(self.session_id)
        else:
            # Current session: toggle manual lock
            if self.session_id in self.manually_locked_sessions:
                self.manually_locked_sessions.remove(self.session_id)
            else:
                self.manually_locked_sessions.add(self.session_id)
        self.save_config()
        return self.is_current_session_locked()

    # --- Debug: glitch tracking ---
    # Alt-tab and camera cycling are both assumed ON by default. The UI lets
    # the user flag a shift as "not doing this" — e.g. a deliberately clean
    # recording. Cycling, when on, is assumed to happen right after each
    # anomaly is reported (Last_Cycled = that row's Timestamp).

    def is_alt_tab_disabled(self):
        return bool(self.session_configs.get(str(self.session_id), {}).get("Alt_Tab_Disabled"))

    def is_cycling_disabled(self):
        return bool(self.session_configs.get(str(self.session_id), {}).get("Cycling_Disabled"))

    def set_alt_tab_disabled(self, disabled):
        cfg = self.session_configs.setdefault(str(self.session_id), {})
        if disabled:
            cfg["Alt_Tab_Disabled"] = True
        else:
            cfg.pop("Alt_Tab_Disabled", None)
        self.save_config()
        self._rewrite_session_flag_rows()

    def set_cycling_disabled(self, disabled):
        cfg = self.session_configs.setdefault(str(self.session_id), {})
        if disabled:
            cfg["Cycling_Disabled"] = True
        else:
            cfg.pop("Cycling_Disabled", None)
        self.save_config()
        self._rewrite_session_flag_rows()

    def _rewrite_session_flag_rows(self):
        """Rewrite Alt_Tabbed and Last_Cycled on all CSV rows of the current session
        to match the current session flags."""
        if not os.path.exists(self.logs_path):
            return
        alt_val = "False" if self.is_alt_tab_disabled() else "True"
        cyc_off = self.is_cycling_disabled()
        rows = []
        with open(self.logs_path, 'r', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                if int(row["Session_ID"]) == self.session_id:
                    row["Alt_Tabbed"] = alt_val
                    row["Last_Cycled"] = "" if cyc_off else row.get("Timestamp", "")
                rows.append(row)
        with open(self.logs_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=self.CSV_FIELDS)
            writer.writeheader()
            writer.writerows(rows)

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
            writer = csv.DictWriter(f, fieldnames=self.CSV_FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    def add_observation(self, map_name, room_name, anomaly_name):
        if self.is_logged_in_current_session(map_name, room_name, anomaly_name):
            return False
        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        cfg = self.session_configs.get(str(self.session_id), {})
        alt_tabbed = "False" if cfg.get("Alt_Tab_Disabled") else "True"
        last_cycled = "" if cfg.get("Cycling_Disabled") else timestamp
        anom_id = self._resolve_anomaly_id(map_name, room_name, anomaly_name)
        with open(self.logs_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([self.session_id, self.difficulty, map_name, room_name, anom_id, anomaly_name, timestamp, alt_tabbed, last_cycled])
        # Shift now has a CSV row — drop any stale Map/Difficulty from its
        # Session_Configs entry so the CSV is the only copy from here on.
        self._strip_map_diff_from_session_config(self.session_id)
        return True

    def add_failure_report(self, map_name, failures):
        """
        failures: list of 3 dicts {"room": str, "reported_type": str, "linked_anomaly": str}
        """
        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        row = [self.session_id, map_name, self.difficulty]

        updated_any_json = False
        lookups = self._build_id_lookups()
        for f in failures:
            room = f.get("room", "")
            reported_type = f.get("reported_type", "")
            linked_name = f.get("linked_anomaly", "None")
            if linked_name and linked_name != "None":
                linked_id = self._resolve_anomaly_id(map_name, room, linked_name, _lookups=lookups)
            else:
                linked_id = ""
            row.extend([room, reported_type, linked_id, linked_name])

            # Update master JSON if linked
            if linked_name != "None":
                if self.update_anomaly_end_game_type(map_name, room, linked_name, reported_type):
                    updated_any_json = True

        row.append(timestamp)
        
        with open(self.failures_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(row)

        # Shift is recorded in a CSV now — drop any stale Map/Difficulty copy
        # from Session_Configs so the failures CSV is the only source.
        self._strip_map_diff_from_session_config(self.session_id)

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
                writer = csv.DictWriter(f, fieldnames=self.CSV_FIELDS)
                writer.writeheader()
                writer.writerows(reversed(rows))
        return removed

    COLLECTIBLE_TYPES = {"Special Object", "Secret Object"}

    def is_collectible_collected(self, map_name, name):
        """Check if a collectible is marked as collected."""
        collected = self.session_configs.get("_collectibles", {}).get(map_name, [])
        return name in collected

    def toggle_collectible(self, map_name, name):
        """Toggle collected state for a collectible. Stored globally, not per-session."""
        coll = self.session_configs.setdefault("_collectibles", {}).setdefault(map_name, [])
        if name in coll:
            coll.remove(name)
        else:
            coll.append(name)
        self.save_config()

    def is_collectible(self, anomaly):
        atype = anomaly.get("type", "")
        if isinstance(atype, list):
            return bool(set(atype) & self.COLLECTIBLE_TYPES)
        return atype in self.COLLECTIBLE_TYPES

    def get_collectibles(self, map_name):
        """Returns list of {name, room, description} for all collectibles on this map."""
        result = []
        rooms = self.data.get("Maps", {}).get(map_name, {}).get("Rooms", {})
        for room_name, anoms in rooms.items():
            for a in anoms:
                if self.is_collectible(a):
                    result.append({"name": a["name"], "room": room_name, "description": a.get("description", "")})
        return result

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
        for row in self._get_csv_data(self.logs_path):
            if int(row["Session_ID"]) == self.session_id and \
               row["Difficulty"] == self.difficulty and \
               row["Map"] == map_name and \
               row["Room"] == room_name and \
               row["Anomaly_Name"] == anomaly_name:
                return True
        return False

    def get_last_activity(self):
        last_time = "Never"
        for row in self._get_csv_data(self.logs_path):
            if int(row["Session_ID"]) == self.session_id:
                last_time = row.get("Timestamp", "N/A")
        return last_time

    def get_per_difficulty_sightings(self, map_name):
        """Cross-difficulty 'have I ever seen this?' view for a given map.

        Returns a list of per-anomaly dicts, one per anomaly defined in the
        map's rooms (plus all Global anomalies, which can manifest on any map):
            {
                "id": str,              # stable UUID
                "name": str,            # current display name
                "room": str,            # "Global" for Global anomalies
                "sightings_by_diff": {"Normal": int, "Hard": int, ...},
                                        # unique-shift count per difficulty
                "total_shifts": int,    # unique shifts across all difficulties
            }
        Never-seen anomalies are still included (with zeros) so the UI can
        present them as 'outstanding' without a separate lookup."""
        sightings = defaultdict(lambda: defaultdict(set))
        for row in self._get_csv_data(self.logs_path):
            if row.get("Map") != map_name: continue
            aid = row.get("Anomaly_ID", "")
            if not aid: continue
            diff = row.get("Difficulty", "")
            try: sid = int(row.get("Session_ID", ""))
            except: continue
            sightings[aid][diff].add(sid)

        supported_diffs = self.data.get("Difficulties", ["Normal", "Hard"])

        def summarize(aid, name, room):
            per_diff = sightings.get(aid, {})
            # Shifts are difficulty-exclusive, so set union == sum; either works.
            total = sum(len(s) for s in per_diff.values())
            return {
                "id": aid,
                "name": name,
                "room": room,
                "sightings_by_diff": {d: len(per_diff.get(d, set())) for d in supported_diffs},
                "total_shifts": total,
            }

        # Collectibles are tracked via toggle (not CSV logs), so including them
        # would show perpetual 'never seen' — filtered out to keep the tab
        # focused on what the CSV actually reflects.
        results = []
        map_data = self.data.get("Maps", {}).get(map_name, {})
        for room_name, anoms in map_data.get("Rooms", {}).items():
            for a in anoms:
                if "id" in a and not self.is_collectible(a):
                    results.append(summarize(a["id"], a["name"], room_name))
        for a in self.data.get("Global", []):
            if "id" in a and not self.is_collectible(a):
                results.append(summarize(a["id"], a["name"], "Global"))
        return results

    def get_counts(self, map_name=None, room_name=None, max_session_id=None):
        counts = defaultdict(int)
        for row in self._get_csv_data(self.logs_path):
            if row["Difficulty"] == self.difficulty:
                try:
                    s_id = int(row["Session_ID"])
                except ValueError:
                    continue
                if max_session_id is not None and s_id > max_session_id:
                    continue
                if map_name and row["Map"] != map_name: continue
                if room_name and row["Room"] != room_name: continue
                counts[row["Anomaly_Name"]] += 1
        return counts

    def add_new_anomaly(self, map_name, room_name, anom_name, anom_type="Unknown", description=""):
        # 1. Update JSON
        new_entry = {
            "id": str(uuid.uuid4()),
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
        for row in self._get_csv_data(self.logs_path):
            if int(row["Session_ID"]) == self.session_id and \
               row["Difficulty"] == self.difficulty and \
               row["Map"] == map_name:
                anoms.append(row["Anomaly_Name"])
        return anoms

    def get_map_shifts(self, map_name):
        """All session IDs for this game on this map, across difficulties.
        Used for the shift-count display — analysis logic stays per-difficulty."""
        ids = set()
        for row in self._get_csv_data(self.logs_path):
            if row["Map"] == map_name:
                try: ids.add(int(row["Session_ID"]))
                except: continue
        if os.path.exists(self.failures_path):
            for row in self._get_csv_data(self.failures_path):
                if row.get("Map") == map_name:
                    try: ids.add(int(row["Session_ID"]))
                    except: continue
        return ids

    def get_stats(self, map_name, max_session_id=None):
        stats = {"total_sessions": 0, "anomaly_sessions": defaultdict(set), "first_seen": {}}
        sessions = set()

        for row in self._get_csv_data(self.logs_path):
            if row["Difficulty"] == self.difficulty and row["Map"] == map_name:
                s_id = int(row["Session_ID"])
                if max_session_id and s_id > max_session_id: continue

                sessions.add(s_id)
                a_name = row["Anomaly_Name"]
                stats["anomaly_sessions"][a_name].add(s_id)
                if a_name not in stats["first_seen"] or s_id < stats["first_seen"][a_name]:
                    stats["first_seen"][a_name] = s_id

        # Merge failure-reported anomalies into known sessions (best-effort)
        if os.path.exists(self.failures_path):
            for row in self._get_csv_data(self.failures_path):
                if row.get("Difficulty") == self.difficulty and row.get("Map") == map_name:
                    s_id = int(row["Session_ID"])
                    if max_session_id and s_id > max_session_id: continue
                    if s_id not in sessions: continue
                    for i in range(1, 4):
                        linked = row.get(f"Linked{i}", "None")
                        if linked and linked != "None":
                            stats["anomaly_sessions"][linked].add(s_id)
                            if linked not in stats["first_seen"] or s_id < stats["first_seen"][linked]:
                                stats["first_seen"][linked] = s_id

        stats["total_sessions"] = len(sessions)
        stats["all_sessions"] = sessions
        return stats

    def has_failure_report(self, session_id):
        """Returns True if the given session has any 'It's over' report, regardless of whether its failures were linked to master-DB anomalies."""
        if not os.path.exists(self.failures_path): return False
        with open(self.failures_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if int(row["Session_ID"]) == session_id:
                    return True
        return False

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
        if not current_anoms: return [], None
        # 'Truly LIVE': include everything up to and including the current session
        stats = self.get_stats(map_name, max_session_id=self.session_id)
        N = stats["total_sessions"]
        if N < 1: return [], None

        all_sessions = stats["all_sessions"]
        first_seen = stats["first_seen"]

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

        pending = []  # Near-threshold candidates

        for a_name in sorted(all_possible_anoms):
            if a_name in current_anoms: continue

            S_a = stats["anomaly_sessions"].get(a_name, set())
            n_a = len(S_a)

            # Track near-threshold: seen only once (need 2)
            if n_a < 2:
                if n_a == 1:
                    pending.append({
                        "name": a_name,
                        "reason": f"1 sighting (need 2)",
                        "count": n_a,
                    })
                continue

            # Direct Blocker Logic: An anomaly is excluded if it conflicts with ANY individual report.
            blockers = []
            S_blockers_union = set()
            for r_name, S_r in session_sets.items():
                # Only count sessions from when BOTH anomalies have been seen
                fs_pair = max(first_seen.get(a_name, 0), first_seen.get(r_name, 0))
                S_r_window = {s for s in S_r if s >= fs_pair}
                S_a_window = {s for s in S_a if s >= fs_pair}
                if not (S_r_window & S_a_window) and S_r_window and S_a_window:
                    blockers.append(r_name)
                    S_blockers_union.update(S_r_window)

            if not blockers: continue

            # Effective N: sessions from the earliest relevant first_seen onward
            fs_a = first_seen.get(a_name, 0)
            fs_blockers = min(first_seen.get(b, 0) for b in blockers)
            fs_effective = max(fs_a, fs_blockers)
            N_eff = len({s for s in all_sessions if s >= fs_effective})

            if N_eff < 3:
                pending.append({
                    "name": a_name,
                    "reason": f"{N_eff} shifts since first seen (need 3)",
                    "count": n_a,
                })
                continue

            S_a_eff = {s for s in S_a if s >= fs_effective}
            n_a_eff = len(S_a_eff)
            n_blockers = len(S_blockers_union)
            expected_overlap = (n_blockers * n_a_eff) / N_eff

            # Skip if zero overlap isn't surprising (expected < 5 means sparse data)
            if expected_overlap < 5:
                pending.append({
                    "name": a_name,
                    "reason": f"expected overlap {expected_overlap:.1f} (need > 5)",
                    "count": n_a,
                    "expected_overlap": expected_overlap,
                    "blockers": blockers,
                    "n_blockers": n_blockers,
                    "N": N_eff,
                })
                continue

            # Probability of zero intersection by chance (Hypergeometric p-value)
            if N_eff - n_blockers < n_a_eff:
                p_value = 0
            else:
                lp = log_comb(N_eff - n_blockers, n_a_eff) - log_comb(N_eff, n_a_eff)
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
                "blockers": blockers,
                "N": N_eff,
            })
        # Sort by Certainty first, then by Surprise (overlap)
        exclusions.sort(key=lambda x: (x["certainty"], x["expected_overlap"]), reverse=True)

        # Pick the single closest-to-threshold candidate
        # Priority: expected_overlap failures (closest to graduating), then shifts, then sightings
        def pending_rank(p):
            r = p["reason"]
            if "expected overlap" in r:
                return (0, -p.get("expected_overlap", 0))  # closest to 5 first
            elif "shifts since first seen" in r:
                return (1, -p["count"])
            else:
                return (2, -p["count"])
        pending.sort(key=pending_rank)
        best_pending = pending[0] if pending else None

        return exclusions, best_pending

    def get_live_exclusions_with_groups(self, map_name, current_anoms):
        """Enriches live exclusions with known group membership context.

        Returns exclusions tagged with their exclusion group (if known),
        plus a list of group summaries for display.
        """
        exclusions, best_pending = self.get_live_exclusions(map_name, current_anoms)
        if not exclusions and not best_pending:
            return {"exclusions": [], "groups": [], "best_pending": None}

        analysis = self.analyze_exclusivity()
        known_groups = analysis.get("groups", [])

        # Build anomaly -> group index mapping
        anom_to_group = {}
        for i, group in enumerate(known_groups):
            for member in group["members"]:
                anom_to_group[member["name"]] = i

        # Tag each exclusion with its group index (or -1 for ungrouped)
        for excl in exclusions:
            excl["group_idx"] = anom_to_group.get(excl["name"], -1)

        # Build group summaries relevant to current exclusions
        # Only include groups that have at least one excluded member
        active_group_indices = {e["group_idx"] for e in exclusions if e["group_idx"] >= 0}
        group_summaries = []
        for idx in sorted(active_group_indices):
            g = known_groups[idx]
            members = [m["name"] for m in g["members"]]
            # Which members from this group are in the current logged anomalies?
            active_members = [m for m in members if m in current_anoms]
            excluded_members = [m for m in members if m not in current_anoms]
            group_summaries.append({
                "idx": idx,
                "members": members,
                "active_members": active_members,
                "excluded_members": excluded_members,
                "size": g["size"],
                "certainty": g["certainty"],
                "status": g["status"],
            })

        return {"exclusions": exclusions, "groups": group_summaries, "best_pending": best_pending}

    def analyze_exclusivity(self, target_difficulty=None, target_map=None):
        """Analyzes historical logs to find exclusion groups and flag suspicious co-occurrences.

        Finds groups of anomalies where seeing any one member excludes all others
        in the group from appearing in the same shift.
        """
        difficulty_filter = target_difficulty if target_difficulty else self.difficulty

        sessions = defaultdict(set)
        anom_to_sessions = defaultdict(set)
        anom_to_room_counts = defaultdict(lambda: defaultdict(int))
        all_anomalies = set()
        if not os.path.exists(self.logs_path): return {"groups": [], "suspicious": []}

        # Read sightings
        first_seen = {}  # anomaly -> earliest session_id (int)
        with open(self.logs_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["Difficulty"] != difficulty_filter: continue
                if target_map and row.get("Map", "") != target_map: continue
                s_id = row["Session_ID"]; a_name = row["Anomaly_Name"]; room = row["Room"]
                s_id_int = int(s_id)
                sessions[s_id].add(a_name)
                anom_to_sessions[a_name].add(s_id)
                anom_to_room_counts[a_name][room] += 1
                all_anomalies.add(a_name)
                if a_name not in first_seen or s_id_int < first_seen[a_name]:
                    first_seen[a_name] = s_id_int

        # Merge failure-reported anomalies (best-effort: missed != absent)
        if os.path.exists(self.failures_path):
            with open(self.failures_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("Difficulty") != difficulty_filter: continue
                    if target_map and row.get("Map", "") != target_map: continue
                    s_id = row["Session_ID"]
                    s_id_int = int(s_id)
                    if s_id not in sessions: continue
                    for i in range(1, 4):
                        linked = row.get(f"Linked{i}", "None")
                        if linked and linked != "None":
                            sessions[s_id].add(linked)
                            anom_to_sessions[linked].add(s_id)
                            all_anomalies.add(linked)
                            if linked not in first_seen or s_id_int < first_seen[linked]:
                                first_seen[linked] = s_id_int

        def format_rooms(anom):
            rooms = anom_to_room_counts[anom]
            parts = [f"{r} x{c}" for r, c in sorted(rooms.items(), key=lambda x: x[1], reverse=True)]
            return ", ".join(parts) if parts else "Unknown"

        all_session_ids = {int(s) for s in sessions.keys()}
        total_sessions = len(sessions)
        if total_sessions == 0: return {"groups": [], "suspicious": []}

        freq = {a: len(anom_to_sessions[a]) for a in all_anomalies}
        # Only consider anomalies with enough sightings
        eligible = {a for a in all_anomalies if freq[a] >= 2}

        # Build exclusion graph: edge between a,b if they never co-occur
        # Only count sessions from when both anomalies have been seen
        excl_edges = set()  # frozenset pairs
        best_developing = None  # closest pair to forming a group edge

        def _update_developing(members, certainty, N_eff, reason, score):
            """Track the single best developing pair (highest score = closest to graduating)."""
            nonlocal best_developing
            if best_developing is None or score > best_developing["_score"]:
                best_developing = {
                    "members": members,
                    "certainty": certainty,
                    "N": N_eff,
                    "reason": reason,
                    "_score": score,
                }

        for a1 in eligible:
            s1 = anom_to_sessions[a1]
            for a2 in eligible:
                if a2 <= a1: continue
                s2 = anom_to_sessions[a2]

                # Window: only sessions from when both were first seen
                fs = max(first_seen.get(a1, 0), first_seen.get(a2, 0))
                window_sessions = {s for s in all_session_ids if s >= fs}
                N_eff = len(window_sessions)
                if N_eff < 3: continue

                s1_w = {s for s in s1 if int(s) >= fs}
                s2_w = {s for s in s2 if int(s) >= fs}
                if s1_w & s2_w: continue  # They co-occur in the window

                n1_w, n2_w = len(s1_w), len(s2_w)
                if n1_w < 2 or n2_w < 2: continue

                expected_overlap = (n1_w * n2_w) / N_eff
                if expected_overlap < 5:
                    # Score: how close to 5 (higher = closer)
                    _update_developing(sorted([a1, a2]), 0, N_eff,
                        f"expected overlap {expected_overlap:.1f} (need > 5)",
                        expected_overlap / 5)  # 0..1 range
                    continue

                # Certainty check
                if N_eff - n1_w >= n2_w:
                    lp = math.lgamma(N_eff - n1_w + 1) + math.lgamma(N_eff - n2_w + 1) - \
                         math.lgamma(N_eff + 1) - math.lgamma(N_eff - n1_w - n2_w + 1)
                    certainty = 1 - math.exp(lp) if lp != -float('inf') else 1.0
                else:
                    certainty = 1.0

                if certainty < 0.7:
                    # Score: 1.0 + certainty (always beats expected_overlap failures)
                    _update_developing(sorted([a1, a2]), certainty, N_eff,
                        f"certainty {certainty:.0%} (need > 70%)",
                        1.0 + certainty)
                    continue

                excl_edges.add(frozenset((a1, a2)))

        # Find exclusion groups via greedy clique detection
        # Build adjacency for the exclusion graph
        adj = defaultdict(set)
        for edge in excl_edges:
            a, b = edge
            adj[a].add(b)
            adj[b].add(a)

        groups = []
        used = set()
        # Greedy: start from highest-degree node, grow clique
        nodes_by_degree = sorted(adj.keys(), key=lambda x: len(adj[x]), reverse=True)
        for seed in nodes_by_degree:
            if seed in used: continue
            # Grow clique from seed
            clique = {seed}
            candidates = adj[seed].copy()
            for node in sorted(candidates, key=lambda x: len(adj[x]), reverse=True):
                if node in used: continue
                # Check if node is connected to all current clique members
                if all(node in adj[member] for member in clique):
                    clique.add(node)
            if len(clique) < 2: continue
            used.update(clique)

            # Calculate group-level stats using windowed comparisons
            member_list = sorted(clique)
            min_certainty = 1.0
            for a1 in member_list:
                for a2 in member_list:
                    if a2 <= a1: continue
                    fs = max(first_seen.get(a1, 0), first_seen.get(a2, 0))
                    N_eff = len({s for s in all_session_ids if s >= fs})
                    n1_w = len({s for s in anom_to_sessions[a1] if int(s) >= fs})
                    n2_w = len({s for s in anom_to_sessions[a2] if int(s) >= fs})
                    if N_eff - n1_w >= n2_w:
                        lp = math.lgamma(N_eff - n1_w + 1) + math.lgamma(N_eff - n2_w + 1) - \
                             math.lgamma(N_eff + 1) - math.lgamma(N_eff - n1_w - n2_w + 1)
                        c = 1 - math.exp(lp) if lp != -float('inf') else 1.0
                    else:
                        c = 1.0
                    min_certainty = min(min_certainty, c)

            groups.append({
                "members": [{
                    "name": a,
                    "rooms": format_rooms(a),
                    "sightings": freq[a],
                } for a in member_list],
                "size": len(member_list),
                "certainty": min_certainty,
                "N": total_sessions,
                "status": "CONFIRMED GROUP" if min_certainty > 0.95 else "LIKELY GROUP",
            })

        # Group violations: find candidate members that almost fit a group
        # but co-occur with 1-2 members in a small number of shifts
        violations = []
        group_members_all = set()
        for g in groups:
            group_members_all.update(m["name"] for m in g["members"])

        for g in groups:
            g_names = [m["name"] for m in g["members"]]
            g_set = set(g_names)

            for candidate in eligible - g_set:
                s_cand = anom_to_sessions[candidate]
                exclusive_with = []
                conflicts = []

                for member in g_names:
                    s_mem = anom_to_sessions[member]
                    fs = max(first_seen.get(candidate, 0), first_seen.get(member, 0))
                    window = {s for s in all_session_ids if s >= fs}
                    N_eff = len(window)
                    if N_eff < 3:
                        continue

                    s_cand_w = {s for s in s_cand if int(s) >= fs}
                    s_mem_w = {s for s in s_mem if int(s) >= fs}
                    n_cand_w, n_mem_w = len(s_cand_w), len(s_mem_w)
                    if n_cand_w < 2 or n_mem_w < 2:
                        continue

                    overlap = s_cand_w & s_mem_w
                    actual = len(overlap)
                    expected = (n_cand_w * n_mem_w) / N_eff

                    if actual == 0:
                        exclusive_with.append(member)
                    elif actual <= 2 and expected >= 5 and (actual / expected) <= 0.4:
                        conflicts.append({
                            "member": member,
                            "conflict_shifts": sorted(overlap, key=lambda x: int(x)),
                            "expected_overlap": expected,
                            "actual_overlap": actual,
                        })
                    else:
                        # Too much co-occurrence — not a candidate for this group
                        break
                else:
                    # Must be exclusive with at least one member AND have conflicts
                    if exclusive_with and conflicts and not (len(conflicts) > len(g_names) // 2 + 1):
                        for conflict in conflicts:
                            violations.append({
                                "group_names": g_names,
                                "candidate": candidate,
                                "candidate_rooms": format_rooms(candidate),
                                "conflicts_with": conflict["member"],
                                "conflict_shifts": conflict["conflict_shifts"],
                                "exclusive_with": exclusive_with,
                                "expected_overlap": conflict["expected_overlap"],
                                "actual_overlap": conflict["actual_overlap"],
                            })

        groups.sort(key=lambda x: (-x["size"], -x["certainty"]))
        violations.sort(key=lambda x: (-len(x["exclusive_with"]), x["actual_overlap"]))
        return {"groups": groups, "violations": violations, "suspicious": violations,
                "best_developing": best_developing}

    def get_anomaly_frequencies(self, target_difficulty=None, from_first_seen=True, target_map=None):
        """Per-anomaly occurrence rates with condition breakdowns (alt-tab, cycling).

        Anomalies are keyed by (name, room) because the same name can refer to
        distinct anomalies in different rooms (e.g. "Dead body" in Pier vs Basement).
        Global anomalies are keyed by (name, "Global") and aggregate across rooms,
        since the same Global anomaly can manifest in any room.
        """
        difficulty_filter = target_difficulty if target_difficulty else self.difficulty
        if not os.path.exists(self.logs_path):
            return []

        global_names = {a["name"] for a in self.data.get("Global", [])}

        def make_key(name, room):
            if name in global_names:
                return (name, "Global")
            return (name, room)

        # One pass through CSV to collect everything
        all_shifts = set()
        key_shifts = defaultdict(set)          # (name, room) -> set of shift IDs
        key_clean_shifts = defaultdict(set)
        key_alttab_shifts = defaultdict(set)
        first_seen = {}                         # (name, room) -> earliest shift ID
        shift_has_cycling = set()
        key_cycled_shifts = defaultdict(set)
        clean_shifts = set()
        alttab_shifts = set()
        logged_maps = set()

        with open(self.logs_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["Difficulty"] != difficulty_filter:
                    continue
                map_name = row.get("Map", "")
                if target_map and map_name != target_map:
                    continue
                s_id = int(row["Session_ID"])
                a_name = row["Anomaly_Name"]
                room = row["Room"]
                alt_tabbed = row.get("Alt_Tabbed", "False") == "True"
                last_cycled = row.get("Last_Cycled", "").strip()

                key = make_key(a_name, room)

                all_shifts.add(s_id)
                key_shifts[key].add(s_id)
                if map_name:
                    logged_maps.add(map_name)

                if key not in first_seen or s_id < first_seen[key]:
                    first_seen[key] = s_id

                if alt_tabbed:
                    key_alttab_shifts[key].add(s_id)
                    alttab_shifts.add(s_id)
                else:
                    key_clean_shifts[key].add(s_id)
                    clean_shifts.add(s_id)

                if last_cycled:
                    shift_has_cycling.add(s_id)
                    key_cycled_shifts[key].add(s_id)

        if not all_shifts:
            return []

        # Collect all known (name, room) pairs from game data for maps that have log data
        all_known_keys = set()
        maps_data = self.data.get("Maps", {})
        for m_name in logged_maps:
            if m_name in maps_data:
                for r_name, r_anoms in maps_data[m_name].get("Rooms", {}).items():
                    for a in r_anoms:
                        all_known_keys.add(make_key(a["name"], r_name))
        for a in self.data.get("Global", []):
            all_known_keys.add((a["name"], "Global"))

        all_keys = sorted(all_known_keys | set(key_shifts.keys()))

        n_total_shifts = len(all_shifts)

        results = []
        for key in all_keys:
            a_name, room = key
            fs = first_seen.get(key)

            if fs is None:
                results.append({
                    "name": a_name,
                    "rooms": room,
                    "first_seen": None,
                    "total_shifts": 0,
                    "eligible_shifts": n_total_shifts,
                    "overall_rate": 0,
                    "clean_rate": None,
                    "alt_tab_rate": None,
                    "cycled_shift_rate": None,
                    "non_cycled_rate": None,
                    "clean_shifts": 0,
                    "alt_tab_shifts": 0,
                    "cycled_shifts": 0,
                })
                continue

            if from_first_seen:
                eligible = {s for s in all_shifts if s >= fs}
            else:
                eligible = all_shifts

            total = len(key_shifts[key] & eligible)
            n_eligible = len(eligible)
            overall_rate = total / n_eligible if n_eligible else 0

            eligible_clean = eligible & clean_shifts
            n_clean = len(eligible_clean)
            clean_appeared = len(key_clean_shifts[key] & eligible_clean)
            clean_rate = clean_appeared / n_clean if n_clean else None

            eligible_alttab = eligible & alttab_shifts
            n_alttab = len(eligible_alttab)
            alttab_appeared = len(key_alttab_shifts[key] & eligible_alttab)
            alt_tab_rate = alttab_appeared / n_alttab if n_alttab else None

            eligible_cycled = eligible & shift_has_cycling
            n_cycled = len(eligible_cycled)
            cycled_appeared = len(key_cycled_shifts[key] & eligible_cycled)
            cycled_rate = cycled_appeared / n_cycled if n_cycled else None

            eligible_noncycled = eligible - shift_has_cycling
            n_noncycled = len(eligible_noncycled)
            noncycled_appeared = len(key_shifts[key] & eligible_noncycled)
            non_cycled_rate = noncycled_appeared / n_noncycled if n_noncycled else None

            results.append({
                "name": a_name,
                "rooms": room,
                "first_seen": fs,
                "total_shifts": total,
                "eligible_shifts": n_eligible,
                "overall_rate": overall_rate,
                "clean_rate": clean_rate,
                "alt_tab_rate": alt_tab_rate,
                "cycled_shift_rate": cycled_rate,
                "non_cycled_rate": non_cycled_rate,
                "clean_shifts": n_clean,
                "alt_tab_shifts": n_alttab,
                "cycled_shifts": n_cycled,
            })

        return results

