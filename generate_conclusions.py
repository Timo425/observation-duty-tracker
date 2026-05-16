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

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")


# ---------------------------------------------------------------------------
# Image discovery


def _normalize(s):
    """Lowercase + strip non-alphanumerics so 'Keeper’s Cabin' matches 'Keepers Cabin'."""
    return re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower())


def _trailing_number(desc):
    """Trailing integer in the description half of a filename, else 0.
    Used to order `Foo`, `Foo 1`, `Foo 2`… in the user-intuitive sequence.
    Tolerates trailing parentheticals ('Foo 2 (Intruder)' → 2) so adding a
    qualifier after the number doesn't break sort order."""
    s = (desc or "").strip()
    # Peel off trailing " (...)" groups so the number-before-paren reaches $.
    while True:
        new_s = re.sub(r"\s*\([^)]*\)\s*$", "", s).strip()
        if new_s == s: break
        s = new_s
    m = re.search(r"(\d+)$", s)
    return int(m.group(1)) if m else 0


def _index_images(images_dir, map_name):
    """List images under <images_dir>/<map_name>/, parsed as (room_part, desc_part, abs_path)."""
    if not images_dir: return []
    map_dir = os.path.join(images_dir, map_name)
    if not os.path.isdir(map_dir): return []
    out = []
    for fname in sorted(os.listdir(map_dir)):
        if not fname.lower().endswith(IMAGE_EXTS): continue
        stem = os.path.splitext(fname)[0]
        if " - " in stem:
            room_part, desc_part = stem.split(" - ", 1)
        else:
            room_part, desc_part = "", stem
        out.append((room_part, desc_part, os.path.join(map_dir, fname)))
    return out


def _name_match_parts(name):
    """Split an anomaly name into (base, discriminators).
    'Sockets (door)' → ('sockets', ['door']);  'Dead body' → ('dead body', []).
    The discriminator must also appear in the filename for the match to count
    — otherwise 'Sockets (glass)' and 'Sockets (door)' both share the same
    base and would steal each other's images."""
    base = _normalize(re.sub(r"\([^)]*\)", "", name)).strip()
    discs = [_normalize(d).strip() for d in re.findall(r"\(([^)]+)\)", name)]
    return base, [d for d in discs if d]


def _desc_matches(name, file_desc):
    """True iff the file's description half matches the anomaly name —
    base name as substring, plus every parenthetical discriminator from the
    name also present in the file's description."""
    base, discs = _name_match_parts(name)
    if not base: return False
    n_desc = _normalize(file_desc)
    if base not in n_desc: return False
    return all(d in n_desc for d in discs)


def _find_images_for_room_anomaly(name, room_name, indexed):
    """Match files where (a) filename's room half loosely matches the JSON
    room and (b) the anomaly name (incl. paren discriminators) matches the
    description half. Returns abs paths sorted by trailing-number first."""
    n_room = _normalize(room_name).strip()
    matches = []
    for file_room, file_desc, path in indexed:
        nfr = _normalize(file_room).strip()
        room_hit = bool(n_room) and (n_room in nfr or nfr in n_room)
        if not room_hit: continue
        if _desc_matches(name, file_desc):
            matches.append((file_desc, path))
    matches.sort(key=lambda t: (_trailing_number(t[0]), t[1]))
    return [p for _, p in matches]


def _find_images_for_global_in_map(name, indexed):
    """Per-map global lookup: match by anomaly name only, ignoring the
    filename's room half (a global can be photographed in any room of the
    map). `indexed` is this map's index from _index_images."""
    matches = []
    for _file_room, file_desc, path in indexed:
        if _desc_matches(name, file_desc):
            matches.append((file_desc, path))
    matches.sort(key=lambda t: (_trailing_number(t[0]), t[1]))
    return [p for _, p in matches]


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

    Per ANALYSIS.md: 'Global' anomalies aren't tied to a room but DO manifest
    on specific maps and each map's grid is judged purely on that map's own
    sighting history. So globals are folded into each map block as the last
    'room' (named 'Global'), using that map's totals and image folder."""
    if difficulties is None:
        difficulties = backend.data.get("Difficulties", ["Normal", "Hard"])

    excl_by_diff = _build_exclusion_lookup(backend, difficulties)
    map_names = list(backend.data.get("Maps", {}).keys())

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

        rooms = []
        for room_name, anoms in backend.data["Maps"][map_name]["Rooms"].items():
            cards = []
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
            _sort_cards(cards)
            rooms.append({"name": room_name, "cards": cards, "is_global": False})

        # Globals as a synthetic "room" at the end of each map.
        global_cards = []
        for a in backend.data.get("Global", []):
            name = a["name"]
            counts = {d: len(diff_stats[d]["anomaly_sessions"].get(name, set())) for d in difficulties}
            images = _find_images_for_global_in_map(name, indexed)
            global_cards.append(_card(
                name=name,
                atype=a.get("type") or "Global",
                image_status=(a.get("image") or "").lower(),
                counts=counts,
                totals=totals,
                excl_by_diff=excl_by_diff,
                images=images,
            ))
        if global_cards:
            _sort_cards(global_cards)
            rooms.append({"name": "Global", "cards": global_cards, "is_global": True})

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


def render_md(data, _images_dir=None, title=None):
    diffs = data["difficulties"]
    lines = [f"# {title or data['game_id']}", ""]
    lines.append("Bucket key: **N** = Normal-only · **N+H** = both · **H** = Hard-only · **—** = never seen on this map.")
    lines.append("")

    for block in data["maps"]:
        total_str = " · ".join(f"{d}: {block['totals'][d]} shifts" for d in diffs)
        lines.append(f"## {block['name']}")
        lines.append(f"_{total_str}_")
        lines.append("")

        # Header: Room | Type | Anomaly | Bucket | <each diff> | Excl
        header_cells = ["Room", "Type", "Anomaly", "Bucket"]
        for d in diffs:
            header_cells.append(d)
        header_cells.append("Excl")
        lines.append("| " + " | ".join(header_cells) + " |")
        lines.append("|" + "|".join(["---"] * len(header_cells)) + "|")

        for room in block["rooms"]:
            room_label = room["name"]
            for c in room["cards"]:
                cells = [
                    room_label,
                    c["type"] or "—",
                    c["name"],
                    _BUCKET_SHORT[c["bucket"]],
                ]
                for d in diffs:
                    cells.append(_md_rate_cell(c["counts"].get(d, 0), c["totals"].get(d, 0)))
                cells.append(_md_excl_cell(c["excl"]))
                lines.append("| " + " | ".join(cells) + " |")
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
            label = "Global anomalies" if room.get("is_global") else room["name"]
            body.append(f"<h2>{_esc(label)}</h2>")
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
    parser.add_argument("--format", choices=("md", "html", "both"), default="both",
                        help="Output format. 'md' = committed markdown only, "
                             "'html' = local self-contained HTML only, 'both' = both (default).")
    parser.add_argument("--md-output", default=None,
                        help="Markdown output path. Default: conclusions_<game>.md in the repo.")
    parser.add_argument("--html-output", default=None,
                        help="HTML output path. Default: <parent-of-images-dir>/conclusions_<game>.html "
                             "so the HTML lands next to your screenshots in Obsidian. Falls back to "
                             "./conclusions_<game>.html if --images-dir is not set.")
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

    if args.format in ("md", "both"):
        md_path = _resolve(args.md_output)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_text)
        print(f"Markdown written to {md_path}")

    if args.format in ("html", "both"):
        html_path = _resolve(args.html_output)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(render_html(data, args.images_dir, title=args.title))
        print(f"HTML written to {html_path}")


if __name__ == "__main__":
    main()
