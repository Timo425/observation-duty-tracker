"""
Test UI launcher — generates deterministic test data, then launches the real tracker.

Uses a temp directory for app_config.json so the real config is never touched.
Data and logs live under tests/data and tests/logs (isolated from the main tool).
"""
import sys
import os
import json
import tempfile
import shutil

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tests_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base_dir)
sys.path.insert(0, tests_dir)

# 1. Generate deterministic test data
from generate_test_data import generate
generate(base_dir)

# 2. Temp dir for config only (symlink tests/data + tests/logs as the app's data/logs)
tmpdir = tempfile.mkdtemp(prefix="obs_test_")
os.symlink(os.path.join(tests_dir, "data"), os.path.join(tmpdir, "data"))
os.symlink(os.path.join(tests_dir, "logs"), os.path.join(tmpdir, "logs"))

from generate_test_data import NUM_SHIFTS
config = {
    "Game_ID": "game_test",
    "Window_Size": "1200x800",
    "Games": {
        "game_test": {
            "Session_ID": NUM_SHIFTS,
            "Max_Session_ID": NUM_SHIFTS,
            "Session_Configs": {str(i): {"Map": "TestHouse", "Difficulty": "Normal"} for i in range(1, NUM_SHIFTS + 1)},
            "Difficulty": "Normal",
            "Last_Map": "TestHouse",
            "Unlocked_Sessions": [],
            "Manually_Locked_Sessions": [],
        }
    }
}
with open(os.path.join(tmpdir, "app_config.json"), 'w') as f:
    json.dump(config, f)

# 3. Patch Backend to use temp dir (keeps real config safe)
from backend import Backend
orig_init = Backend.__init__

def patched_init(self, base_dir_arg=None):
    orig_init(self, base_dir=tmpdir)

Backend.__init__ = patched_init

# 4. Launch real UI
import tkinter as tk
from observation_duty_tracker import AnomalyTrackerApp

root = tk.Tk()
root.title("Observation Duty Tracker [TEST MODE]")
app = AnomalyTrackerApp(root)
root.mainloop()

# 5. Cleanup
shutil.rmtree(tmpdir, ignore_errors=True)
