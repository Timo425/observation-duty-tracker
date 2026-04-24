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

**Scoping:** All audit tabs are filtered by the selected **map**. Most tabs are also
filtered by the selected **difficulty** — each map has its own anomaly pool and shift
history per difficulty, so mixing them would produce misleading statistics.
The one exception is **Anomalies Seen** (Tab 3), which is deliberately cross-difficulty
because the question it answers — "have I ever seen this anomaly at all?" — only
makes sense across modes. For that tab the difficulty dropdown does not filter;
it just moves a column highlight. The map defaults to whatever is currently
selected in the main window.

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
- **Clean rate**: rate in shifts where alt-tabbing was explicitly disabled (deliberately clean recording)
- **Alt-tab rate**: rate in shifts where alt-tabbing was on (the default)
- **Cycled shift rate**: rate in shifts where camera cycling was on (the default)
- Toggle: count from first sighting (default) vs all shifts

Alt-tabbing and cycling are both assumed ON by default because they match regular
play — alt-tab happens naturally, and when cycling is on we assume it's done right
after each anomaly is reported. The toggles flip either off for an entire shift if
you want a deliberately clean recording.

Helps answer: "does alt-tabbing create phantom sightings?" and "am I getting better at
spotting this anomaly over time?"

### Tab 3: Anomalies Seen (completion view)
Cross-difficulty "have I ever caught this?" view. Lists every anomaly defined for the
selected map (including Globals; excluding collectibles, which are tracked via toggle
not via CSV logs). Each row shows per-difficulty ✓/— marks plus a total-shifts count.

**Three visual tiers (using foreground colour):**
- **Grey** — never seen on any difficulty. The primary signal: anomalies still
  outstanding. Default sort brings these to the top.
- **Faded** — seen on another difficulty but not the currently selected one.
  Secondary signal: you've caught it once, but still need it on this mode.
- **Normal** — seen on the currently selected difficulty. "Done" on this mode.

**Difficulty dropdown behaviour:** The dropdown does NOT filter this tab (that would
defeat its purpose). Instead, it (a) prepends a ▶ marker to the matching "Seen on X"
column header and (b) drives the faded-vs-normal row split above. Switching the
dropdown re-renders the highlight without reloading the underlying data.

**Single-difficulty games (e.g. demo's `N/A`):** The per-difficulty split collapses
to a single "Seen" column since the split would be meaningless.

Helps answer: "which anomalies haven't I caught yet at all?" and "which have I
caught on Normal but still need on Hard (or vice versa)?"

### Tab 4: Exclusion Groups (reference)
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
| Min sightings | 2 | First sighting just proves existence. Need at least 2 before the anomaly enters any analysis. |
| Min expected overlap | 5 | Per-pair: `(n_blockers * n_a_eff) / N_eff` = "if independent, how many times would we expect them in the same shift?" If < 5, zero co-occurrence isn't surprising enough to flag. |
| Min shifts in window | 3 | The window (see below) must contain at least 3 shifts total before a pair is evaluated. With only 1-2 shifts, "never appeared together" is meaningless. |
| Group edge certainty | >70% | Minimum hypergeometric certainty for a pair to form an exclusion graph edge. Below this = "developing" (ghost row). |
| Confirmed group certainty | >95% | Weakest pair in a group needs p < 0.05 for CONFIRMED label. Below = LIKELY GROUP. |
| Violation detection | actual ≤ 2 AND ratio ≤ 0.4 | Flags anomalies that almost fit a group but co-occur with one member in 1-2 shifts. |

## Windowing

For any pair of anomalies (A, B), the system only looks at shifts from when **both**
were first observed. This is the "window" for that pair.

**How it works:**
1. Window starts at whichever anomaly was seen later: `max(first_seen(A), first_seen(B))`
2. Window includes **every shift** from that point to the current shift — not just
   shifts where A or B appeared
3. The window must have at least 3 shifts before the pair is evaluated at all

**Example:** A first seen shift 3, B first seen shift 7. You're on shift 14.
- Window = shifts 7 through 14 = **8 shifts** in the window
- The pair became evaluable at shift 9 (that's when the window first had 3 shifts)
- If A appeared in 4 of those 8 shifts and B in 3, expected overlap = (4 × 3) / 8 = 1.5
- Since 1.5 < 5 threshold, this pair is NOT flagged yet despite never co-occurring

**Why window?** Prevents early shifts (before you learned to spot an anomaly) from
inflating exclusion evidence.
