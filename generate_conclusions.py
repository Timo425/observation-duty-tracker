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
    Used to order `Foo`, `Foo 1`, `Foo 2`… in the user-intuitive sequence."""
    m = re.search(r"\s+(\d+)\s*$", (desc or "").strip())
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


def _index_all_images(images_dir, map_names):
    """Like _index_images, but pre-tagged with the map name. Used for Globals
    which can have screenshots under any map's folder."""
    out = []
    for m in map_names:
        for room_part, desc_part, path in _index_images(images_dir, m):
            out.append((m, room_part, desc_part, path))
    return out


def _find_images_for_room_anomaly(name, room_name, indexed):
    """Match files where (a) filename's room half loosely matches the JSON
    room and (b) the anomaly name appears in the description half.
    Returns abs paths sorted by trailing-number first, then filename."""
    name_simple = re.sub(r"\([^)]*\)", "", name)
    n_name = _normalize(name_simple).strip()
    if not n_name: return []
    n_room = _normalize(room_name).strip()

    matches = []
    for file_room, file_desc, path in indexed:
        nfr = _normalize(file_room).strip()
        room_hit = bool(n_room) and (n_room in nfr or nfr in n_room)
        if not room_hit: continue
        if n_name in _normalize(file_desc):
            matches.append((file_desc, path))
    matches.sort(key=lambda t: (_trailing_number(t[0]), t[1]))
    return [p for _, p in matches]


def _find_images_for_global(name, indexed_all):
    """Globals match anywhere — scan every map's index by name only.
    indexed_all rows are (map, room, desc, abs_path)."""
    name_simple = re.sub(r"\([^)]*\)", "", name)
    n_name = _normalize(name_simple).strip()
    if not n_name: return []
    matches = []
    for _m, _room, file_desc, path in indexed_all:
        if n_name in _normalize(file_desc):
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
    Layout: globals first, then per map → per room → list of card dicts."""
    if difficulties is None:
        difficulties = backend.data.get("Difficulties", ["Normal", "Hard"])

    excl_by_diff = _build_exclusion_lookup(backend, difficulties)
    map_names = list(backend.data.get("Maps", {}).keys())

    # --- Globals: combined across all maps, images can come from anywhere.
    indexed_all = _index_all_images(images_dir, map_names) if images_dir else []
    global_totals = {d: 0 for d in difficulties}
    for m in map_names:
        for d in difficulties:
            global_totals[d] += len(backend.get_map_shifts(m, difficulty=d))

    global_anom_counts = defaultdict(lambda: {d: set() for d in difficulties})
    for m in map_names:
        for d in difficulties:
            backend.difficulty = d
            stats = backend.get_stats(m)
            for a in backend.data.get("Global", []):
                global_anom_counts[a["name"]][d].update(stats["anomaly_sessions"].get(a["name"], set()))

    global_cards = []
    for a in backend.data.get("Global", []):
        name = a["name"]
        counts = {d: len(global_anom_counts[name][d]) for d in difficulties}
        images = _find_images_for_global(name, indexed_all)
        global_cards.append(_card(
            name=name,
            atype=a.get("type") or "Global",
            image_status=(a.get("image") or "").lower(),
            counts=counts,
            totals=global_totals,
            excl_by_diff=excl_by_diff,
            images=images,
        ))
    _sort_cards(global_cards)

    # --- Per-map / per-room cards.
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
            rooms.append({"name": room_name, "cards": cards})
        map_blocks.append({"name": map_name, "totals": totals, "rooms": rooms})

    return {
        "game_id": backend.game_id,
        "difficulties": list(difficulties),
        "global_totals": global_totals,
        "global_cards": global_cards,
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
# Markdown renderer.


def _md_card(card, difficulties, images_dir):
    """One card as Markdown lines."""
    out = []
    meta = " — ".join(_meta_segments(card, difficulties))
    out.append(meta)

    if card["image_status"] == "n/a":
        out.append("*[no image — N/A]*")
    elif card["images"]:
        for abs_path in card["images"]:
            rel = _to_relative_src(abs_path, images_dir)
            out.append(f"![{card['name']}]({rel})")
    else:
        out.append("*[image missing]*")
    out.append("")
    return out


def render_md(data, images_dir):
    lines = [f"# {data['game_id']} — conclusions", ""]

    if data["global_cards"]:
        lines.append("## Global anomalies")
        total_str = " · ".join(f"{d}: {data['global_totals'][d]} shifts" for d in data["difficulties"])
        lines.append(f"_{total_str}_")
        lines.append("")
        for c in data["global_cards"]:
            lines.extend(_md_card(c, data["difficulties"], images_dir))

    for block in data["maps"]:
        total_str = " · ".join(f"{d}: {block['totals'][d]} shifts" for d in data["difficulties"])
        lines.append(f"# {block['name']}")
        lines.append(f"_{total_str}_")
        lines.append("")
        for room in block["rooms"]:
            lines.append(f"## {room['name']}")
            lines.append("")
            for c in room["cards"]:
                lines.extend(_md_card(c, data["difficulties"], images_dir))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML renderer — emits structured HTML directly (no markdown intermediate).
# Images use relative paths so the file stays small; click to open full size.


_DARK_CSS = """
:root { color-scheme: dark; }
body {
  margin: 0;
  padding: 2rem 3rem;
  background: #1b1d21;
  color: #d8d8d8;
  font-family: -apple-system, "Segoe UI", system-ui, sans-serif;
  line-height: 1.55;
  font-size: 15px;
  max-width: 1200px;
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
.anomaly .images a { display: inline-block; line-height: 0; }
.anomaly .images img { max-height: 260px; max-width: 380px; border-radius: 4px; }
.no-image { color: #8a8e95; font-style: italic; font-size: 0.92em; }
.bucket-normal { border-left-color: #5ea3d8; }
.bucket-both { border-left-color: #8fb96b; }
.bucket-hard { border-left-color: #d87a5e; }
.bucket-never { border-left-color: #555; }
"""

_BUCKET_CLASS = {
    "Normal-only": "bucket-normal",
    "Normal+Hard": "bucket-both",
    "Hard-only": "bucket-hard",
    "Never seen": "bucket-never",
}


def _esc(s):
    return html_lib.escape(s or "")


def _html_card(card, difficulties, images_dir):
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
        for abs_path in card["images"]:
            rel = _esc(_to_relative_src(abs_path, images_dir))
            parts.append(
                f'<a href="{rel}" target="_blank" rel="noopener">'
                f'<img src="{rel}" alt="{name}" loading="lazy"/></a>'
            )
        parts.append("</div>")
    else:
        parts.append('<div class="no-image">[image missing]</div>')

    parts.append("</div>")
    return "\n".join(parts)


def render_html(data, images_dir):
    diffs = data["difficulties"]
    body = []
    body.append(f"<h1>{_esc(data['game_id'])} — conclusions</h1>")

    if data["global_cards"]:
        total_str = " · ".join(f"{d}: {data['global_totals'][d]} shifts" for d in diffs)
        body.append("<h2>Global anomalies</h2>")
        body.append(f'<p><em class="subtotal">{_esc(total_str)}</em></p>')
        for c in data["global_cards"]:
            body.append(_html_card(c, diffs, images_dir))

    for block in data["maps"]:
        total_str = " · ".join(f"{d}: {block['totals'][d]} shifts" for d in diffs)
        body.append(f"<h1>{_esc(block['name'])}</h1>")
        body.append(f'<p><em class="subtotal">{_esc(total_str)}</em></p>')
        for room in block["rooms"]:
            body.append(f"<h2>{_esc(room['name'])}</h2>")
            for c in room["cards"]:
                body.append(_html_card(c, diffs, images_dir))

    return (
        "<!doctype html>\n"
        f'<html lang="en"><head><meta charset="utf-8">'
        f"<title>{_esc(data['game_id'])} conclusions</title>"
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

    base_dir = os.path.dirname(os.path.abspath(__file__))
    backend = Backend(base_dir)
    backend.set_game(args.game)

    data = build_report_data(backend, images_dir=args.images_dir)
    md_text = render_md(data, args.images_dir)

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
            f.write(render_html(data, args.images_dir))
        print(f"HTML written to {html_path}")


if __name__ == "__main__":
    main()
