"""
Generates statistical conclusions from local session logs.

Output is per-game so each game gets its own file:
  - conclusions_<game>.md   — markdown text, committed to git, tracks
                              long-term occurrence stats. Card layout
                              with anomalies grouped by room and by
                              difficulty bucket.
  - conclusions_<game>.html — same content, self-contained dark-themed
                              HTML, written into the game's Obsidian
                              folder. Uses RELATIVE image paths
                              (`screenshots/<Map>/<file>`) so it renders
                              correctly when opened in the browser or in
                              Obsidian and stays small (no base64).

Layout (per map, plus a top-level Global section):
  # Map
  ## Room
    Anomaly cards ordered by bucket:
      Normal-only → Normal+Hard → Hard-only → Never seen
    Within each bucket: sorted by combined occurrence % (descending).
    Each card:
      Type: Name — Bucket — Normal X/T (Y%) · Hard X/T (Y%) — Excl…
      <image(s)>  or  [image missing]  or  [no image — N/A]
    Multiple images per anomaly are ordered by the trailing number in
    the filename's description half (`Foo`, `Foo 1`, `Foo 2`, …).

JSON convention: an anomaly entry with `"image": "n/a"` is rendered with
[no image — N/A] (e.g. Camera Malfunction — no in-game visual to
photograph). Anything else without a matched image becomes
[image missing].

Run: python3 generate_conclusions.py [--game game_8] [--images-dir DIR]
     --format md|html|both   default: both
     --stdout                print markdown to stdout, write nothing
"""
import sys
import os
import re
import html as html_lib
import argparse
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backend import Backend
from image_matcher import (
    index_images as _index_images,
    find_images_for_room_anomaly as _find_images_for_room_anomaly,
    find_images_for_global_in_map as _find_images_for_global_in_map,
)


def _to_relative_src(abs_path, images_dir):
    """Express abs_path relative to the parent of images_dir.
    Both the HTML and the markdown end up in that parent dir (the game's
    Obsidian folder), so a relative `screenshots/<Map>/<file>` src works
    in browsers and in Obsidian alike."""
    if not abs_path or not images_dir: return abs_path
    parent = os.path.dirname(os.path.abspath(images_dir))
    try:
        return os.path.relpath(abs_path, parent)
    except ValueError:
        return abs_path


# ---------------------------------------------------------------------------
# Exclusivity lookup — confirmed groups only, per difficulty.


def _build_exclusion_lookup(backend, difficulties):
    """Returns {difficulty: {anomaly_name: [other confirmed-group members]}}."""
    out = {}
    for d in difficulties:
        backend.difficulty = d
        results = backend.analyze_exclusivity()
        d_map = {}
        for g in results.get("groups", []):
            if "CONFIRMED" not in g.get("status", ""): continue
            names = [m["name"] for m in g["members"]]
            for name in names:
                d_map[name] = [n for n in names if n != name]
        out[d] = d_map
    return out


# ---------------------------------------------------------------------------
# Report data assembly — pure data, no rendering.


_BUCKET_ORDER = {"Normal-only": 0, "Normal+Hard": 1, "Hard-only": 2, "Never seen": 3}


def _bucket_for(counts):
    """Decide which difficulty bucket an anomaly belongs to based on sightings."""
    n = counts.get("Normal", 0) > 0
    h = counts.get("Hard", 0) > 0
    if n and h: return "Normal+Hard"
    if n: return "Normal-only"
    if h: return "Hard-only"
    return "Never seen"


def _type_str(value):
    """The JSON `type` field can be a string OR a list of tags. Normalize to a
    short display string ('Object Movement / Light Anomaly' etc.)."""
    if not value: return ""
    if isinstance(value, list):
        return " / ".join(str(t).strip() for t in value if t)
    if isinstance(value, str):
        return " / ".join(t.strip() for t in value.split(",") if t.strip())
    return str(value)


def _card(name, atype, image_status, counts, totals, excl_by_diff, images):
    """Assemble the per-anomaly dict used by both renderers."""
    bucket = _bucket_for(counts)
    combined_n = sum(counts.values())
    combined_t = sum(totals.values())
    combined_pct = (combined_n / combined_t) if combined_t else 0.0
    excl = {d: excl_by_diff.get(d, {}).get(name) for d in totals}
    excl = {d: v for d, v in excl.items() if v}
    return {
        "name": name,
        "type": _type_str(atype),
        "image_status": image_status,        # "n/a" if JSON marks it so, else ""
        "counts": dict(counts),
        "totals": dict(totals),
        "bucket": bucket,
        "bucket_idx": _BUCKET_ORDER[bucket],
        "combined_pct": combined_pct,
        "excl": excl,                         # {difficulty: [other members]}
        "images": list(images),               # list of abs paths
    }


def _sort_cards(cards):
    """Bucket-first, occurrence-desc within bucket, then name as tiebreak."""
    cards.sort(key=lambda c: (c["bucket_idx"], -c["combined_pct"], c["name"]))


def build_report_data(backend, difficulties=None, images_dir=None):
    """Returns a structured dict ready for either MD or HTML rendering.

    Per ANALYSIS.md ("What Global means" — read it): globals are NOT
    treated as a separate room or bucket. Every sighting is in a specific
    room (CSV's Room column); globals are listed under the actual rooms
    they've been sighted in, with that room's per-room sighting count.
    Cards from globals are indistinguishable from cards from per-room
    JSON entries at the render layer — both flow through the same
    {name, type, counts, ...} card dict."""
    if difficulties is None:
        difficulties = backend.data.get("Difficulties", ["Normal", "Hard"])

    excl_by_diff = _build_exclusion_lookup(backend, difficulties)
    map_names = list(backend.data.get("Maps", {}).keys())
    global_lookup = {a["name"]: a for a in backend.data.get("Global", [])}

    map_blocks = []
    for map_name in map_names:
        totals = {d: len(backend.get_map_shifts(map_name, difficulty=d)) for d in difficulties}
        if not any(totals.values()):
            continue

        diff_stats = {}
        for d in difficulties:
            backend.difficulty = d
            diff_stats[d] = backend.get_stats(map_name)

        indexed = _index_images(images_dir, map_name) if images_dir else []

        # Walk the main CSV ourselves to bucket global sightings per
        # (room, name, difficulty). Steam's "Global" is data-model
        # shorthand for "definition shared across maps", not "roomless"
        # — each sighting still has a Room and we use it.
        global_sightings = defaultdict(lambda: {d: set() for d in difficulties})
        for row in backend._get_csv_data(backend.logs_path):
            if row.get("Map") != map_name: continue
            d = row.get("Difficulty")
            if d not in difficulties: continue
            name = row.get("Anomaly_Name")
            if name not in global_lookup: continue
            try: s_id = int(row.get("Session_ID"))
            except (TypeError, ValueError): continue
            global_sightings[(row.get("Room"), name)][d].add(s_id)

        rooms = []
        for room_name, anoms in backend.data["Maps"][map_name]["Rooms"].items():
            cards = []

            # Per-room JSON anomalies.
            for a in anoms:
                name = a["name"]
                counts = {d: len(diff_stats[d]["anomaly_sessions"].get(name, set())) for d in difficulties}
                images = _find_images_for_room_anomaly(name, room_name, indexed)
                cards.append(_card(
                    name=name,
                    atype=a.get("type"),
                    image_status=(a.get("image") or "").lower(),
                    counts=counts,
                    totals=totals,
                    excl_by_diff=excl_by_diff,
                    images=images,
                ))

            # Globals that have been sighted in THIS specific room on
            # THIS map. Each card's counts reflect this room's
            # per-sighting numbers, not the map-wide total.
            for (sight_room, gname), diff_sessions in global_sightings.items():
                if sight_room != room_name: continue
                g = global_lookup.get(gname)
                if not g: continue
                counts = {d: len(diff_sessions[d]) for d in difficulties}
                # Image match still uses the global helper (no room
                # filter), since the user may file the screenshot
                # without a room prefix or under any room.
                images = _find_images_for_global_in_map(gname, indexed)
                cards.append(_card(
                    name=gname,
                    atype=g.get("type") or "Global",
                    image_status=(g.get("image") or "").lower(),
                    counts=counts,
                    totals=totals,
                    excl_by_diff=excl_by_diff,
                    images=images,
                ))

            _sort_cards(cards)
            rooms.append({"name": room_name, "cards": cards})

        map_blocks.append({"name": map_name, "totals": totals, "rooms": rooms})

    return {
        "game_id": backend.game_id,
        "difficulties": list(difficulties),
        "maps": map_blocks,
    }


# ---------------------------------------------------------------------------
# Card text helpers (shared by MD and HTML renderers).


def _rate_text(counts, totals, difficulties):
    """e.g. 'Normal: 8/13 (61%) · Hard: 14/18 (77%)'"""
    parts = []
    for d in difficulties:
        n = counts.get(d, 0)
        t = totals.get(d, 0)
        if t == 0:
            parts.append(f"{d}: —")
        elif n == 0:
            parts.append(f"{d}: 0/{t}")
        else:
            parts.append(f"{d}: {n}/{t} ({100 * n // t}%)")
    return " · ".join(parts)


def _excl_text(excl):
    """Returns list of strings like 'Excl (Hard): A, B, C', one per difficulty."""
    return [f"Excl ({d}): {', '.join(members)}" for d, members in excl.items()]


def _meta_segments(card, difficulties):
    """Common per-anomaly metadata, returned as list[str] so both renderers
    can join with their preferred separator."""
    head = f"**{card['type']}:** {card['name']}" if card['type'] else f"**{card['name']}**"
    return [head, card['bucket'], _rate_text(card['counts'], card['totals'], difficulties)] + _excl_text(card['excl'])


# ---------------------------------------------------------------------------
# Markdown renderer — compact reference table per map. No images, no card
# layout (that's what the HTML is for). Tracked in git, diffable.


_BUCKET_SHORT = {
    "Normal-only": "N",
    "Normal+Hard": "N+H",
    "Hard-only": "H",
    "Never seen": "—",
}


def _md_rate_cell(n, t):
    if t == 0: return "—"
    if n == 0: return f"0/{t}"
    return f"{n}/{t} ({100 * n // t}%)"


def _md_excl_cell(excl):
    """Compact representation: 'N: A,B · H: C,D' or '—' if none."""
    if not excl: return "—"
    parts = []
    for d, members in excl.items():
        diff_short = d[0]  # 'N' / 'H'
        parts.append(f"{diff_short}: {', '.join(members)}")
    return " · ".join(parts)


_BUCKET_KEY_LINE = "Bucket key: **N** = Normal-only · **N+H** = both · **H** = Hard-only · **—** = never seen on this map."


def _safe_cell(text):
    r"""Sanitize a cell value so it survives both Markdown table parsing and
    Steam's BBCode renderer. Specifically:
    - bare `"` → curly `“ ”` (Steam mishandles literal double quotes inside
      [td]content[/td] — its parser can treat them as attribute delimiters
      and cascade-corrupt subsequent rows)
    - `|` → `\|` so markdown's table parser doesn't see a cell break
    - leading/trailing whitespace stripped."""
    if text is None: return ""
    s = str(text).strip()
    # Replace pairs of double quotes with typographic open/close, then any leftover singletons with the open quote.
    out = []
    open_q = True
    for ch in s:
        if ch == '"':
            out.append("“" if open_q else "”")  # “ or ”
            open_q = not open_q
        elif ch == "|":
            out.append(r"\|")
        else:
            out.append(ch)
    return "".join(out)


def _md_map_section(block, diffs, heading_level=2):
    """Render one map's data as a Markdown chunk: heading + shifts subtitle +
    table covering all rooms. Used by the all-in-one MD renderer (diffable
    compact text in the repo)."""
    h = "#" * heading_level
    total_str = " · ".join(f"{d}: {block['totals'][d]} shifts" for d in diffs)
    lines = [f"{h} {block['name']}", f"_{total_str}_", ""]

    # Header: Room | Type | Anomaly | Bucket | <each diff> | Excl
    header_cells = ["Room", "Type", "Anomaly", "Bucket"] + list(diffs) + ["Excl"]
    lines.append("| " + " | ".join(header_cells) + " |")
    lines.append("|" + "|".join(["---"] * len(header_cells)) + "|")

    for room in block["rooms"]:
        for c in room["cards"]:
            cells = [
                _safe_cell(room["name"]),
                _safe_cell(c["type"] or "—"),
                _safe_cell(c["name"]),
                _safe_cell(_BUCKET_SHORT[c["bucket"]]),
            ]
            for d in diffs:
                cells.append(_safe_cell(_md_rate_cell(c["counts"].get(d, 0), c["totals"].get(d, 0))))
            cells.append(_safe_cell(_md_excl_cell(c["excl"])))
            lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _bbcode_room_section(block, room, diffs, image_urls=None):
    """Render one (map, room) tuple directly as Steam BBCode. Each anomaly
    is a one-line card with its stats followed by its image(s) on the
    next line — keeps the screenshot visually tied to the data.

    Emitted as raw BBCode rather than via markdown→steam-editor-tools
    because the library silently drops markdown image syntax (`![](url)`
    becomes nothing) and mangles literal `[img]` tags. The room layout is
    simple enough that direct emission is cleaner than fighting the
    converter."""
    map_total = " · ".join(f"{d}: {block['totals'][d]} shifts" for d in diffs)
    lines = [f"[i]Map totals: {map_total}[/i]", ""]

    for c in room["cards"]:
        type_str = c["type"] or "—"
        name = c["name"]
        bucket = c["bucket"]
        rates = " · ".join(
            f"{d}: {_md_rate_cell(c['counts'].get(d, 0), c['totals'].get(d, 0))}"
            for d in diffs
        )
        # Card structure: title (h3) → meta line → blank → image(s) →
        # blank → blank (extra breathing room before the next card).
        lines.append(f"[h3]{type_str}: {name}[/h3]")
        meta_parts = [bucket, rates]
        if c["excl"]:
            for d, members in c["excl"].items():
                meta_parts.append(f"Excl ({d}): {', '.join(members)}")
        lines.append(" — ".join(meta_parts))
        lines.append("")

        # Image(s) on their own lines (one per line — Steam stacks them
        # vertically at sizeFull anyway, but explicit line breaks make
        # the source readable). Steam guide BBCode uses [previewimg=
        # PREVIEWID;size,layout;filename][/previewimg] referencing the
        # upload by preview id; source: Steam's own InsertSelected() JS.
        if image_urls and c.get("images"):
            for abs_path in c["images"]:
                fname = os.path.basename(abs_path)
                entry = image_urls.get(fname)
                if not entry: continue
                if isinstance(entry, str): continue  # legacy {filename: url} shape, no previewid
                previewid = entry.get("previewid")
                if not previewid: continue
                lines.append(f"[previewimg={previewid};sizeFull,inline;{fname}][/previewimg]")

        # Extra blank to give visual gap before the next [h3].
        lines.append("")
        lines.append("")
    return "\n".join(lines)


def render_md(data, _images_dir=None, title=None):
    diffs = data["difficulties"]
    lines = [f"# {title or data['game_id']}", "", _BUCKET_KEY_LINE, ""]
    for block in data["maps"]:
        lines.append(_md_map_section(block, diffs, heading_level=2))
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML renderer — emits structured HTML directly (no markdown intermediate).
# Images use relative paths so the file stays small; click to open full size.


_DARK_CSS = """
:root { color-scheme: dark; }
html { background: #1b1d21; }
body {
  margin: 0 auto;
  padding: 2rem 3rem;
  background: #1b1d21;
  color: #d8d8d8;
  font-family: -apple-system, "Segoe UI", system-ui, sans-serif;
  line-height: 1.55;
  font-size: 15px;
  max-width: 1400px;
}
h1, h2, h3 { color: #f3f3f3; margin-top: 1.6em; }
h1 { border-bottom: 1px solid #34373d; padding-bottom: 0.25em; }
h2 { border-bottom: 1px solid #2a2c31; padding-bottom: 0.2em; }
em.subtotal { color: #9aa0a6; font-size: 0.92em; }
strong { color: #f3f3f3; }
.anomaly { margin: 0.9em 0 1.2em; padding: 0.3em 0 0.3em 0.9em; border-left: 3px solid #34373d; }
.anomaly .meta { margin: 0 0 0.4em; }
.anomaly .bucket { color: #9aa0a6; }
.anomaly .rates { color: #c9c9c9; }
.anomaly .excl { color: #c9a86a; font-size: 0.92em; display: block; margin-top: 0.1em; }
.anomaly .images { display: flex; flex-wrap: wrap; gap: 8px; }
.anomaly .images a.thumb { display: inline-block; line-height: 0; }
.anomaly .images a.thumb img { max-height: 260px; max-width: 380px; border-radius: 4px; cursor: zoom-in; }
.no-image { color: #8a8e95; font-style: italic; font-size: 0.92em; }
.bucket-normal { border-left-color: #5ea3d8; }
.bucket-both { border-left-color: #8fb96b; }
.bucket-hard { border-left-color: #d87a5e; }
.bucket-never { border-left-color: #555; }

/* CSS-only lightbox via :target. The whole overlay is a single <a href="#">
   so clicking anywhere — including the dimmed backdrop — closes it. The X
   in the corner is a visual cue, not its own button. */
a.lightbox {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.94);
  z-index: 1000;
  align-items: center;
  justify-content: center;
  cursor: zoom-out;
  text-decoration: none;
}
a.lightbox:target { display: flex; }
a.lightbox img {
  max-width: 96vw;
  max-height: 92vh;
  object-fit: contain;
  border-radius: 4px;
}
a.lightbox .close {
  position: absolute;
  top: 1rem;
  right: 1.5rem;
  width: 2.4rem;
  height: 2.4rem;
  border-radius: 50%;
  background: rgba(40, 40, 40, 0.65);
  color: #f3f3f3;
  font-size: 1.6rem;
  line-height: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;  /* override the parent's zoom-out cursor over the X */
}
a.lightbox:hover .close { background: rgba(70, 70, 70, 0.85); }
.anomaly .images a.thumb { scroll-margin-top: 4rem; }
"""

_BUCKET_CLASS = {
    "Normal-only": "bucket-normal",
    "Normal+Hard": "bucket-both",
    "Hard-only": "bucket-hard",
    "Never seen": "bucket-never",
}


def _esc(s):
    return html_lib.escape(s or "")


def _html_card(card, difficulties, images_dir, card_idx):
    cls = _BUCKET_CLASS.get(card["bucket"], "")
    bucket = _esc(card["bucket"])
    name = _esc(card["name"])
    atype = _esc(card["type"])
    head = f"<strong>{atype}:</strong> {name}" if atype else f"<strong>{name}</strong>"
    rates = _esc(_rate_text(card["counts"], card["totals"], difficulties))

    parts = [
        f'<div class="anomaly {cls}">',
        f'<div class="meta">{head} — <span class="bucket">{bucket}</span> — <span class="rates">{rates}</span>',
    ]
    for line in _excl_text(card["excl"]):
        parts.append(f'<span class="excl">{_esc(line)}</span>')
    parts.append("</div>")

    if card["image_status"] == "n/a":
        parts.append('<div class="no-image">[no image — N/A]</div>')
    elif card["images"]:
        parts.append('<div class="images">')
        # Each image gets a thumbnail link + lightbox overlay pair. Clicking
        # the thumb sets the URL fragment to the overlay's id, the :target
        # CSS rule reveals it. The overlay is itself an <a href="#"> so a
        # click anywhere on it (including the backdrop and the X) clears
        # the fragment and hides everything.
        for img_idx, abs_path in enumerate(card["images"]):
            rel = _esc(_to_relative_src(abs_path, images_dir))
            lb_id = f"lb-{card_idx}-{img_idx}"
            thumb_id = f"thumb-{card_idx}-{img_idx}"
            # The thumb carries an id so the lightbox's close href can target
            # it; clicking 'close' navigates the URL fragment back to the
            # thumb's position instead of scrolling to top.
            parts.append(
                f'<a id="{thumb_id}" href="#{lb_id}" class="thumb">'
                f'<img src="{rel}" alt="{name}" loading="lazy"/></a>'
                f'<a id="{lb_id}" href="#{thumb_id}" class="lightbox" aria-label="Close">'
                f'<span class="close">×</span>'
                f'<img src="{rel}" alt="{name}"/></a>'
            )
        parts.append("</div>")
    else:
        parts.append('<div class="no-image">[image missing]</div>')

    parts.append("</div>")
    return "\n".join(parts)


def render_html(data, images_dir, title=None):
    diffs = data["difficulties"]
    display_title = title or data["game_id"]
    body = [f"<h1>{_esc(display_title)}</h1>"]

    card_idx = 0
    for block in data["maps"]:
        total_str = " · ".join(f"{d}: {block['totals'][d]} shifts" for d in diffs)
        body.append(f"<h1>{_esc(block['name'])}</h1>")
        body.append(f'<p><em class="subtotal">{_esc(total_str)}</em></p>')
        for room in block["rooms"]:
            body.append(f"<h2>{_esc(room['name'])}</h2>")
            for c in room["cards"]:
                body.append(_html_card(c, diffs, images_dir, card_idx))
                card_idx += 1

    return (
        "<!doctype html>\n"
        f'<html lang="en"><head><meta charset="utf-8">'
        f"<title>{_esc(display_title)}</title>"
        f"<style>{_DARK_CSS}</style></head><body>\n"
        + "\n".join(body)
        + "\n</body></html>\n"
    )


# ---------------------------------------------------------------------------
# Steam BBCode pipeline — one file per guide section. Drives the
# steam-editor-tools library (PyPI), which parses Markdown via markdown-it
# and renders Steam's specific BBCode dialect. Optional dependency: only
# loaded when --format includes 'steam'.


_FS_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _fs_safe(name):
    """Filename-safe rendering of a section name. 'Research Station' →
    'Research_Station'. Keeps the section name readable in the output dir."""
    return _FS_SAFE.sub("_", name).strip("_") or "section"


def _md_to_bbcode(md_text, parser, renderer):
    """Round-trip a Markdown string through steam-editor-tools via a temp
    file (the library's public parser entry point takes a path)."""
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(md_text)
        tmp_path = f.name
    try:
        return renderer.render(parser.parse_file(tmp_path))
    finally:
        try: os.unlink(tmp_path)
        except OSError: pass


def render_steam_sections(data, title, codeberg_url="https://codeberg.org/Comtief/observation-duty-tracker", image_urls=None):
    """Yields (section_name, bbcode_text) pairs — one per Steam guide section.
    First yield is the overview (legend + tool link); then one per (map, room).

    `image_urls`, if provided, is a {filename: {url, previewid}} dict used
    to embed [previewimg=ID;...] per anomaly in each room section."""
    diffs = data["difficulties"]

    # Overview / legend section. Raw BBCode, no markdown detour — keeps
    # the multi-line list intact (Steam collapsed the prose legend to
    # one dense line otherwise).
    overview_bb = (
        f"[h1]{title}[/h1]\n"
        "\n"
        "Each anomaly carries a bucket showing where it's been observed:\n"
        "[list]\n"
        "[*][b]N[/b] — Normal-only\n"
        "[*][b]N+H[/b] — both difficulties\n"
        "[*][b]H[/b] — Hard-only\n"
        "[*][b]—[/b] — never seen on this map yet\n"
        "[/list]\n"
        "\n"
        f"Tracker: {codeberg_url}\n"
    )
    yield ("Overview", overview_bb)

    # One section per (map, room). Per-map sections hit Steam's per-section
    # character cap (~8K chars, truncates mid-tag); per-room sections are
    # 1-3 KB each, well under any cap. Globals appear inline within
    # whichever room they've been sighted in (see ANALYSIS.md — "Global"
    # is a JSON-data-model label, not a separate room or pseudo-section).
    #
    # Room sections are emitted as raw BBCode directly. The markdown
    # detour we use for the Overview can't carry `[img]` through (the
    # steam-editor-tools renderer drops markdown image syntax). Cards
    # are simple lines, easier to emit directly than to fight the
    # converter.
    for block in data["maps"]:
        for room in block["rooms"]:
            section_name = f"{block['name']} - {room['name']}"
            section_bb = _bbcode_room_section(block, room, diffs, image_urls=image_urls)
            yield (section_name, section_bb)


# ---------------------------------------------------------------------------
# Exclusivity report — kept for test compat and as the `generate_report` alias
# the GUI/CLI used historically. Not included in the per-game files anymore
# (group info is now inline on each card).


def generate_exclusivity_report(backend, difficulties=None):
    """Exclusivity findings from Backend.analyze_exclusivity(), as markdown."""
    if difficulties is None:
        difficulties = backend.data.get("Difficulties", ["Normal"])

    lines = ["# Exclusivity analysis", ""]
    lines.append(f"- Game: `{backend.game_id}`")
    lines.append(f"- Log file: `{backend.logs_path}`")
    lines.append("")

    for diff in difficulties:
        backend.difficulty = diff
        results = backend.analyze_exclusivity()
        groups = results.get("groups", [])
        violations = results.get("violations", [])

        lines.append(f"## {diff}")
        lines.append("")

        if not groups and not violations:
            all_sessions = backend.get_all_sessions()
            lines.append(f"- Shifts logged: {len(all_sessions)}")
            lines.append("- Not enough data yet (need at least 3 shifts with 2+ anomalies each).")
            lines.append("")
            continue

        N = groups[0]["N"] if groups else "?"
        lines.append(f"- Total sessions analyzed: {N}")
        lines.append("")

        confirmed = [g for g in groups if "CONFIRMED" in g["status"]]
        likely = [g for g in groups if "LIKELY" in g["status"]]

        if confirmed:
            lines.append("### Confirmed exclusion groups (>95% confidence)")
            for i, g in enumerate(confirmed, 1):
                members = sorted(g["members"], key=lambda m: m["sightings"], reverse=True)
                member_strs = [f"{m['name']} ({m['sightings']}/{N})" for m in members]
                lines.append(f"{i}. {', '.join(member_strs)}")
            lines.append("")

        if likely:
            lines.append("### Likely exclusion groups (needs more data)")
            for i, g in enumerate(likely, 1):
                members = sorted(g["members"], key=lambda m: m["sightings"], reverse=True)
                member_strs = [f"{m['name']} ({m['sightings']}/{N})" for m in members]
                lines.append(f"{i}. {', '.join(member_strs)} — certainty {g['certainty']:.0%}")
            lines.append("")

        if violations:
            lines.append("### Possible group violations")
            for v in violations:
                group_str = ", ".join(v["group_names"])
                shifts_str = ", ".join(f"#{s}" for s in v["conflict_shifts"])
                lines.append(f"- **{v['candidate']}** may belong to group {{{group_str}}}")
                lines.append(f"  - but co-occurs with **{v['conflicts_with']}** in shifts {shifts_str}")
                lines.append(f"  - (expected overlap: {v['expected_overlap']:.1f}, actual: {v['actual_overlap']})")
            lines.append("")

    return "\n".join(lines)


# Backward-compat alias used by tests/test_conclusions.py.
generate_report = generate_exclusivity_report


# ---------------------------------------------------------------------------
# CLI.


def main():
    parser = argparse.ArgumentParser(description="Generate per-game statistical conclusions from session logs")
    parser.add_argument("--game", default="game_8", help="Game ID (default: game_8)")
    parser.add_argument("--format", choices=("md", "html", "both", "steam", "all"), default="both",
                        help="Output format. 'md' = markdown only (committed to repo), "
                             "'html' = local self-contained HTML, 'both' = md + html (default, what cron runs), "
                             "'steam' = per-section Steam BBCode files (requires steam-editor-tools), "
                             "'all' = md + html + steam.")
    parser.add_argument("--md-output", default=None,
                        help="Markdown output path. Default: conclusions_<game>.md in the repo.")
    parser.add_argument("--html-output", default=None,
                        help="HTML output path. Default: <parent-of-images-dir>/conclusions_<game>.html "
                             "so the HTML lands next to your screenshots in Obsidian. Falls back to "
                             "./conclusions_<game>.html if --images-dir is not set.")
    parser.add_argument("--steam-output-dir", default=None,
                        help="Directory for per-section Steam BBCode files (one file per guide section). "
                             "Default: <parent-of-images-dir>/steam-guide-<game>/ next to Obsidian, "
                             "or ./steam-guide-<game>/ if --images-dir is not set.")
    parser.add_argument("--image-urls", default=None,
                        help="Path to a {local_filename: steam_url} JSON produced by the Steam "
                             "guide playwright sync. When provided, each room section's BBCode "
                             "includes a screenshots block with [img]URL[/img] per matched anomaly. "
                             "Default: <parent-of-images-dir>/image_urls.json if it exists.")
    parser.add_argument("--stdout", action="store_true",
                        help="Print markdown to stdout and skip writing files.")
    parser.add_argument("--images-dir", default=os.environ.get("OBSDUTY_IMAGES_DIR"),
                        help="Directory containing <Map>/<Room> - <Desc>.jpg screenshots. "
                             "Also read from OBSDUTY_IMAGES_DIR env var. Path stays out of the repo on purpose.")
    parser.add_argument("--title", default=None,
                        help="Friendly title for the H1 and HTML <title>. "
                             "Default: derived from --images-dir's parent dir name (e.g. "
                             "'Im on Observation Duty 8') so the heading reads as the game's "
                             "name, not its internal ID. Falls back to the game id.")
    args = parser.parse_args()

    if args.md_output is None:
        args.md_output = f"conclusions_{args.game}.md"
    if args.html_output is None:
        if args.images_dir:
            args.html_output = os.path.join(
                os.path.dirname(os.path.abspath(args.images_dir)),
                f"conclusions_{args.game}.html",
            )
        else:
            args.html_output = f"conclusions_{args.game}.html"
    if args.steam_output_dir is None:
        if args.images_dir:
            args.steam_output_dir = os.path.join(
                os.path.dirname(os.path.abspath(args.images_dir)),
                f"steam-guide-{args.game}",
            )
        else:
            args.steam_output_dir = f"steam-guide-{args.game}"

    if args.title is None:
        if args.images_dir:
            args.title = os.path.basename(os.path.dirname(os.path.abspath(args.images_dir)))
        else:
            args.title = args.game

    base_dir = os.path.dirname(os.path.abspath(__file__))
    backend = Backend(base_dir)
    backend.set_game(args.game)

    data = build_report_data(backend, images_dir=args.images_dir)
    md_text = render_md(data, args.images_dir, title=args.title)

    if args.stdout:
        print(md_text)
        return

    def _resolve(p):
        return p if os.path.isabs(p) else os.path.join(base_dir, p)

    if args.format in ("md", "both", "all"):
        md_path = _resolve(args.md_output)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_text)
        print(f"Markdown written to {md_path}")

    if args.format in ("html", "both", "all"):
        html_path = _resolve(args.html_output)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(render_html(data, args.images_dir, title=args.title))
        print(f"HTML written to {html_path}")

    if args.format in ("steam", "all"):
        steam_dir = _resolve(args.steam_output_dir)
        os.makedirs(steam_dir, exist_ok=True)
        # Wipe stale .bbcode files before writing — otherwise sections
        # that no longer exist in the current report (e.g. an old "Global
        # anomalies" pseudo-section) would linger and trick the
        # downstream sync into reapplying them.
        for stale in os.listdir(steam_dir):
            if stale.endswith(".bbcode"):
                os.unlink(os.path.join(steam_dir, stale))
        # Resolve image-urls JSON: explicit flag → default next to images dir → none.
        image_urls = None
        urls_path = args.image_urls
        if urls_path is None and args.images_dir:
            candidate = os.path.join(os.path.dirname(os.path.abspath(args.images_dir)), "image_urls.json")
            if os.path.exists(candidate):
                urls_path = candidate
        if urls_path and os.path.exists(urls_path):
            import json as _json
            with open(urls_path, "r", encoding="utf-8") as f:
                image_urls = _json.load(f)
            print(f"Using image URLs from {urls_path} ({len(image_urls)} entries)")
        # Emit a manifest listing section names in the desired order
        # (Overview first, then maps in JSON / game order, rooms in JSON
        # order, Globals last per map). Sync tooling reads this to create
        # Steam guide sections in the correct order — Steam preserves
        # creation order in the sidebar nav.
        section_manifest = []
        for section_name, bbcode in render_steam_sections(data, args.title, image_urls=image_urls):
            path = os.path.join(steam_dir, f"{_fs_safe(section_name)}.bbcode")
            with open(path, "w", encoding="utf-8") as f:
                f.write(bbcode)
            section_manifest.append(section_name)
            print(f"Steam BBCode section '{section_name}' written to {path}")
        import json as _json
        manifest_path = os.path.join(steam_dir, "_sections.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            _json.dump(section_manifest, f, indent=2)
        print(f"Section order manifest written to {manifest_path}")


if __name__ == "__main__":
    main()
