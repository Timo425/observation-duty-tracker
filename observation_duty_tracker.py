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
        
        self.setup_ui()
        self.update_live_analysis()

    def setup_ui(self):
        # Top Frame: Session & Map Control
        top_frame = ttk.Frame(self.root, padding="10")
        top_frame.pack(fill=tk.X)

        nav_frame = ttk.LabelFrame(top_frame, text="Shift Management", padding="5")
        nav_frame.pack(side=tk.LEFT, padx=5)
        ttk.Button(nav_frame, text="<", width=3, command=self.prev_shift).pack(side=tk.LEFT)
        self.session_label = ttk.Label(nav_frame, text=f"ID: {self.backend.session_id}", font=("Arial", 11, "bold"), width=8, anchor="center")
        self.session_label.pack(side=tk.LEFT, padx=5)
        ttk.Button(nav_frame, text=">", width=3, command=self.next_shift).pack(side=tk.LEFT)
        self.activity_label = ttk.Label(nav_frame, text="Last activity: Never", font=("Arial", 9, "italic"), foreground="gray")
        self.activity_label.pack(side=tk.LEFT, padx=10)
        ttk.Button(nav_frame, text="New Shift", command=self.start_new_shift).pack(side=tk.LEFT, padx=10)
        ttk.Button(nav_frame, text="Audit Logs", command=self.show_analytics_window).pack(side=tk.LEFT, padx=5)

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

        # Content: Notebook + Live Panel
        pane = ttk.Panedwindow(self.root, orient=tk.VERTICAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.notebook = ttk.Notebook(pane)
        pane.add(self.notebook, weight=3)

        # Live Analysis Panel
        live_frame = ttk.LabelFrame(pane, text="Live Prediction Analysis (Mutual Exclusivity)", padding="5")
        pane.add(live_frame, weight=1)
        
        cols = ("Anomaly", "E (Surprise)", "Likelihood", "N", "Total Sights", "Conflict With")
        self.live_tree = ttk.Treeview(live_frame, columns=cols, show="headings", height=8)
        self.live_tree.heading("Anomaly", text="Anomaly Name")
        self.live_tree.heading("E (Surprise)", text="Surprise (E)")
        self.live_tree.heading("Likelihood", text="Exclusivity %")
        self.live_tree.heading("N", text="N (Data)")
        self.live_tree.heading("Total Sights", text="Sightings")
        self.live_tree.heading("Conflict With", text="Conflict With")
        self.live_tree.column("Anomaly", width=180)
        self.live_tree.column("E (Surprise)", width=80)
        self.live_tree.column("Likelihood", width=100)
        self.live_tree.column("N", width=50, anchor="center")
        self.live_tree.column("Total Sights", width=80, anchor="center")
        self.live_tree.pack(fill=tk.BOTH, expand=True)

        # Bottom Frame: Status
        status_frame = ttk.Frame(self.root, padding="5")
        status_frame.pack(fill=tk.X)
        self.status_label = ttk.Label(status_frame, text="Ready")
        self.status_label.pack(side=tk.LEFT)
        self.data_weight_label = ttk.Label(status_frame, text="Total Sessions: 0", font=("Arial", 9, "italic"))
        self.data_weight_label.pack(side=tk.RIGHT, padx=10)

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

    def on_game_change(self, *args):
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
        
        self.on_map_change(None)

    def on_difficulty_change(self, *args):
        self.backend.set_difficulty(self.current_difficulty.get())
        self.status_label.config(text=f"Mode switched to {self.backend.difficulty}")
        self.on_map_change(None)

    def on_map_change(self, event):
        map_name = self.current_map.get()
        if map_name:
            self.backend.set_map(map_name)

        # Save current tab selection if possible
        selected_index = 0
        try:
            selected_index = self.notebook.index("current")
        except:
            pass

        for tab in self.notebook.tabs():
            self.notebook.forget(tab)
        
        map_name = self.current_map.get()
        rooms = self.data["Maps"].get(map_name, {}).get("Rooms", {})
        for room_name, anomalies in rooms.items():
            tab = ttk.Frame(self.notebook)
            self.notebook.add(tab, text=room_name)
            self.populate_room_tab(tab, room_name, anomalies)
        
        # Restore tab selection
        if selected_index < len(self.notebook.tabs()):
            self.notebook.select(selected_index)
            
        self.update_live_analysis()

    def show_analytics_window(self):
        win = tk.Toplevel(self.root)
        win.title(f"Global Analytics - {self.backend.difficulty}")
        win.geometry("900x600")
        
        # Tools for global analysis
        header = ttk.Frame(win, padding=10)
        header.pack(fill=tk.X)
        ttk.Label(header, text="Full Database Exclusivity & Error Report", font=("Arial", 12, "bold")).pack(side=tk.LEFT)
        
        desc = ttk.Label(win, text="Flags pairs with high Expected Overlap (E) but low Actual Overlap. 'POTENTIAL ERROR' suggests a data entry mistake.", foreground="gray")
        desc.pack(pady=5)

        cols = ("Pair", "Actual", "Expected (E)", "Likelihood", "N", "Status")
        tree = ttk.Treeview(win, columns=cols, show="headings")
        tree.heading("Pair", text="Anomaly Pair (A vs B)")
        tree.heading("Actual", text="Actual Overlap")
        tree.heading("Expected (E)", text="Expected (E)")
        tree.heading("Likelihood", text="Likelihood")
        tree.heading("N", text="N")
        tree.heading("Status", text="Status")
        
        tree.column("Pair", width=550)
        tree.column("Actual", width=80, anchor="center")
        tree.column("Expected (E)", width=80, anchor="center")
        tree.column("Likelihood", width=80, anchor="center")
        tree.column("N", width=40, anchor="center")
        tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        tree.tag_configure("ERROR", background="#ffcccc", foreground="#990000")
        
        ttk.Button(header, text="Refresh Analysis", command=lambda: self.update_analytics_window(tree)).pack(side=tk.RIGHT)
        
        # Initial fill
        self.update_analytics_window(tree)

    def update_analytics_window(self, tree):
        for item in tree.get_children():
            tree.delete(item)
            
        results = self.backend.analyze_exclusivity()
        for r in results:
            pair_str = f"{r['pair'][0]} ({r['room1']})  <--->  {r['pair'][1]} ({r['room2']})"
            tag = "ERROR" if r['status'] == "POTENTIAL ERROR" else ""
            tree.insert("", tk.END, values=(
                pair_str, 
                r['actual'], 
                f"{r['expected']:.2f}", 
                f"{r['likelihood']:.2%}" if r['likelihood'] > 0 else "N/A",
                r['N'],
                r['status']
            ), tags=(tag,))

    def populate_room_tab(self, tab, room_name, room_anomalies):
        canvas = tk.Canvas(tab, highlightthickness=0)
        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        # Bindings for scrolling and scaling
        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        
        # Ensure scrollable_frame width stays in sync with canvas width
        def on_canvas_configure(event):
            canvas.itemconfig(canvas_frame, width=event.width)
        canvas.bind("<Configure>", on_canvas_configure)

        canvas_frame = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Mouse Wheel Support (Across different platforms)
        def _on_mouse_wheel(event):
            if event.num == 4 or event.delta > 0:
                canvas.yview_scroll(-1, "units")
            elif event.num == 5 or event.delta < 0:
                canvas.yview_scroll(1, "units")
        
        # Bind to canvas and all its children recursively
        canvas.bind_all("<MouseWheel>", _on_mouse_wheel) # Windows/macOS
        canvas.bind_all("<Button-4>", _on_mouse_wheel)   # Linux
        canvas.bind_all("<Button-5>", _on_mouse_wheel)   # Linux

        header_frame = ttk.Frame(scrollable_frame); header_frame.pack(fill=tk.X, pady=5)
        ttk.Label(header_frame, text=f"Room: {room_name}", font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        ttk.Button(header_frame, text="+ Add Anomaly", command=lambda r=room_name: self.prompt_add_anomaly(r)).pack(side=tk.RIGHT)
        self.create_buttons(scrollable_frame, room_name, room_anomalies)
        
        ttk.Separator(scrollable_frame, orient='horizontal').pack(fill='x', pady=10)
        global_header = ttk.Frame(scrollable_frame); global_header.pack(fill=tk.X, pady=5)
        ttk.Label(global_header, text="Global Anomalies", font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        ttk.Button(global_header, text="+ Add Global", command=lambda: self.prompt_add_anomaly("Global")).pack(side=tk.RIGHT)
        self.create_buttons(scrollable_frame, "Global", self.data.get("Global", []))
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def create_buttons(self, parent, room_name, anomalies):
        current_map = self.current_map.get()
        counts = self.backend.get_counts(current_map, room_name)
        current_session_anoms = self.backend.get_current_session_anomalies(current_map)
        live_exclusions = self.backend.get_live_exclusions(current_map, current_session_anoms)
        exclusions_map = {e["name"]: e for e in live_exclusions}
        
        grid_frame = ttk.Frame(parent); grid_frame.pack(fill=tk.X)
        for c in range(3): grid_frame.columnconfigure(c, weight=1) # Allow columns to expand
        cols = 3
        sorted_anoms = sorted(anomalies, key=lambda x: x["name"])
        
        for i, anom in enumerate(sorted_anoms):
            name = anom["name"]; count = counts.get(name, 0)
            
            # Use tk.Button instead of ttk.Button for better Linux color support
            btn = tk.Button(grid_frame, text=f"{name} ({count})", width=25, height=2, wraplength=180, justify="center")
            btn.grid(row=i//cols, column=i%cols, padx=3, pady=3, sticky="ew")
            btn.bind("<Button-1>", lambda e, n=name, r=room_name: self.log_anomaly(n, r))
            btn.bind("<Button-3>", lambda e, n=name, r=room_name: self.undo_anomaly(n, r))

            # Tooltip
            excl_info = exclusions_map.get(name)
            desc = anom.get("description", anom.get("desc", ""))
            anom_type = anom.get("type", "Unknown")
            
            tip_text = f"NAME: {name}\nTYPE: {anom_type}"
            if desc: tip_text += f"\nDESC: {desc}"
            tip_text += f"\nTotal sightings: {count}"
            
            if excl_info:
                E = excl_info['expected_overlap']
                tip_text += f"\n\nEXPECTED overlap: {E:.2f} | ACTUAL: 0"
                tip_text += f"\nExclusivity Likelihood: {excl_info['likelihood']:.2%}"
            ToolTip(btn, tip_text)

            # Color Logic
            bg_color = "lightgray" # Default Linux gray
            fg_color = "black"
            
            if self.backend.is_logged_in_current_session(current_map, room_name, name):
                bg_color = "#90ee90" # Light Green
            elif excl_info:
                # Scaled Red Saturation based on E (1.0 to 5.0 scale)
                E = excl_info['expected_overlap']
                if E < 1.0:
                    sat = 0.15
                elif E >= 5.0:
                    sat = 1.0
                else:
                    sat = 0.2 + (E - 1.0) * (0.8 / 4.0)
                
                rgb = colorsys.hls_to_rgb(0, 0.5, sat)
                bg_color = '#%02x%02x%02x' % (int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255))
                # If very dark red, use white text (though at 0.5 lightness it should be fine)
            
            btn.config(bg=bg_color, fg=fg_color)

    def update_live_analysis(self):
        map_name = self.current_map.get()
        if not map_name: return
        
        current_anoms = self.backend.get_current_session_anomalies(map_name)
        exclusions = self.backend.get_live_exclusions(map_name, current_anoms)
        
        for item in self.live_tree.get_children():
            self.live_tree.delete(item)
            
        for e in exclusions:
            self.live_tree.insert("", tk.END, values=(
                e["name"], f"{e['expected_overlap']:.2f}", f"{e['likelihood']:.2%}", e["N"], e["count"], ", ".join(e["current_set"])
            ))

        stats = self.backend.get_stats(map_name)
        self.data_weight_label.config(text=f"Total Sessions for {map_name} [{self.backend.difficulty}]: {stats['total_sessions']}")

    def log_anomaly(self, name, room_name):
        current_map = self.current_map.get()
        if self.backend.is_logged_in_current_session(current_map, room_name, name):
            messagebox.showwarning("Duplicate", f"'{name}' is already logged in {room_name}.") ; return
        if self.backend.add_observation(current_map, room_name, name):
            self.status_label.config(text=f"Logged: {name}")
            self.update_session_view()

    def undo_anomaly(self, name, room_name):
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
        self.session_label.config(text=f"ID: {self.backend.session_id}")
        self.activity_label.config(text=f"Last activity: {self.backend.get_last_activity()}")
        self.on_map_change(None)

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

        ttk.Label(dialog, text="Type (e.g. Object Replacement):").pack(pady=5)
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

if __name__ == "__main__":
    root = tk.Tk()
    app = AnomalyTrackerApp(root)
    root.mainloop()
