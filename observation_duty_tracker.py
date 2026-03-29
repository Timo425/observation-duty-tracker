import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import json
import os
import colorsys
from backend import Backend

class ToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip_window = None
        widget.bind("<Enter>", self.show_tip)
        widget.bind("<Leave>", self.hide_tip)

    def show_tip(self, event=None):
        if self.tip_window or not self.text: return
        # Offset sufficiently to avoid flickering (original widget <-> tooltip)
        # Using winfo_pointerx/y to be precise about the cursor
        x = self.widget.winfo_pointerx() + 15
        y = self.widget.winfo_pointery() + 15
        
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(tw, text=self.text, justify=tk.LEFT, background="#ffffe0", relief=tk.SOLID, borderwidth=1, font=("tahoma", "9", "normal"), padx=5, pady=2)
        label.pack()

    def hide_tip(self, event=None):
        tw = self.tip_window
        self.tip_window = None
        if tw: tw.destroy()

class AnomalyTrackerApp:
    def __init__(self, root):
        self.root = root
        self.backend = Backend()
        self.root.title("Observation Duty Tracker")
        self.root.geometry(self.backend.window_size)
        self.root.minsize(1000, 700) # Ensure it's never too tiny
        
        self.root.bind("<Configure>", self.on_window_resize)
        
        # Game State
        self.data = self.backend.data
        
        self.GAME_NAMES = {
            "game_1": "I'm on Observation Duty",
            "game_2": "I'm on Observation Duty 2",
            "game_3": "I'm on Observation Duty 3",
            "game_4": "I'm on Observation Duty 4",
            "game_5": "I'm on Observation Duty 5",
            "game_6": "I'm on Observation Duty 6",
            "game_7": "I'm on Observation Duty 7",
            "game_8": "I'm on Observation Duty 8",
        }
        # Mapping back from nice name to ID
        self.NAME_TO_ID = {v: k for k, v in self.GAME_NAMES.items()}
        
        self.current_game_display = tk.StringVar(value=self.GAME_NAMES.get(self.backend.game_id, self.backend.game_id.replace('_', ' ').title()))
        self.current_game_display.trace_add("write", self.on_game_change)

        self.current_map = tk.StringVar(value=self.backend.last_map)
        self.current_difficulty = tk.StringVar(value=self.backend.difficulty)
        self.current_difficulty.trace_add("write", self.on_difficulty_change)
        
        self._prediction_job = None
        self._updating_ui = False
        self._last_rendered_map = None
        self._room_buttons = {} # {room_name: {anomaly_name: button_widget}}
        
        self.setup_ui()
        # Initial analysis with a slight delay for better startup feel
        self.root.after(100, self.update_live_analysis)

    def setup_ui(self):
        # Top Frame: Session & Map Control
        top_frame = ttk.Frame(self.root, padding="10")
        top_frame.pack(fill=tk.X)

        nav_frame = ttk.LabelFrame(top_frame, text="Shift management", padding="5")
        nav_frame.pack(side=tk.LEFT, padx=5)
        ttk.Button(nav_frame, text="<", width=3, command=self.prev_shift).pack(side=tk.LEFT)
        self.session_label = ttk.Label(nav_frame, text=f"ID: {self.backend.session_id}", font=("Arial", 11, "bold"), width=7, anchor="center")
        self.session_label.pack(side=tk.LEFT, padx=5)
        
        # Lock Toggle Button
        self.lock_button = tk.Button(nav_frame, text="🔓", font=("Arial", 10), width=3, height=1, command=self.toggle_lock, relief=tk.FLAT)
        self.lock_button.pack(side=tk.LEFT, padx=2)
        ToolTip(self.lock_button, "Lock/Unlock historical session for editing")

        ttk.Button(nav_frame, text=">", width=3, command=self.next_shift).pack(side=tk.LEFT)
        self.activity_label = ttk.Label(nav_frame, text="Last activity: Never", font=("Arial", 9, "italic"), foreground="gray")
        self.activity_label.pack(side=tk.LEFT, padx=10)
        ttk.Button(nav_frame, text="New shift", command=self.start_new_shift).pack(side=tk.LEFT, padx=10)
        self.over_button = ttk.Button(nav_frame, text="It's over", command=self.show_failure_dialog)
        self.over_button.pack(side=tk.LEFT, padx=5)
        ttk.Button(nav_frame, text="Audit logs", command=self.show_analytics_window).pack(side=tk.LEFT, padx=5)

        mode_frame = ttk.LabelFrame(top_frame, text="Settings", padding="5")
        mode_frame.pack(side=tk.LEFT, padx=15)
        
        ttk.Label(mode_frame, text="Game:").grid(row=0, column=0, padx=5)
        # Scan for available games and map to nice names
        raw_ids = [f.split('.')[0] for f in os.listdir(os.path.join(self.backend.base_dir, "data")) if f.endswith('.json')]
        nice_names = [self.GAME_NAMES.get(rid, rid.replace('_', ' ').title()) for rid in raw_ids]
        
        self.game_combo = ttk.Combobox(mode_frame, textvariable=self.current_game_display, values=nice_names, state="readonly", width=25)
        self.game_combo.grid(row=0, column=1)

        self.diff_label = ttk.Label(mode_frame, text="Difficulty:")
        self.diff_label.grid(row=0, column=2, padx=10)
        self.difficulty_combo = ttk.Combobox(mode_frame, textvariable=self.current_difficulty, values=["Normal", "Hard"], state="readonly", width=10)
        self.difficulty_combo.grid(row=0, column=3, padx=5)

        self.map_label = ttk.Label(mode_frame, text="Map:")
        self.map_label.grid(row=0, column=4, padx=5)
        map_names = list(self.data.get("Maps", {}).keys())
        self.map_combo = ttk.Combobox(mode_frame, textvariable=self.current_map, values=map_names, state="readonly", width=20)
        self.map_combo.grid(row=0, column=5, padx=5)
        self.map_combo.bind("<<ComboboxSelected>>", self.on_map_change)

        # Debug: Glitch tracking toggles
        debug_frame = ttk.LabelFrame(top_frame, text="Debug", padding="5")
        debug_frame.pack(side=tk.LEFT, padx=15)

        self.alt_tab_btn = tk.Button(debug_frame, text="Alt-Tabbed", width=12, command=self.on_alt_tab_toggle, relief=tk.RAISED, bg="#d9d9d9")
        self.alt_tab_btn.pack(side=tk.LEFT, padx=3)
        ToolTip(self.alt_tab_btn, "Mark that alt-tabbing happened this shift (one-way, can't undo)")

        self.cycle_btn = tk.Button(debug_frame, text="Cycled cams", width=12, command=self.on_camera_cycle, relief=tk.RAISED, bg="#d9d9d9")
        self.cycle_btn.pack(side=tk.LEFT, padx=3)
        ToolTip(self.cycle_btn, "Record a camera cycling event (each press updates timestamp)")

        self.debug_status = ttk.Label(debug_frame, text="", font=("Arial", 8, "italic"), foreground="gray")
        self.debug_status.pack(side=tk.LEFT, padx=5)

        # Collectibles strip (compact, between top bar and main content)
        self.collectibles_frame = ttk.LabelFrame(self.root, text="Collectibles", padding="3")
        self.collectibles_frame.pack(fill=tk.X, padx=10, pady=(2, 0))
        self._collectible_buttons = {}

        # Content: Notebook + Live Panel
        pane = ttk.Panedwindow(self.root, orient=tk.VERTICAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.notebook = ttk.Notebook(pane)
        pane.add(self.notebook, weight=5)

        # Live Analysis Panel
        self.live_frame = ttk.LabelFrame(pane, text="Live prediction analysis (Mutual exclusivity)", padding="5")
        pane.add(self.live_frame, weight=1)
        
        cols = ("Anomaly", "Certainty", "Evidence", "Sightings", "Blockers")
        self.live_tree = ttk.Treeview(self.live_frame, columns=cols, show="headings", height=10)
        self.live_tree.heading("Anomaly", text="Anomaly Name")
        self.live_tree.heading("Certainty", text="Certainty")
        self.live_tree.heading("Evidence", text="Evidence (Shifts)")
        self.live_tree.heading("Sightings", text="Sights")
        self.live_tree.heading("Blockers", text="Conflict Triggered By")
        self.live_tree.column("Anomaly", width=180)
        self.live_tree.column("Certainty", width=120)
        self.live_tree.column("Evidence", width=110, anchor="center")
        self.live_tree.column("Sightings", width=60, anchor="center")
        self.live_tree.column("Blockers", width=400)
        self.live_tree.pack(fill=tk.BOTH, expand=True)

        # Failure Summary Section (Hidden by default)
        self.failure_frame = ttk.LabelFrame(self.live_frame, text="⚠️ Anomalies took over this shift", padding="5")
        self.failure_label = ttk.Label(self.failure_frame, text="", foreground="#D35400", font=("Arial", 10, "bold"), wraplength=1000)
        self.failure_label.pack(fill=tk.X)
        
        # Tags for analysis coloring
        self.live_tree.tag_configure("REPORTED", background="#FFCC80") # Light Orange

        # Bottom Frame: Status
        status_frame = ttk.Frame(self.root, padding="2")
        status_frame.pack(fill=tk.X)
        self.status_label = ttk.Label(status_frame, text="Ready", font=("Arial", 9))
        self.status_label.pack(side=tk.LEFT)

        self.update_title()
        if map_names:
            saved_map = self.current_map.get()
            if saved_map in map_names:
                self.map_combo.current(map_names.index(saved_map))
            else:
                self.map_combo.current(0)
            self.update_session_view()

    def update_title(self):
        self.root.title(f"{self.current_game_display.get()} Anomaly Tracker")

    def on_window_resize(self, event):
        """Saves current window geometry to config (throttled to root window configure events)."""
        if event.widget == self.root:
            # We only care about root window changes
            geom = self.root.geometry()
            if geom != self.backend.window_size:
                self.backend.window_size = geom
                # Performance: only save if it's a stable change, but resize is manual so it's fine.
                self.backend.save_config()

    def on_game_change(self, *args):
        self._updating_ui = True
        nice_name = self.current_game_display.get()
        # Convert back to ID: either from map OR formatted correctly
        target_id = self.NAME_TO_ID.get(nice_name)
        if not target_id:
            # Fallback: reverse the formatting if possible
            target_id = nice_name.lower().replace(' ', '_')
            
        self.backend.set_game(target_id)
        self.data = self.backend.data
        self.update_title()
        
        # Smart Difficulty: Filter based on what the game supports
        supported_diffs = self.data.get("Difficulties", ["Normal", "Hard"])
        self.difficulty_combo.config(values=supported_diffs)
        
        if len(supported_diffs) < 2:
            self.diff_label.grid_remove()
            self.difficulty_combo.grid_remove()
            self.current_difficulty.set(supported_diffs[0])
        else:
            self.diff_label.grid()
            self.difficulty_combo.grid()
            if self.current_difficulty.get() not in supported_diffs:
                self.current_difficulty.set(supported_diffs[0])
            
        # Refresh map list
        map_names = list(self.data.get("Maps", {}).keys())
        self.map_combo.config(values=map_names)
        if map_names:
            self.current_map.set(map_names[0])
        else:
            self.current_map.set("")
        
        self._updating_ui = False
        self.refresh_map_ui()

    def on_difficulty_change(self, *args):
        if self._updating_ui: return
        self.backend.set_difficulty(self.current_difficulty.get())
        self.status_label.config(text=f"Mode switched to {self.backend.difficulty}")
        self.refresh_map_ui()

    def on_map_change(self, *args):
        """User manually changed the map in the dropdown."""
        if self._updating_ui: return
        map_name = self.current_map.get()
        if map_name:
            self.backend.last_map = map_name
            self.backend.session_configs.setdefault(str(self.backend.session_id), {})["Map"] = map_name
            self.backend.save_config()
            self.refresh_map_ui()

    def refresh_map_ui(self):
        """Updates the room buttons and live analysis. Uses recycling to stay fast."""
        map_name = self.current_map.get()
        if not map_name: return
        
        # Performance: If it's the same map, just update button colors (Logged vs Not)
        if self._last_rendered_map == map_name:
            self.update_button_states()
            self.update_live_analysis()
            return
            
        self._last_rendered_map = map_name
        self._room_buttons = {}

        # Rebuild collectibles strip
        self.rebuild_collectibles(map_name)

        # Save current tab selection if possible
        selected_index = 0
        try: selected_index = self.notebook.index("current")
        except: pass

        # Full rebuild of tabs (only on map change)
        for tab in self.notebook.tabs():
            self.notebook.forget(tab)

        rooms = self.data["Maps"].get(map_name, {}).get("Rooms", {})
        for room_name, anomalies in rooms.items():
            tab = ttk.Frame(self.notebook)
            self.notebook.add(tab, text=room_name)
            self.populate_room_tab(tab, room_name, anomalies)

        # Restore tab selection
        if selected_index < len(self.notebook.tabs()):
            self.notebook.select(selected_index)

        self.update_button_states()
        self.update_live_analysis()

    def rebuild_collectibles(self, map_name):
        """Rebuild the collectibles strip for the current map."""
        for w in self.collectibles_frame.winfo_children():
            w.destroy()
        self._collectible_buttons = {}

        collectibles = self.backend.get_collectibles(map_name)
        if not collectibles:
            self.collectibles_frame.pack_forget()
            return

        self.collectibles_frame.pack(fill=tk.X, padx=10, pady=(2, 0))

        for c in collectibles:
            name, room = c["name"], c["room"]
            collected = self.backend.is_collectible_collected(map_name, name)
            btn = tk.Button(self.collectibles_frame, text=name, width=18, height=1,
                          font=("Arial", 8), command=lambda n=name, r=room: self.toggle_collectible(n, r))
            btn.pack(side=tk.LEFT, padx=3, pady=1)
            ToolTip(btn, f"{c['description']} [{room}]")
            self._collectible_buttons[name] = (btn, room)

    def toggle_collectible(self, name, room):
        """Toggle collected state for a collectible."""
        map_name = self.current_map.get()
        self.backend.toggle_collectible(map_name, name)
        self.update_button_states()

    def update_button_states(self):
        """Fast pass: update labels and smart colors based on live stats."""
        map_name = self.current_map.get()
        if not map_name: return
        
        counts = self.backend.get_counts(map_name)
        current_session_anoms = self.backend.get_current_session_anomalies(map_name)
        live_exclusions = self.backend.get_live_exclusions(map_name, current_session_anoms)
        exclusions_map = {e["name"]: e for e in live_exclusions}
        missed_names = self.backend.get_missed_anomalies(map_name, self.backend.session_id)

        for room_name, btns in self._room_buttons.items():
            for anom_name, btn in btns.items():
                count = counts.get(anom_name, 0)
                excl_info = exclusions_map.get(anom_name)
                
                # Update text with count
                btn.config(text=f"{anom_name} ({count})")
                
                # Probabilistic Color Logic
                bg_color = "lightgray"
                fg_color = "black"
                
                if self.backend.is_logged_in_current_session(map_name, room_name, anom_name):
                    bg_color = "#90ee90" # Green (Found)
                elif anom_name in missed_names:
                    bg_color = "#FF8C00" # Orange (Missed)
                    fg_color = "white"
                elif excl_info:
                    # Heat-map red based on Expected Overlap (Surprise density)
                    E = excl_info['expected_overlap']
                    # Scale saturation: 1.0 (light) to 5.0 (vibrant red)
                    sat = max(0.15, min(1.0, 0.2 + (E - 1.0) * (0.8 / 4.0)))
                    import colorsys
                    rgb = colorsys.hls_to_rgb(0, 0.5, sat)
                    bg_color = '#%02x%02x%02x' % (int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255))
                    if sat > 0.7: fg_color = "white" # High intensity = white text
                
                btn.config(bg=bg_color, fg=fg_color)

        # Update collectible buttons
        for anom_name, (btn, room_name) in self._collectible_buttons.items():
            collected = self.backend.is_collectible_collected(map_name, anom_name)
            if collected:
                btn.config(bg="#90ee90", fg="black")
            else:
                btn.config(bg="#e8e8e8", fg="black")

    def show_analytics_window(self):
        win = tk.Toplevel(self.root)
        win.title("Expert Audit")
        win.geometry("950x650")
        
        header = ttk.Frame(win, padding=10)
        header.pack(fill=tk.X)
        ttk.Label(header, text="Full Database Exclusivity Report", font=("Arial", 12, "bold")).pack(side=tk.LEFT)
        
        # Difficulty Filter
        filter_frame = ttk.Frame(header)
        filter_frame.pack(side=tk.RIGHT)
        ttk.Label(filter_frame, text="Filter:").pack(side=tk.LEFT, padx=5)
        
        supported_diffs = self.data.get("Difficulties", ["Normal", "Hard"])
        audit_diff = tk.StringVar(value=self.backend.difficulty)
        diff_combo = ttk.Combobox(filter_frame, textvariable=audit_diff, values=supported_diffs, width=10, state="readonly")
        diff_combo.pack(side=tk.LEFT)

        # 1. Define refresh logic first
        def refresh(*args):
            self.update_analytics_window(tree, target_diff=audit_diff.get())

        # 2. Add the button (now it can see 'refresh')
        ttk.Button(header, text="Refresh Analysis", command=refresh).pack(side=tk.RIGHT, padx=5)
        
        desc = ttk.Label(win, text="Flags suspicious co-occurrences: when anomalies that almost never appear together show up in the same shift, suggesting possible misidentification.", foreground="gray")
        desc.pack(pady=5)

        cols = ("Pair", "Actual", "Expected", "Certainty", "N", "Status")
        tree = ttk.Treeview(win, columns=cols, show="headings")
        tree.heading("Pair", text="Anomaly Pair (A vs B)")
        tree.heading("Actual", text="Actual Overlap")
        tree.heading("Expected", text="Expected Overlap")
        tree.heading("Certainty", text="Certainty")
        tree.heading("N", text="N")
        tree.heading("Status", text="Status")
        
        tree.column("Pair", width=550)
        tree.column("Actual", width=80, anchor="center")
        tree.column("Expected", width=80, anchor="center")
        tree.column("Certainty", width=80, anchor="center")
        tree.column("N", width=40, anchor="center")
        tree.pack(fill="both", expand=True, padx=10, pady=10)

        # Style colors
        tree.tag_configure("suspicious", background="#ffcccc")
        tree.tag_configure("likely", background="#fff0cc")
        tree.tag_configure("exclusion", background="#ccffcc")

        audit_diff.trace_add("write", refresh)
        refresh()

    def update_analytics_window(self, tree, target_diff=None):
        for item in tree.get_children():
            tree.delete(item)
            
        results = self.backend.analyze_exclusivity(target_difficulty=target_diff)
        for r in results:
            pair_str = f"{r['pair'][0]} ({r['room1']})  <--->  {r['pair'][1]} ({r['room2']})"
            tag = ""
            if "SUSPICIOUS" in r['status']: tag = "suspicious"
            elif "TOTAL EXCLUSION" in r['status']: tag = "exclusion"
            elif "LIKELY EXCLUSION" in r['status']: tag = "likely"

            tree.insert("", tk.END, values=(
                pair_str, 
                r['actual'],
                f"{r['expected']:.2f}", 
                f"{r['certainty']:.0%}" if r['certainty'] > 0 else "—",
                r['N'],
                r['status']
            ), tags=(tag,))

    def populate_room_tab(self, tab, room_name, room_anomalies):
        self._room_buttons[room_name] = {}
        
        canvas = tk.Canvas(tab, highlightthickness=0)
        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_frame = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_frame, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Mouse Wheel Support
        def _on_mouse_wheel(event):
            if event.num == 4 or event.delta > 0: canvas.yview_scroll(-1, "units")
            elif event.num == 5 or event.delta < 0: canvas.yview_scroll(1, "units")
        canvas.bind_all("<MouseWheel>", _on_mouse_wheel)
        canvas.bind_all("<Button-4>", _on_mouse_wheel)
        canvas.bind_all("<Button-5>", _on_mouse_wheel)

        # Local Header
        header = ttk.Frame(scrollable_frame); header.pack(fill=tk.X, pady=5)
        ttk.Label(header, text=f"Room: {room_name}", font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        ttk.Button(header, text="+ Add", command=lambda r=room_name: self.prompt_add_anomaly(r)).pack(side=tk.RIGHT)
        
        # Local Buttons
        self.create_buttons(scrollable_frame, room_name, room_anomalies)
        
        # Global Section
        ttk.Separator(scrollable_frame, orient='horizontal').pack(fill='x', pady=10)
        global_header = ttk.Frame(scrollable_frame); global_header.pack(fill=tk.X, pady=5)
        ttk.Label(global_header, text="Global anomalies", font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        ttk.Button(global_header, text="+ Add", command=lambda: self.prompt_add_anomaly("Global")).pack(side=tk.RIGHT)
        
        self.create_buttons(scrollable_frame, "Global", self.data.get("Global", []))
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def create_buttons(self, parent, room_name, anomalies):
        if room_name not in self._room_buttons: self._room_buttons[room_name] = {}

        # Filter out collectibles from normal anomaly grid
        normal_anoms = [a for a in anomalies if not self.backend.is_collectible(a)]

        grid_frame = ttk.Frame(parent); grid_frame.pack(fill=tk.X)
        for c in range(3): grid_frame.columnconfigure(c, weight=1) # Center/Expand rows

        sorted_anoms = sorted(normal_anoms, key=lambda x: x["name"])
        for i, a in enumerate(sorted_anoms):
            name = a["name"]
            # Store reference for recycling
            btn = tk.Button(grid_frame, text=name, width=20, height=2,
                          command=lambda n=name, r=room_name: self.log_anomaly(n, r))
            btn.grid(row=i // 3, column=i % 3, padx=3, pady=3, sticky="ew")
            self._room_buttons[room_name][name] = btn

            # Use Right-click for Undo as before
            btn.bind("<Button-3>", lambda e, n=name, r=room_name: self.undo_anomaly(n, r))

            # Tooltips for descriptions
            desc = a.get("description", a.get("desc", ""))
            if desc: ToolTip(btn, desc)

    def update_live_analysis(self):
        """Debounced wrapper: only calls the real math after 250ms of silence."""
        if self._prediction_job:
            self.root.after_cancel(self._prediction_job)
        self._prediction_job = self.root.after(250, self._perform_live_analysis)

    def _perform_live_analysis(self):
        """The heavy mathematical lifting."""
        self._prediction_job = None
        
        map_name = self.current_map.get()
        if not map_name: return
        
        current_anoms = self.backend.get_current_session_anomalies(map_name)
        live_exclusions = self.backend.get_live_exclusions(map_name, current_anoms)
        failure_details = self.backend.get_failure_details(map_name, self.backend.session_id)
        
        for item in self.live_tree.get_children():
            self.live_tree.delete(item)
            
        # 1. Update Failure Summary Frame
        if failure_details:
            summary_parts = []
            for f in failure_details:
                name = f["linked_anomaly"] if f["linked_anomaly"] != "None" else f["type"]
                summary_parts.append(f"• {name} in {f['room']}")
            
            self.failure_label.config(text="\n".join(summary_parts))
            self.failure_frame.pack(fill=tk.X, pady=(5, 0), after=self.live_tree)
        else:
            self.failure_frame.pack_forget()

        # 2. Show Mutual Exclusivity Predictions
        for e in live_exclusions:
            # Evidence: How many times was the blocker seen vs Total sessions
            evidence_str = f"{e['n_blockers']} / {e['N']} shifts" 
            certainty_str = f"{e['certainty_status']} ({e['certainty']:.0%})"
            
            self.live_tree.insert("", tk.END, values=(
                e["name"], certainty_str, evidence_str, e["count"], ", ".join(e["blockers"])
            ))

        stats = self.backend.get_stats(map_name, max_session_id=self.backend.session_id)
        self.live_frame.config(text=f"Live prediction analysis (Shifts 1-{self.backend.session_id}: {stats['total_sessions']} total)")

    def log_anomaly(self, name, room_name):
        if self.backend.is_current_session_locked():
            messagebox.showwarning("Locked", "This historical session is LOCKED. Unlock it (🔓) to make changes.")
            return

        current_map = self.current_map.get()
        if self.backend.is_logged_in_current_session(current_map, room_name, name):
            messagebox.showwarning("Duplicate", f"'{name}' is already logged in {room_name}.") ; return
        if self.backend.add_observation(current_map, room_name, name):
            self.status_label.config(text=f"Logged: {name}")
            self.update_session_view()

    def undo_anomaly(self, name, room_name):
        if self.backend.is_current_session_locked():
            messagebox.showwarning("Locked", "This historical session is LOCKED. Unlock it (🔓) to make changes.")
            return

        current_map = self.current_map.get()
        if self.backend.undo_observation(current_map, room_name, name):
            self.status_label.config(text=f"Undid: {name}")
            self.update_session_view()

    def start_new_shift(self):
        self.backend.increment_session()
        self.update_session_view()

    def prev_shift(self):
        all_ids = self.backend.get_all_sessions()
        if not all_ids: return
        # Find the largest ID in all_ids that is smaller than current
        prev_ids = [i for i in all_ids if i < self.backend.session_id]
        if prev_ids:
            self.backend.set_session(max(prev_ids))
            self.update_session_view()

    def next_shift(self):
        all_ids = self.backend.get_all_sessions()
        if not all_ids: return
        # Find the smallest ID in all_ids that is larger than current
        next_ids = [i for i in all_ids if i > self.backend.session_id]
        if next_ids:
            self.backend.set_session(min(next_ids))
            self.update_session_view()

    def confirm_delete_shift(self):
        if messagebox.askyesno("Confirm Delete", f"Delete Shift {self.backend.session_id}?"):
            self.backend.delete_current_session()
            self.on_map_change(None)

    def update_session_view(self):
        self._updating_ui = True
        self.session_label.config(text=f"ID: {self.backend.session_id}")
        self.activity_label.config(text=f"Last activity: {self.backend.get_last_activity()}")
        
        # Update Lock Icon
        if self.backend.is_current_session_locked():
            self.lock_button.config(text="🔒", foreground="red")
        else:
            self.lock_button.config(text="🔓", foreground="green")

        # Smart Load: If this session has activity in logs, switch to its map/diff
        s_map, s_diff = self.backend.get_session_info(self.backend.session_id)
        if s_map and s_diff:
            # Update variables without triggering infinite recursion if needed
            # (on_map_change will still trigger, but that's what we want)
            if self.current_map.get() != s_map or self.current_difficulty.get() != s_diff:
                self.current_map.set(s_map)
                if s_diff: self.current_difficulty.set(s_diff)

        # Always sync backend state from UI to prevent stale difficulty/map
        self.backend.difficulty = self.current_difficulty.get()
        self.backend.last_map = self.current_map.get()

        self._updating_ui = False
        self.update_debug_ui()
        self.refresh_map_ui()

    def toggle_lock(self):
        self.backend.toggle_session_lock()
        self.update_session_view()

    def on_alt_tab_toggle(self):
        if self.backend.is_current_session_locked():
            return
        if self.backend.get_alt_tabbed_at():
            return  # Already toggled, one-way
        ts = self.backend.mark_alt_tabbed()
        self.alt_tab_btn.config(relief=tk.SUNKEN, bg="#ffaaaa")
        self.debug_status.config(text=f"Alt-tabbed at {ts}")

    def on_camera_cycle(self):
        if self.backend.is_current_session_locked():
            return
        ts = self.backend.mark_camera_cycled()
        self.cycle_btn.config(relief=tk.SUNKEN, bg="#aaaaff")
        self.debug_status.config(text=f"Last cycled: {ts}")

    def update_debug_ui(self):
        """Refresh debug button states for current session."""
        alt_at = self.backend.get_alt_tabbed_at()
        if alt_at:
            self.alt_tab_btn.config(relief=tk.SUNKEN, bg="#ffaaaa")
        else:
            self.alt_tab_btn.config(relief=tk.RAISED, bg="#d9d9d9")

        cycled = self.backend.get_last_cycled()
        if cycled:
            self.cycle_btn.config(relief=tk.SUNKEN, bg="#aaaaff")
        else:
            self.cycle_btn.config(relief=tk.RAISED, bg="#d9d9d9")

        parts = []
        if alt_at: parts.append(f"Alt-tabbed at {alt_at}")
        if cycled: parts.append(f"Last cycled: {cycled}")
        self.debug_status.config(text=" | ".join(parts))

    def prompt_add_anomaly(self, room_name):
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Add Anomaly to {room_name}")
        dialog.geometry("400x300")
        dialog.transient(self.root)
        dialog.grab_set()

        # Center dialog
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() // 2) - 200
        y = self.root.winfo_rooty() + (self.root.winfo_height() // 2) - 150
        dialog.geometry(f"+{x}+{y}")

        ttk.Label(dialog, text="Name (Required):").pack(pady=5)
        name_var = tk.StringVar()
        name_entry = ttk.Entry(dialog, textvariable=name_var, width=40)
        name_entry.pack()
        name_entry.focus_set()

        ttk.Label(dialog, text="Type (e.g. object replacement):").pack(pady=5)
        type_var = tk.StringVar(value="Unknown")
        type_entry = ttk.Entry(dialog, textvariable=type_var, width=40)
        type_entry.pack()

        ttk.Label(dialog, text="Description:").pack(pady=5)
        desc_text = tk.Text(dialog, height=4, width=40)
        desc_text.pack(pady=5)

        def on_ok():
            name = name_var.get().strip()
            if not name:
                messagebox.showerror("Error", "Name is required.")
                return
            anom_type = type_var.get().strip()
            description = desc_text.get("1.0", tk.END).strip()
            
            if self.backend.add_new_anomaly(self.current_map.get(), room_name, name, anom_type, description):
                self.on_map_change(None)
                dialog.destroy()
            else:
                messagebox.showerror("Error", "Anomaly already exists!")

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="OK", command=on_ok).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT, padx=5)

    def show_failure_dialog(self):
        if self.backend.is_current_session_locked():
            messagebox.showwarning("Locked", "This session is locked. Unlock it first to report failures.")
            return
        FailureDialog(self.root, self.backend, self.current_map.get())

class FailureDialog:
    def __init__(self, parent, backend, current_map):
        self.parent = parent
        self.backend = backend
        self.current_map = current_map
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("It's over - Report Failure")
        self.dialog.geometry("700x400")
        self.dialog.transient(parent)
        self.dialog.grab_set()

        # Center dialog
        self.dialog.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() // 2) - 350
        y = parent.winfo_rooty() + (parent.winfo_height() // 2) - 200
        self.dialog.geometry(f"+{x}+{y}")

        ttk.Label(self.dialog, text="Report the 3 anomalies seen on the end-game screen:", font=("Arial", 11, "bold")).pack(pady=10)

        self.rows = []
        rooms = list(self.backend.data.get("Maps", {}).get(current_map, {}).get("Rooms", {}).keys())
        
        # All types currently in the JSON
        self.all_types = self.backend.get_all_types()

        container = ttk.Frame(self.dialog, padding=10)
        container.pack(fill=tk.BOTH, expand=True)

        # Header
        header = ttk.Frame(container)
        header.pack(fill=tk.X, pady=5)
        ttk.Label(header, text="Room", width=20, font=("Arial", 9, "bold")).pack(side=tk.LEFT, padx=5)
        ttk.Label(header, text="Reported type", width=25, font=("Arial", 9, "bold")).pack(side=tk.LEFT, padx=5)
        ttk.Label(header, text="Link to database (optional)", width=35, font=("Arial", 9, "bold")).pack(side=tk.LEFT, padx=5)

        for i in range(3):
            row_frame = ttk.Frame(container)
            row_frame.pack(fill=tk.X, pady=5)

            # Room
            room_var = tk.StringVar()
            room_combo = ttk.Combobox(row_frame, textvariable=room_var, values=rooms, width=18, state="readonly")
            room_combo.pack(side=tk.LEFT, padx=5)

            # Type
            type_var = tk.StringVar()
            # Initial types are map-wide, but will be filtered by room selection
            type_combo = ttk.Combobox(row_frame, textvariable=type_var, values=self.all_types, width=23)
            type_combo.pack(side=tk.LEFT, padx=5)
            
            # Linked Anomaly
            link_var = tk.StringVar()
            link_combo = ttk.Combobox(row_frame, textvariable=link_var, values=["None"], state="readonly", width=35)
            link_combo.pack(side=tk.LEFT, padx=5)

            # Store references
            row_data = {
                "room_var": room_var, "type_var": type_var, "link_var": link_var, 
                "link_combo": link_combo, "type_combo": type_combo,
                "room_types": self.all_types
            }
            self.rows.append(row_data)

            # Bind events
            room_combo.bind("<<ComboboxSelected>>", lambda e, rv=room_var, i=i: self.update_anomaly_list(rv.get(), i))
            type_combo.bind('<KeyRelease>', lambda e, c=type_combo, i=i: self.on_type_search(e, c, i))

        btn_frame = ttk.Frame(self.dialog)
        btn_frame.pack(pady=20)
        ttk.Button(btn_frame, text="Submit Report", command=self.submit).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="Cancel", command=self.dialog.destroy).pack(side=tk.LEFT, padx=10)

    def update_anomaly_list(self, room_name, row_index):
        """Updates both the anomaly link list and the suggested types based on room."""
        if not room_name: return
        
        row = self.rows[row_index]
        link_combo = row["link_combo"]
        type_combo = row["type_combo"]
        
        # Update Links
        anomalies = self.backend.get_room_anomalies(self.current_map, room_name)
        link_combo.config(values=["None"] + anomalies)
        link_combo.set("None")
        
        # Update suggested Types for this room
        room_types = self.backend.get_room_types(self.current_map, room_name)
        row["room_types"] = room_types
        type_combo.config(values=room_types)

    def on_type_search(self, event, combo, row_index):
        """Filters the dropdown values as the user types."""
        value = combo.get()
        room_types = self.rows[row_index]["room_types"]
        
        if value == '':
            combo['values'] = room_types
        else:
            filtered = [item for item in room_types if value.lower() in item.lower()]
            combo['values'] = filtered
        
        # Open dropdown if there are matches
        if combo['values']:
            # We use try/except as some systems/versions might flicker on immediate open
            try:
                combo.event_generate('<Down>')
            except:
                pass

    def submit(self):
        if self.backend.is_current_session_locked():
            messagebox.showwarning("Locked", "This historical session is LOCKED. Unlock it (🔓) to make changes.")
            return

        reports = []
        for i, row in enumerate(self.rows):
            room = row["room_var"].get()
            reported_type = row["type_var"].get().strip()
            link = row["link_var"].get()

            # Validate each entry
            if not room:
                messagebox.showerror("Error", f"Please select a room for entry {i+1}.")
                return
            if not reported_type:
                messagebox.showerror("Error", f"Please enter/select a type for entry {i+1}.")
                return
            
            # Strictly validate the type against the database
            if reported_type not in self.all_types:
                messagebox.showerror("Invalid Type", f"'{reported_type}' is not a valid category in your database. Please select an existing type.")
                return

            reports.append({
                "room": room,
                "reported_type": reported_type,
                "linked_anomaly": link.split(": (")[0] if link != "None" else "None"
            })

        if self.backend.add_failure_report(self.current_map, reports):
            msg = f"Failure report saved for shift ID {self.backend.session_id}."
            if any(r["linked_anomaly"] != "None" for r in reports):
                msg += "\n\nMaster database updated for linked anomalies."
            messagebox.showinfo("Success", msg)
            self.dialog.destroy()
            self.parent.update_session_view()
        else:
            messagebox.showerror("Error", "Failed to save report.")

if __name__ == "__main__":
    root = tk.Tk()
    app = AnomalyTrackerApp(root)
    root.mainloop()
