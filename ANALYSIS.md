# Analysis Features — Spec & Design

> **This file is the spec.** Every analytical feature in the tracker —
> what it does, why it exists, and how it fits with the rest — is
> defined here. The whole document is the source of truth, not any
> single section. Read this before changing analytical code or
> behaviour, and update it whenever behaviour intentionally changes.
> Drift between this doc and the code is the bug.

**Terminology:** we say **shift** (not session) throughout.

## What "Global" means (read this first)

The JSON has two kinds of anomaly entries:

- **Per-room anomalies** — defined inside a specific map's specific room.
  Can only manifest in that room.

- **"Global" anomalies** — defined at the top level of the JSON. The
  same conceptual anomaly reoccurs across multiple maps (and often
  across multiple games in the series — Abyss, Rift, Camera
  Malfunction, etc.). The "global" label means the **definition** is
  shared across the game's maps; it does NOT mean the anomaly is
  roomless.

**Every sighting of a global is still in a specific room.** The CSV log
records `(Map, Room, Anomaly_Name)` for every sighting, including
globals. When a player reports a global in-game via the right-click
menu, they're observing a specific room and that room is the
sighting's location for analytical purposes.

**Globals do not appear in every room.** Which rooms a given global
can manifest in depends on the global — Abyss might appear in some
Lighthouse rooms but not others. Empirically, the rooms where a
global has been sighted are the rooms where it actually appears; the
data has the answer and we should let it speak.

**Globals do not appear on every map.** Some globals only show up on
some maps. Same caveat: data tells us.

**What this means for any report / table / view that lists anomalies
per room:** globals are listed under the actual rooms they've been
sighted in, with that room's specific occurrence count — **never as a
separate "Global" pseudo-room or catch-all bucket.** The display model
mirrors the data model: per-room. The only thing that distinguishes a
sighting of a global from a sighting of a per-room anomaly is which
JSON entry it links back to (top-level Global array vs nested under a
room) — and that's a data-model detail, not a presentation one.

The live GUI's room buttons render the per-room anomalies for the
current tab plus the globals that the tracker UI lets you log
*from* that room (an input-side convenience — the in-game RMB menu is
room-agnostic). The analysis output is the read-side and there
globals belong inline with the rooms they're observed in.



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

## Sighting-Driven Candidate Filter (room grid)

**Purpose:** Reduce visual noise on the room grid by hiding anomaly buttons
the user has had ample chance to sight on the current shift but never has.
The grid stays open during early game so first sightings are always
loggable.

**The rule:**

A **shift** is the (current map, current difficulty) tuple — the slice of
the game the user is actively playing. Each shift stands on its own
sighting history; the filter does not look at other (map, difficulty)
slices.

- `here`   = unique-shift count of this anomaly on the current (map, difficulty)
- `played` = total unique shifts the user has played on the current (map, difficulty)
- **Hide if `here == 0` AND `played >= MIN_SHIFTS_FOR_CANDIDATE_FILTER` (currently 10).**

This applies uniformly to per-room and Global anomalies. "Global" means
the anomaly isn't tied to a single room and may appear on multiple maps
— it does **not** mean one map's sightings should influence what's
displayed on another map. Each map's grid is judged purely on that map's
own evidence: if the user has played 30 Lighthouse shifts and never
sighted Rift there, the filter hides Rift on Lighthouse regardless of
how many Rift sightings exist on Airplane.

**Warmup gate.** Below the `played` threshold, "never seen here" is just
lack of playtime, not evidence of absence — applying the filter would
hide every anomaly on a fresh difficulty switch (e.g. moving to Hard on
a map you've only played on Normal). During warmup the grid behaves as
if the filter is disabled: every anomaly is visible and nothing is
muted, regardless of the Show All toggle. The threshold is heuristic;
it just buys enough shifts that a confirmed-zero starts to mean
something.

**"Show all candidates" toggle** (top-bar checkbox, persisted across
launches): overrides the hide rule once warmup is met. Hidden anomalies
come back as muted-grey + italic rows, readable as reference-only. The
user can still click them if the game surprises them with one — and
that single sighting moves the anomaly back into the visible bucket
permanently (because `here` becomes ≥ 1).

**Self-correcting:** no JSON schema changes, no manual per-map
declarations of which anomalies belong where. The filter reads CSV
sighting history for the current shift only and adapts as the user
plays.

**What this is NOT:**
- Not the live exclusion predictor — that's "Anomalies Likely Excluded"
  in the lower pane, driven by what you've logged *in the current shift*,
  not by historical sightings.
- Not the Anomalies Seen audit tab — that's deliberately cross-difficulty
  completion tracking; this filter is about what's loggable on the
  current shift specifically.

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

**Three visual tiers:**
- **Light grey + italic** — never seen on any difficulty. The most muted tier;
  reads as "no data yet, still outstanding everywhere." Default sort brings
  these to the top.
- **Mid grey (regular)** — seen on another difficulty but not the currently
  selected one. Ambiguous by design: the anomaly is either genuinely missing
  from your current-mode sightings *or* is exclusive to the other difficulty
  and will never appear here (the tracker can't distinguish those two without
  a schema hint — see the "Difficulty-Exclusive Anomalies" note in the README).
- **Normal black** — seen on the currently selected difficulty. "Done" on this
  mode.

The italic-vs-regular split keeps the two muted tiers clearly distinguishable
even on displays where small greyscale differences wash out.

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

## Open Questions / Modeling Gaps

Unresolved questions about how the anomaly data model should evolve. Parked
here so they don't get lost between sessions. Items marked **???** need
in-game verification.

### Steam / Smoke / Fog availability per map
The newly-promoted global "Steam / Smoke / Fog" has only one logged
sighting so far (Research Station Exterior, session 36).

**Confirmed:** Lighthouse offers the RMB → "Steam / Smoke / Fog" report
option in-game. So SSF as a global is genuinely available on Lighthouse,
not just Research Station — the per-shift filter will discover this
empirically once Lighthouse accumulates RMB-SSF sightings under the
global UUID.

Still open:
- Is Steam / Smoke / Fog room-locked at Research Station (Exterior
  only? other rooms too?) or genuinely random across rooms like Abyss
  and Rift? **???**

Each map's grid will surface or hide SSF based purely on that map's own
sighting history once enough shifts are played there — no cross-map
dependency.

### Room-based Fog vs global Steam / Smoke / Fog
Two coexisting representations of fog/steam/smoke in the data:
- Per-room entries: name "Fog", type "Steam/Smoke/Fog", own UUIDs.
  Currently in Lighthouse Cabin (`29f6b9f6...`) and Lighthouse Pier
  (`3a1e0663...`, 6 sightings).
- Top-level Global: "Steam / Smoke / Fog" (`4712056f...`, 1 sighting in
  Research Station Exterior).

Now that Lighthouse is confirmed to expose the RMB → "Steam / Smoke /
Fog" option, both reporting paths plausibly fire on the same Pier fog
instance: the user can either Hold-LMB the fog object (which has been
the de-facto path for the 6 logged Pier sightings) or RMB → global SSF.
Strongly suggests these are the same in-game event, just two ways to
report it — duplicate counts in our data.

Still open:
- Confirm directly: does the same Pier fog occurrence accept BOTH
  Hold-LMB on the object AND RMB → "Steam / Smoke / Fog"? **???**
  (Currently inferred from "Lighthouse offers RMB SSF" but not
  observed back-to-back on a single fog instance.)
- Can Research Station Exterior Fog (now global) *also* be reported
  via Hold LMB on the fog object? **???**

If both methods work on the same fog instance, the room-based and
global entries should be linked so clicking either counts as the
other — probably a `linked_ids` / `aliases` field on the anomaly
entry, with the analyzer folding them at load time. The current split
otherwise inflates the sighting count whenever the user picks one
report path over the other on different shifts. If only one method
works per location, the split is correct as-is.
