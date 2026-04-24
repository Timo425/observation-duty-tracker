# Universal Observation Duty Tracker

This tool helps keep track of anomalies in the **I'm on Observation Duty** series. It is a universal, data-driven tracker that supports multiple games by simply adding new JSON anomaly definitions.

The goal is to reverse-engineer the game's anomaly selection algorithm through statistical observation — determining which anomalies form exclusion groups, their occurrence rates, and any hidden patterns, all from gameplay data alone.

## Features
- **Multi-Game Support:** Easily switch between different titles in the series.
- **Smart UI:** Automatically adapts to the features of each game (e.g., hiding difficulty options for games that don't have them).
- **Shift Management:** Navigate between shifts with `<`/`>`, start new ones, lock/unlock any shift, and review history. Historical shifts are auto-locked (🔒) to prevent accidental edits; shifts with an "It's over" report are also locked.
- **Per-Difficulty Sightings:** Anomaly buttons show the sighting count for the currently selected difficulty, and anomalies never caught on that difficulty are rendered in italic so you can tell at a glance which ones you still haven't ticked off on Normal vs. Hard.
- **Collectibles:** Special items (rubber ducky, ring, etc.) are shown in a separate compact strip, tracked as collected/not-collected rather than as anomalies.
- **"It's over" Failure Reporting:** Report the 3 anomalies shown on the end-game screen. Linked anomalies appear as Orange buttons in room tabs, and a summary section appears below the analysis panel.
- **Live Exclusivity Prediction:** Uses your full history up to (and including) the current shift to predict which anomalies are likely excluded from the current shift — updating in real-time as you log. Predictions are grouped under their exclusion group when known, showing which group members are active. Ungrouped pair exclusions appear individually until enough data confirms a group.
- **Audit Log:** Catches possible user reporting errors. When anomalies that belong to an exclusion group (i.e. should never appear together) show up in the same shift, it flags that shift for review — the player likely misidentified one of them. Also shows discovered exclusion groups as reference.
- **Debug: Glitch Tracking:** Two toggles to investigate suspected game glitches:
  - **Alt-Tabbed:** One-way toggle per shift. Once pressed, all subsequent observations are marked as potentially affected by alt-tabbing. Defaults to False.
  - **Camera Cycling:** Each press records a timestamp. Observations log the most recent cycling timestamp, allowing post-hoc analysis of time proximity between cycling and anomaly appearance.
- **Data-Driven:** Easily expandable by adding JSON files to the `data/` directory. Each anomaly has a stable UUID (`id` field) assigned on first load, so renaming an anomaly in JSON automatically propagates to the existing CSV logs on the next launch — no manual find-and-replace needed. Removing an anomaly from JSON while logged rows still reference it is flagged on startup as an orphan warning rather than silently dropping the history.

## Core Concepts

### Exclusion Groups
The game selects anomalies per shift such that certain anomalies are mutually exclusive — if one appears, the others in its group won't. Discovering these groups is the tool's primary analytical goal. Both live prediction and the audit log build on this.

### Difficulty-Exclusive Anomalies
The JSON anomaly pool for each map is the **union across difficulties** — every anomaly is listed once regardless of which mode it actually spawns on. In practice the game tends to split this pool: some anomalies only appear on Normal, others only on Hard. The tracker doesn't declare this upfront in the data; the **Anomalies Seen** audit tab surfaces it empirically through the per-difficulty ✓/— marks. With enough shifts logged, anything showing a perpetual — on one column is a strong candidate for being exclusive to the other mode (or just very rare — statistics can't fully separate those two without a schema hint).

### How the Math Works
- Anomalies need **at least 2 sightings** before they enter any analysis (first sighting just proves it exists).
- Pairs need an **expected overlap >= 2.5** before zero co-occurrence becomes statistically noteworthy (prevents false positives from sparse data).
- Groups are found by building a graph of never-co-occurring anomaly pairs and finding cliques (fully connected subgroups).
- With ~5 sessions, expect nothing. With 15-20+ sessions per difficulty, real patterns start emerging.

## Usage
Run the main tracker application:
```bash
python3 observation_duty_tracker.py
```

## Exclusivity Analysis
As you play and log anomalies, the tool collects data to determine which anomalies form exclusion groups.

To generate a text report of discovered exclusion groups:
```bash
python3 generate_conclusions.py
python3 generate_conclusions.py --output conclusions.txt  # save to file
```

## Tests
```bash
python3 -m unittest discover tests -v
```
