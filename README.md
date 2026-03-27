# Universal Observation Duty Tracker

This tool helps keep track of anomalies in the **I'm on Observation Duty** series. It is a universal, data-driven tracker that supports multiple games by simply adding new JSON anomaly definitions.

The goal is to reverse-engineer the game's anomaly selection algorithm through statistical observation — determining which anomalies are grouped together, their probabilities, and any hidden patterns, all from gameplay data alone.

## Features
- **Multi-Game Support:** Easily switch between different titles in the series.
- **Smart UI:** Automatically adapts to the features of each game (e.g., hiding difficulty options for games that don't have them).
- **Shift Logging:** Track anomalies by Session ID, Difficulty, Map, and Room.
- **Live Exclusivity Prediction:** During a shift, the GUI uses your historical logs to predict which anomalies are excluded based on what you've already found — helping you narrow down what to look for next.
- **Audit Log:** Flags suspicious co-occurrences — when two anomalies that almost never appear together (and are likely truly exclusive) suddenly show up in the same shift, it suggests one of them was probably misidentified.
- **Data-Driven:** Easily expandable by adding JSON files to the `data/` directory.

## Usage
Run the main tracker application:
```bash
python3 observation_duty_tracker.py
```

## Exclusivity Analysis
As you play and log anomalies, the tool collects data to determine which anomalies are grouped together (mutually exclusive — if one appears in a session, the others in its group won't).

To generate a report of discovered exclusivity groups:
```bash
python3 generate_conclusions.py
python3 generate_conclusions.py --output conclusions.txt  # save to file
```

The analysis improves with more sessions logged. Results start appearing after 3 sessions, but realistic conclusions require 15–20+ sessions per map/difficulty.

## Tests
```bash
python3 -m unittest discover tests -v
```
