# Analysis Features — Purpose & Design

This doc exists to prevent drift when modifying the analytical parts of the tracker.
Terminology: we say **shift** (not session) throughout.

## Anomalies Likely Excluded (main window, lower pane)

**Purpose:** Gameplay aid — "what's excluded from THIS shift right now?"

Shows anomalies predicted to be absent from the current shift based on what you've already logged.
Updates in real-time as you log anomalies. Cross-references pair-based exclusion detection
with known exclusion groups to present predictions in context.

**Display:** Uses a hierarchical tree view:
- **Grouped exclusions:** When excluded anomalies belong to a known exclusion group, they appear
  under a collapsible group header showing all members, certainty, and which members are active
  (logged this shift). This gives the user immediate context: "these exclusions are part of the
  same pattern."
- **Ungrouped exclusions:** Pair-based exclusions that don't yet belong to a confirmed group
  appear as standalone items with their individual blockers.

This gradual presentation means early data shows raw pair exclusions, and as groups mature
they are automatically clustered under their group headers.

**Ghost row:** When no real predictions exist yet, the single closest-to-threshold candidate
appears as a grey row inside the tree itself (not below it). This shows what's most likely
to appear next as more data is collected. The ghost row disappears once real predictions
are available — it's only there to give early feedback when data is still sparse. Shows
the blocker anomalies in the Triggered By column when available. Priority order: candidates
blocked by expected overlap (closest to graduating), then insufficient shifts since first
seen, then insufficient sightings.

**Threshold display:** The panel footer shows the active thresholds so users know why
certain anomalies don't appear yet.

This is actionable during gameplay — you check it to narrow down what's left.

## Expert Audit (separate window, "Audit logs" button)

**Purpose:** Data quality tool — investigate your logging accuracy and anomaly behavior.

NOT a repeat of live prediction. This is for between-shift analysis.

**Scoping:** All audit tabs are filtered by both the selected **map** and **difficulty**.
Each map has its own anomaly pool and shift history, so mixing maps would produce
misleading statistics. The map defaults to whatever is currently selected in the main window.

### Tab 1: Group Violations (primary)
Finds probable user errors. After discovering exclusion groups, checks for anomalies that
*almost* fit a group but co-occur with one member in a small number of shifts. Those shifts
likely contain a misidentified anomaly.

Example: Group {Curtains, Painting} found. Wall color is exclusive with Curtains but
co-occurs with Painting in shifts 12, 19. Flag: "check shifts 12, 19."

### Tab 2: Anomaly Frequency
Shows **all known anomalies** for maps with log data, including those never seen (displayed
in grey). This makes it easy to spot which anomalies you haven't encountered yet vs which
are genuinely rare. Default sort: by rate (descending).

Per-anomaly occurrence rates with breakdowns:
- **Clean rate**: observations logged before alt-tab was pressed in that shift
- **Alt-tab rate**: observations logged after alt-tab was pressed
- **Cycled shift rate**: rate in shifts where camera cycling happened vs didn't
- Toggle: count from first sighting (default) vs all shifts

Helps answer: "does alt-tabbing create phantom sightings?" and "am I getting better at
spotting this anomaly over time?"

### Tab 3: Exclusion Groups (reference)
List of discovered groups with certainty levels. Reference view of what the system knows.

**Ghost row:** When no confirmed or likely groups exist yet, shows the single closest pair
to forming a group as a grey row (the pair with the highest certainty below the 70%
edge threshold). Disappears once real groups are found.

### Column sorting
All audit tabs and the live prediction panel support click-to-sort on column headings.
An arrow (▲/▼) indicates the currently sorted column and direction. Sorting persists
through data refreshes (e.g. toggling "Count from first sighting").

### Threshold display
Each tab shows its active thresholds in a footer label so users understand the filtering
criteria without needing to reference documentation.

## Key Thresholds

| Threshold | Value | Why |
|-----------|-------|-----|
| Min sightings | 2 | First sighting just proves it exists |
| Min expected overlap | 1.5 | Fixed per-pair value: `(n_blockers * n_a_eff) / N_eff`. Not map-dependent. |
| Min shifts since first seen | 3 | Need enough data for statistics |
| Group edge certainty | >70% | Minimum certainty for a pair to form an exclusion edge |
| Confirmed group certainty | >95% | Hypergeometric p-value < 0.05 |
| Violation detection | actual <= 2 AND ratio <= 0.4 | Catches near-misses without noise |

## Windowing

Both systems count shifts since first seen: for any pair of anomalies, only count shifts
from when both were first observed. This prevents early shifts (before the user learned
to spot an anomaly) from inflating exclusion evidence.
