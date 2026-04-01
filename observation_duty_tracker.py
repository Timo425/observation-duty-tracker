import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import json
import os
import re
import colorsys
from backend import Backend


def _parse_sort_key(value):
    """Extract a numeric sort key from display values like '45%', '#12', '3.2 / 5', '1/10 shifts'."""
    s = str(value).strip()
    if s in ("", "\u2014", "—"):
        return (1, 0)  # blanks sort last
    # Percentage: "85%" or "CONFIRMED (95%)"
    m = re.search(r'(\d+(?:\.\d+)?)\s*%', s)
    if m:
        return (0, float(m.group(1)))
    # Fraction with slash: "3.2 / 5" or "8/12" or "3 / 10 shifts"
    m = re.match(r'(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)', s)
    if m:
        return (0, float(m.group(1)))
    # Leading number: "#12", "5", "3.7"
    m = re.match(r'#?(\d+(?:\.\d+)?)', s)
    if m:
        return (0, float(m.group(1)))
    # Fall back to case-insensitive string
    return (0, s.lower())


def _treeview_sort(tree, col, reverse, is_tree_col=False):
    """Sort a Treeview by column. Tracks sort state and shows arrow indicator."""
    items = [(tree.set(k, col) if not is_tree_col else tree.item(k, "text"), k)
             for k in tree.get_children("")]
    items.sort(key=lambda t: _parse_sort_key(t[0]), reverse=reverse)
    for idx, (_, k) in enumerate(items):
        tree.move(k, "", idx)

    # Update heading labels: clear old arrow, add new one
    arrow = " \u25bc" if reverse else " \u25b2"
    for c in tree._sort_columns:
        base = tree._sort_base_texts[c]
        tc = tree._sort_is_tree_col.get(c, False)
        if c == col:
            if tc:
                tree.heading("#0", text=base + arrow)
            else:
                tree.heading(c, text=base + arrow)
        else:
            if tc:
                tree.heading("#0", text=base)
            else:
                tree.heading(c, text=base)

    # Store current sort state for re-apply after data refresh
    tree._sort_state = (col, reverse, is_tree_col)

    # Toggle direction on next click
    cmd = lambda _col=col, _rev=not reverse, _tc=is_tree_col: _treeview_sort(tree, _col, _rev, _tc)
    if is_tree_col:
        tree.heading("#0", command=cmd)
    else:
        tree.heading(col, command=cmd)


def _reapply_sort(tree):
    """Re-apply the last sort after data has been refreshed."""
    state = getattr(tree, "_sort_state", None)
    if state:
        col, reverse, is_tree_col = state
        _treeview_sort(tree, col, reverse, is_tree_col)


def _bind_sort_headings(tree, columns, include_tree_col=False):
    """Bind click-to-sort on all column headings of a Treeview."""
    tree._sort_columns = list(columns)
    tree._sort_base_texts = {}
    tree._sort_is_tree_col = {}
    tree._sort_state = None

    if include_tree_col:
        tree._sort_columns.insert(0, "#0")
        tree._sort_base_texts["#0"] = tree.heading("#0", "text")
        tree._sort_is_tree_col["#0"] = True
        tree.heading("#0", command=lambda: _treeview_sort(tree, "#0", False, is_tree_col=True))

    for col in columns:
        tree._sort_base_texts[col] = tree.heading(col, "text")
        tree.heading(col, command=lambda c=col: _treeview_sort(tree, c, False))

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
        
        # Check if window is off-screen (Windows specific)
        self.root.update_idletasks()
        try:
            import ctypes
            # System metrics for virtual screen bounding box
            SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
            SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79

            user32 = ctypes.windll.user32
            vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
            vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
            vw = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
            vh = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)

            wx = self.root.winfo_x()
            wy = self.root.winfo_y()
            ww = self.root.winfo_width()
            wh = self.root.winfo_height()

            if (wx + ww <= vx) or (wx >= vx + vw) or (wy + wh <= vy) or (wy >= vy + vh):
                # Window is outside the virtual desktop bounds; reset it
                self.root.geometry(f"{ww}x{wh}+100+100")
                self.backend.window_size = f"{ww}x{wh}+100+100"
        except Exception:
            pass

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
        self._top_frame = top_frame

        nav_frame = ttk.LabelFrame(top_frame, text="Shift management", padding="5")
        ttk.Button(nav_frame, text="<", width=3, command=self.prev_shift).pack(side=tk.LEFT)
        self.session_label = ttk.Label(nav_frame, text=f"ID: {self.backend.session_id}", font=("Arial", 11, "bold"), width=7, anchor="center")
        self.session_label.pack(side=tk.LEFT, padx=5)
        ToolTip(self.session_label, "Current shift/session ID")
        self.anomaly_count_label = ttk.Label(nav_frame, text="(0)", font=("Arial", 10), foreground="#555")
        self.anomaly_count_label.pack(side=tk.LEFT, padx=(0, 5))
        ToolTip(self.anomaly_count_label, "Anomalies reported in this shift")

        # Lock Toggle Button
        self.lock_button = tk.Button(nav_frame, text="🔓", font=("Arial", 10), width=3, height=1, command=self.toggle_lock, relief=tk.FLAT)
        self.lock_button.pack(side=tk.LEFT, padx=2)
        ToolTip(self.lock_button, "Lock/Unlock historical session for editing")

        ttk.Button(nav_frame, text=">", width=3, command=self.next_shift).pack(side=tk.LEFT)
        self.activity_label = ttk.Label(nav_frame, text="Last activity: Never", font=("Arial", 9, "italic"), foreground="gray")
        self.activity_label.pack(side=tk.LEFT, padx=10)
        new_shift_btn = ttk.Button(nav_frame, text="New shift", command=self.start_new_shift)
        new_shift_btn.pack(side=tk.LEFT, padx=10)
        ToolTip(new_shift_btn, "Start a new shift (increments session ID)")
        self.over_button = ttk.Button(nav_frame, text="It's over", command=self.show_failure_dialog)
        self.over_button.pack(side=tk.LEFT, padx=5)
        ToolTip(self.over_button, "Report the 3 anomalies shown on the end-game screen")
        audit_btn = ttk.Button(nav_frame, text="Audit logs", command=self.show_analytics_window)
        audit_btn.pack(side=tk.LEFT, padx=5)
        ToolTip(audit_btn, "Open the expert audit / analytics window")

        mode_frame = ttk.LabelFrame(top_frame, text="Settings", padding="5")

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

        self.alt_tab_btn = tk.Button(debug_frame, text="Alt-Tabbed", width=12, command=self.on_alt_tab_toggle, relief=tk.RAISED, bg="#d9d9d9")
        self.alt_tab_btn.pack(side=tk.LEFT, padx=3)
        self.alt_tab_btn.bind("<Button-3>", self.on_alt_tab_undo)
        ToolTip(self.alt_tab_btn, "Left-click: mark alt-tab. Right-click: undo")

        self.cycle_btn = tk.Button(debug_frame, text="Cycled cams", width=12, command=self.on_camera_cycle, relief=tk.RAISED, bg="#d9d9d9")
        self.cycle_btn.pack(side=tk.LEFT, padx=3)
        ToolTip(self.cycle_btn, "Record a camera cycling event (each press updates timestamp)")

        self.debug_status = ttk.Label(debug_frame, text="", font=("Arial", 8, "italic"), foreground="gray")
        self.debug_status.pack(side=tk.LEFT, padx=5)

        # Responsive top bar: sections wrap to new rows when window is too narrow
        self._top_sections = [nav_frame, mode_frame, debug_frame]
        self._top_layout_rows = None  # track current layout to avoid redundant updates
        top_frame.bind("<Configure>", self._reflow_top_bar)
        # Initial placement
        self.root.after_idle(self._reflow_top_bar)

        # Collectibles strip (compact, between top bar and main content)
        self.collectibles_frame = ttk.LabelFrame(self.root, text="Collectibles", padding="3")
        self.collectibles_frame.pack(fill=tk.X, padx=10, pady=(2, 0))
        self._collectible_buttons = {}

        # Content: Notebook + Live Panel
        pane = ttk.Frame(self.root)
        pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.notebook = ttk.Notebook(pane)
        self.notebook.pack(fill=tk.BOTH, expand=False, pady=(0, 5))

        # Live Analysis Panel
        self.live_frame = ttk.LabelFrame(pane, text="Anomalies likely excluded in this shift", padding="5")
        self.live_frame.pack(fill=tk.BOTH, expand=True)
        self.tree_wrapper = ttk.Frame(self.live_frame)
        self.tree_wrapper.pack(fill=tk.BOTH, expand=True)
        
        cols = ("Certainty", "Evidence", "Sightings", "Blockers")
        self.live_tree = ttk.Treeview(self.tree_wrapper, columns=cols, show="tree headings", height=5)
        self.live_tree.heading("#0", text="Anomaly / Group")
        self.live_tree.heading("Certainty", text="Certainty")
        self.live_tree.heading("Evidence", text="Evidence (Shifts)")
        self.live_tree.heading("Sightings", text="Sights")
        self.live_tree.heading("Blockers", text="Triggered By")
        self.live_tree.column("#0", width=220, minwidth=20, stretch=True)
        self.live_tree.column("Certainty", width=150, minwidth=20, stretch=False)
        self.live_tree.column("Evidence", width=100, minwidth=20, anchor="center", stretch=False)
        self.live_tree.column("Sightings", width=50, minwidth=20, anchor="center", stretch=False)
        self.live_tree.column("Blockers", width=300, minwidth=20, stretch=True)
        
        tree_scroll = ttk.Scrollbar(self.tree_wrapper, orient="vertical", command=self.live_tree.yview)
        self.live_tree.configure(yscrollcommand=tree_scroll.set)

        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.live_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        _bind_sort_headings(self.live_tree, cols, include_tree_col=True)

        # Failure Summary Section (Hidden by default)
        self.failure_frame = ttk.LabelFrame(self.live_frame, text="⚠️ Anomalies took over this shift", padding="5")
        self.failure_label = ttk.Label(self.failure_frame, text="", foreground="#D35400", font=("Arial", 10, "bold"), wraplength=1000)
        self.failure_label.pack(fill=tk.X)
        
        # Tags for analysis coloring
        self.live_tree.tag_configure("REPORTED", background="#FFCC80") # Light Orange
        self.live_tree.tag_configure("GROUP_HEADER", background="#E8EAF6", font=("Arial", 9, "bold")) # Light indigo
        self.live_tree.tag_configure("HOVER_HIGHLIGHT", background="#B3E5FC") # Light blue highlight
        self.live_tree.tag_configure("PENDING", foreground="#999999")
        self._tree_item_map = {} # anomaly_name -> list of tree item IDs

        self.threshold_label = ttk.Label(self.live_frame,
            text="Thresholds: \u22652 sightings, \u22653 shifts since first seen, expected overlap > 2.5",
            foreground="gray", font=("Arial", 8))
        self.threshold_label.pack(padx=5, pady=(0, 2))

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

    def _reflow_top_bar(self, event=None):
        """Arrange top bar sections into rows based on available width."""
        self._top_frame.update_idletasks()
        available = self._top_frame.winfo_width()
        if available <= 1:
            return  # Not yet rendered

        # Calculate how sections fit into rows
        pad = 10  # padding between sections
        rows = [[]]
        row_width = 0
        for section in self._top_sections:
            w = section.winfo_reqwidth() + pad
            if row_width > 0 and row_width + w > available:
                rows.append([])
                row_width = 0
            rows[-1].append(section)
            row_width += w

        # Check if layout changed
        layout_key = tuple(tuple(id(s) for s in r) for r in rows)
        if layout_key == self._top_layout_rows:
            return
        self._top_layout_rows = layout_key

        # Remove all sections from grid
        for section in self._top_sections:
            section.grid_forget()

        # Place into grid rows
        for row_idx, row_sections in enumerate(rows):
            for col_idx, section in enumerate(row_sections):
                section.grid(row=row_idx, column=col_idx, padx=5, pady=2, sticky="w")

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
        
        current_session_anoms = self.backend.get_current_session_anomalies(map_name)
        live_exclusions, _ = self.backend.get_live_exclusions(map_name, current_session_anoms)
        exclusions_map = {e["name"]: e for e in live_exclusions}
        missed_names = self.backend.get_missed_anomalies(map_name, self.backend.session_id)

        for room_name, btns in self._room_buttons.items():
            counts = self.backend.get_counts(map_name, room_name, max_session_id=self.backend.session_id)
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

        self.update_anomaly_count()

    def _highlight_prediction(self, anomaly_name):
        """Highlight matching anomaly rows in the live prediction tree."""
        for item_id in self._tree_item_map.get(anomaly_name, []):
            tags = list(self.live_tree.item(item_id, "tags"))
            if "HOVER_HIGHLIGHT" not in tags:
                tags.append("HOVER_HIGHLIGHT")
                self.live_tree.item(item_id, tags=tags)
                self.live_tree.see(item_id)

    def _unhighlight_prediction(self, anomaly_name):
        """Remove highlight from matching anomaly rows in the live prediction tree."""
        for item_id in self._tree_item_map.get(anomaly_name, []):
            tags = [t for t in self.live_tree.item(item_id, "tags") if t != "HOVER_HIGHLIGHT"]
            self.live_tree.item(item_id, tags=tags)

    def flash_status(self, text, duration=3000):
        """Show a status message in red that reverts after duration ms."""
        self.status_label.config(text=text, foreground="red")
        self.root.after(duration, lambda: self.status_label.config(foreground="black"))

    def update_anomaly_count(self):
        map_name = self.current_map.get()
        count = len(self.backend.get_current_session_anomalies(map_name)) if map_name else 0
        self.anomaly_count_label.config(text=f"({count})")

    def show_analytics_window(self):
        win = tk.Toplevel(self.root)
        win.title("Expert Audit")
        win.geometry("1050x700")

        # Header: title + difficulty filter + refresh
        header = ttk.Frame(win, padding=10)
        header.pack(fill=tk.X)
        ttk.Label(header, text="Expert Audit", font=("Arial", 12, "bold")).pack(side=tk.LEFT)

        filter_frame = ttk.Frame(header)
        filter_frame.pack(side=tk.RIGHT)

        ttk.Label(filter_frame, text="Map:").pack(side=tk.LEFT, padx=5)
        map_names = list(self.data.get("Maps", {}).keys())
        audit_map = tk.StringVar(value=self.current_map.get())
        map_combo = ttk.Combobox(filter_frame, textvariable=audit_map, values=map_names, width=20, state="readonly")
        map_combo.pack(side=tk.LEFT)

        ttk.Label(filter_frame, text="Difficulty:").pack(side=tk.LEFT, padx=5)
        supported_diffs = self.data.get("Difficulties", ["Normal", "Hard"])
        audit_diff = tk.StringVar(value=self.backend.difficulty)
        diff_combo = ttk.Combobox(filter_frame, textvariable=audit_diff, values=supported_diffs, width=10, state="readonly")
        diff_combo.pack(side=tk.LEFT)

        # Tabbed notebook
        notebook = ttk.Notebook(win)
        notebook.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # --- Tab 1: Group Violations ---
        violations_frame = ttk.Frame(notebook)
        notebook.add(violations_frame, text="Group Violations")

        self._violations_empty_label = ttk.Label(
            violations_frame,
            text="No group violations detected \u2014 data looks clean.",
            foreground="gray", font=("Arial", 10))

        v_cols = ("group", "candidate", "conflicts", "shifts", "expected_actual")
        v_wrapper = ttk.Frame(violations_frame)
        v_wrapper.pack(fill="both", expand=True, padx=5, pady=5)
        violations_tree = ttk.Treeview(v_wrapper, columns=v_cols, show="headings")
        violations_tree.heading("group", text="Exclusion Group")
        violations_tree.heading("candidate", text="Candidate")
        violations_tree.heading("conflicts", text="Conflicts With")
        violations_tree.heading("shifts", text="Flagged Shifts")
        violations_tree.heading("expected_actual", text="Expected / Actual")

        violations_tree.column("group", width=300, minwidth=20, stretch=True)
        violations_tree.column("candidate", width=180, minwidth=20, stretch=False)
        violations_tree.column("conflicts", width=150, minwidth=20, stretch=False)
        violations_tree.column("shifts", width=150, minwidth=20, anchor="center", stretch=False)
        violations_tree.column("expected_actual", width=130, minwidth=20, anchor="center", stretch=False)
        v_scroll = ttk.Scrollbar(v_wrapper, orient="vertical", command=violations_tree.yview)
        violations_tree.configure(yscrollcommand=v_scroll.set)
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        violations_tree.pack(side=tk.LEFT, fill="both", expand=True)
        _bind_sort_headings(violations_tree, v_cols)

        violations_tree.tag_configure("violation", background="#ffcccc")
        ttk.Label(violations_frame, text="Thresholds: actual overlap \u2264 2, overlap ratio \u2264 0.4, min expected overlap > 2.5",
                  foreground="gray", font=("Arial", 8)).pack(padx=5, pady=(0, 3))

        # --- Tab 2: Anomaly Frequency ---
        freq_frame = ttk.Frame(notebook)
        notebook.add(freq_frame, text="Anomaly Frequency")

        freq_controls = ttk.Frame(freq_frame)
        freq_controls.pack(fill=tk.X, padx=5, pady=5)
        first_seen_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(freq_controls, text="Count from first sighting",
                        variable=first_seen_var).pack(side=tk.LEFT)

        f_cols = ("name", "rooms", "rate", "clean", "alttab", "cycled", "first_seen", "shifts")
        f_wrapper = ttk.Frame(freq_frame)
        f_wrapper.pack(fill="both", expand=True, padx=5, pady=5)
        freq_tree = ttk.Treeview(f_wrapper, columns=f_cols, show="headings")
        freq_tree.heading("name", text="Anomaly")
        freq_tree.heading("rooms", text="Room(s)")
        freq_tree.heading("rate", text="Rate")
        freq_tree.heading("clean", text="Clean Rate")
        freq_tree.heading("alttab", text="Alt-Tab Rate")
        freq_tree.heading("cycled", text="Cycled Shift")
        freq_tree.heading("first_seen", text="First Seen")
        freq_tree.heading("shifts", text="Shifts")

        freq_tree.column("name", width=180, minwidth=20, stretch=True)
        freq_tree.column("rooms", width=150, minwidth=20, stretch=True)
        freq_tree.column("rate", width=70, minwidth=50, anchor="center", stretch=False)
        freq_tree.column("clean", width=90, minwidth=70, anchor="center", stretch=False)
        freq_tree.column("alttab", width=100, minwidth=70, anchor="center", stretch=False)
        freq_tree.column("cycled", width=100, minwidth=70, anchor="center", stretch=False)
        freq_tree.column("first_seen", width=80, minwidth=60, anchor="center", stretch=False)
        freq_tree.column("shifts", width=70, minwidth=50, anchor="center", stretch=False)
        f_scroll = ttk.Scrollbar(f_wrapper, orient="vertical", command=freq_tree.yview)
        freq_tree.configure(yscrollcommand=f_scroll.set)
        f_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        freq_tree.pack(side=tk.LEFT, fill="both", expand=True)
        _bind_sort_headings(freq_tree, f_cols)
        # Default sort by rate descending
        freq_tree._sort_state = ("rate", True, False)
        freq_tree.tag_configure("never_seen", foreground="#999999")
        ttk.Label(freq_frame, text="Shows all known anomalies. Grey = never seen. Rates count from first sighting when toggled.",
                  foreground="gray", font=("Arial", 8)).pack(padx=5, pady=(0, 3))

        # --- Tab 3: Exclusion Groups ---
        groups_frame = ttk.Frame(notebook)
        notebook.add(groups_frame, text="Exclusion Groups")

        g_cols = ("members", "size", "certainty", "analyzed", "status")
        g_wrapper = ttk.Frame(groups_frame)
        g_wrapper.pack(fill="both", expand=True, padx=5, pady=5)
        groups_tree = ttk.Treeview(g_wrapper, columns=g_cols, show="headings")
        groups_tree.heading("members", text="Group Members")
        groups_tree.heading("size", text="Size")
        groups_tree.heading("certainty", text="Certainty")
        groups_tree.heading("analyzed", text="Shifts Analyzed")
        groups_tree.heading("status", text="Status")

        groups_tree.column("members", width=400, minwidth=20, stretch=True)
        groups_tree.column("size", width=50, minwidth=40, anchor="center", stretch=False)
        groups_tree.column("certainty", width=80, minwidth=70, anchor="center", stretch=False)
        groups_tree.column("analyzed", width=110, minwidth=20, anchor="center", stretch=False)
        groups_tree.column("status", width=200, minwidth=20, stretch=False)
        g_scroll = ttk.Scrollbar(g_wrapper, orient="vertical", command=groups_tree.yview)
        groups_tree.configure(yscrollcommand=g_scroll.set)
        g_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        groups_tree.pack(side=tk.LEFT, fill="both", expand=True)
        _bind_sort_headings(groups_tree, g_cols)

        groups_tree.tag_configure("confirmed", background="#ccffcc")
        groups_tree.tag_configure("likely", background="#fff0cc")
        groups_tree.tag_configure("developing", foreground="#999999")
        ttk.Label(groups_frame, text="Thresholds: confirmed > 95% certainty (p < 0.05). Min 2 sightings per anomaly, min 3 shifts since first seen.",
                  foreground="gray", font=("Arial", 8)).pack(padx=5, pady=(0, 3))

        # Store references for refresh
        self._audit_trees = {
            "violations": violations_tree,
            "freq": freq_tree,
            "groups": groups_tree,
        }
        self._audit_first_seen_var = first_seen_var

        self._audit_map_var = audit_map

        def refresh(*args):
            self._refresh_audit(audit_diff.get(), audit_map.get())

        ttk.Button(header, text="Refresh", command=refresh).pack(side=tk.RIGHT, padx=5)
        audit_diff.trace_add("write", refresh)
        audit_map.trace_add("write", refresh)
        first_seen_var.trace_add("write", refresh)
        refresh()

    def _refresh_audit(self, target_diff, target_map=None):
        trees = self._audit_trees

        # --- Violations tab ---
        vt = trees["violations"]
        for item in vt.get_children():
            vt.delete(item)

        results = self.backend.analyze_exclusivity(target_difficulty=target_diff, target_map=target_map)

        violations = results.get("violations", [])
        if violations:
            self._violations_empty_label.pack_forget()
            for v in violations:
                group_str = ", ".join(v["group_names"])
                shifts_str = ", ".join(f"#{s}" for s in v["conflict_shifts"])
                exp_act = f"{v['expected_overlap']:.1f} / {v['actual_overlap']}"
                vt.insert("", tk.END, values=(
                    group_str,
                    v["candidate"],
                    v["conflicts_with"],
                    shifts_str,
                    exp_act,
                ), tags=("violation",))
        else:
            self._violations_empty_label.pack(pady=20)

        # --- Frequency tab ---
        ft = trees["freq"]
        for item in ft.get_children():
            ft.delete(item)

        from_first = self._audit_first_seen_var.get()
        freqs = self.backend.get_anomaly_frequencies(
            target_difficulty=target_diff, from_first_seen=from_first, target_map=target_map)

        def fmt_rate(val):
            return f"{val:.0%}" if val is not None else "\u2014"

        for f in freqs:
            fs = f["first_seen"]
            fs_str = f"#{fs}" if fs is not None else "\u2014"
            tag = ("never_seen",) if fs is None else ()
            ft.insert("", tk.END, values=(
                f["name"],
                f["rooms"],
                fmt_rate(f["overall_rate"]),
                fmt_rate(f["clean_rate"]),
                fmt_rate(f["alt_tab_rate"]),
                fmt_rate(f["cycled_shift_rate"]),
                fs_str,
                f"{f['total_shifts']}/{f['eligible_shifts']}",
            ), tags=tag)

        # --- Groups tab ---
        gt = trees["groups"]
        for item in gt.get_children():
            gt.delete(item)

        for g in results.get("groups", []):
            members_str = ", ".join(
                f"{m['name']} ({m['sightings']} sightings)" for m in g["members"])
            tag = "confirmed" if "CONFIRMED" in g["status"] else "likely"
            gt.insert("", tk.END, values=(
                members_str,
                g["size"],
                f"{g['certainty']:.0%}",
                g["N"],
                g["status"],
            ), tags=(tag,))

        # Ghost row: closest pair to forming a group
        developing = results.get("best_developing")
        if developing:
            members_str = ", ".join(developing["members"])
            gt.insert("", tk.END, values=(
                members_str,
                2,
                f"{developing['certainty']:.0%}",
                developing["N"],
                developing["reason"],
            ), tags=("developing",))

        # Re-apply column sort after data refresh
        for t in trees.values():
            _reapply_sort(t)

    def populate_room_tab(self, tab, room_name, room_anomalies):
        self._room_buttons[room_name] = {}
        
        canvas = tk.Canvas(tab, highlightthickness=0)
        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        def _on_frame_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.configure(height=e.height)

        scrollable_frame.bind("<Configure>", _on_frame_configure)
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
        
        self.create_buttons(scrollable_frame, room_name, self.data.get("Global", []))
        
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
            tip = f"{desc}\n\nRight-click to undo" if desc else "Right-click to undo"
            ToolTip(btn, tip)
            # Bind after ToolTip so both coexist
            btn.bind("<Enter>", lambda e, n=name: self._highlight_prediction(n), add="+")
            btn.bind("<Leave>", lambda e, n=name: self._unhighlight_prediction(n), add="+")

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
        result = self.backend.get_live_exclusions_with_groups(map_name, current_anoms)
        live_exclusions = result["exclusions"]
        group_summaries = result["groups"]
        failure_details = self.backend.get_failure_details(map_name, self.backend.session_id)

        for item in self.live_tree.get_children():
            self.live_tree.delete(item)
        self._tree_item_map = {}

        # 1. Update Failure Summary Frame
        if failure_details:
            summary_parts = []
            for f in failure_details:
                name = f["linked_anomaly"] if f["linked_anomaly"] != "None" else f["type"]
                summary_parts.append(f"• {name} in {f['room']}")

            self.failure_label.config(text="\n".join(summary_parts))
            self.failure_frame.pack(fill=tk.X, pady=(5, 0), after=self.tree_wrapper)
        else:
            self.failure_frame.pack_forget()

        # 2. Show Mutual Exclusivity Predictions (grouped by exclusion group)
        # Separate grouped vs ungrouped exclusions
        grouped = {}  # group_idx -> [exclusions]
        ungrouped = []
        for e in live_exclusions:
            gidx = e.get("group_idx", -1)
            if gidx >= 0:
                grouped.setdefault(gidx, []).append(e)
            else:
                ungrouped.append(e)

        # Render grouped exclusions under collapsible parent nodes
        group_summary_map = {g["idx"]: g for g in group_summaries}
        for gidx in sorted(grouped.keys()):
            members_in_group = grouped[gidx]
            gs = group_summary_map.get(gidx, {})
            all_members = gs.get("members", [])
            active = gs.get("active_members", [])
            status = gs.get("status", "")
            group_certainty = gs.get("certainty", 0)

            # Group header: show active members (logged) and overall status
            active_str = ", ".join(active) if active else "?"
            header_text = f"Group ({len(all_members)}): {', '.join(all_members)}"
            status_str = f"{status} ({group_certainty:.0%})"
            parent_id = self.live_tree.insert("", tk.END, text=header_text,
                values=(status_str, "", "", f"Active: {active_str}"),
                open=True, tags=("GROUP_HEADER",))

            for e in members_in_group:
                evidence_str = f"{e['n_blockers']} / {e['N']} shifts"
                certainty_str = f"{e['certainty_status']} ({e['certainty']:.0%})"
                item_id = self.live_tree.insert(parent_id, tk.END, text=e["name"],
                    values=(certainty_str, evidence_str, e["count"], ", ".join(e["blockers"])))
                self._tree_item_map.setdefault(e["name"], []).append(item_id)

        # Render ungrouped exclusions as top-level items
        for e in ungrouped:
            evidence_str = f"{e['n_blockers']} / {e['N']} shifts"
            certainty_str = f"{e['certainty_status']} ({e['certainty']:.0%})"
            item_id = self.live_tree.insert("", tk.END, text=e["name"],
                values=(certainty_str, evidence_str, e["count"], ", ".join(e["blockers"])))
            self._tree_item_map.setdefault(e["name"], []).append(item_id)

        # 3. Show closest-to-threshold candidate as a ghost row (only if no real data yet)
        best_pending = result.get("best_pending")
        if best_pending and not live_exclusions:
            blockers_str = ", ".join(best_pending.get("blockers", []))
            self.live_tree.insert("", tk.END, text=f"{best_pending['name']}",
                values=(best_pending["reason"], "", best_pending["count"], blockers_str),
                tags=("PENDING",))

        stats = self.backend.get_stats(map_name, max_session_id=self.backend.session_id)
        self.live_frame.config(text=f"Anomalies likely excluded in this shift (Shifts 1-{self.backend.session_id}: {stats['total_sessions']} total)")

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
        else:
            self.flash_status(f"Nothing to undo for: {name}")

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
        self.update_anomaly_count()
        self.refresh_map_ui()

    def toggle_lock(self):
        self.backend.toggle_session_lock()
        self.update_session_view()

    def on_alt_tab_toggle(self):
        if self.backend.is_current_session_locked():
            return
        ts = self.backend.mark_alt_tabbed()
        self.alt_tab_btn.config(relief=tk.SUNKEN, bg="#ffaaaa")
        self.debug_status.config(text=f"Alt-tabbed at {ts}")

    def on_alt_tab_undo(self, event=None):
        if self.backend.is_current_session_locked():
            return
        if not self.backend.get_alt_tabbed_at():
            self.flash_status("Alt-tab not active, nothing to undo")
            return
        self.backend.undo_alt_tabbed()
        self.alt_tab_btn.config(relief=tk.RAISED, bg="#d9d9d9")
        self.debug_status.config(text="Alt-tab undone")

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
