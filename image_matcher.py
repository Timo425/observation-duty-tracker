"""Match local screenshot files to JSON anomaly entries.

Used by both the GUI (📷 indicator on room buttons) and the conclusions
generator (image embedding in HTML/BBCode). Single source of truth so the
two never drift apart — fixes one place, both improve.

Filename convention: `<images_dir>/<Map>/<Room name> - <Anomaly>.<ext>`
(plus optional trailing `<number>` for ordering multiple shots per anomaly,
e.g. `Pier - Naked man 1.jpg`, `… 2.jpg`).

Matching rules:

1. Loose room match — the filename's room half must contain or be
   contained by the JSON room name (so `Keeper's Cabin` matches JSON
   `Cabin`).
2. Base name match with slash-split — the JSON name's base (parens
   stripped) is split on '/' into alternatives. A file matches if ANY
   alternative appears in the filename's description half. Lets
   'Steam / Smoke / Fog' match a file called just 'fog.jpg' without
   forcing the user to spell out the whole tri-name.
3. Parenthetical discriminators — any `(text)` parts in the JSON name
   must ALL appear in the filename. Stops 'Sockets (door)' and
   'Sockets (glass)' from stealing each other's images.

Globals (per-map flavor): same name-matching rule, no room match
required — a global can be photographed in any room of the map.
"""
import os
import re

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def normalize(s):
    """Lowercase + strip non-alphanumerics so apostrophes / em-dashes /
    case differences don't cause a near-miss. Whitespace is collapsed so
    a stripped colon (e.g. 'Drum: Rear left' → 'drum  rear left') doesn't
    produce a double-space that breaks substring matching against a
    naturally-spaced filename ('Drum rear left' → 'drum rear left')."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower())).strip()


def trailing_number(desc):
    """Trailing integer in the description half of a filename, else 0.
    Tolerates trailing parentheticals: 'Foo 2 (Intruder)' → 2 so adding
    a qualifier after the number doesn't break sort order."""
    s = (desc or "").strip()
    while True:
        new_s = re.sub(r"\s*\([^)]*\)\s*$", "", s).strip()
        if new_s == s: break
        s = new_s
    m = re.search(r"(\d+)$", s)
    return int(m.group(1)) if m else 0


def index_images(images_dir, map_name):
    """List images under <images_dir>/<map_name>/, parsed as
    (room_part, desc_part, abs_path) tuples ready for matching."""
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


def name_match_parts(name):
    """Split an anomaly name into (bases, discriminators).

    bases:        slash-separated alternative substrings (any one of them
                  being present in the file desc is enough).
    discriminators: parenthetical content; ALL must be present in the file
                  desc to count as a match.

    Examples:
      'Steam / Smoke / Fog'   → bases=['steam','smoke','fog'], discs=[]
      'Sockets (door)'        → bases=['sockets'],             discs=['door']
      'Dead body (couch)'     → bases=['dead body'],           discs=['couch']
      'Plain name'            → bases=['plain name'],          discs=[]
    """
    no_parens = re.sub(r"\([^)]*\)", "", name)
    bases = [normalize(p).strip() for p in no_parens.split("/")]
    bases = [b for b in bases if b]
    discs = [normalize(d).strip() for d in re.findall(r"\(([^)]+)\)", name)]
    discs = [d for d in discs if d]
    return bases, discs


def desc_matches(name, file_desc):
    """True iff a file's description half matches the anomaly name per
    the rules above."""
    bases, discs = name_match_parts(name)
    if not bases: return False
    n_desc = normalize(file_desc)
    if not any(b in n_desc for b in bases): return False
    return all(d in n_desc for d in discs)


def find_images_for_room_anomaly(name, room_name, indexed):
    """Per-room match: room halves loosely match AND name matches.
    Returns abs paths sorted by trailing-number first, then filename."""
    n_room = normalize(room_name).strip()
    matches = []
    for file_room, file_desc, path in indexed:
        nfr = normalize(file_room).strip()
        room_hit = bool(n_room) and (n_room in nfr or nfr in n_room)
        if not room_hit: continue
        if desc_matches(name, file_desc):
            matches.append((file_desc, path))
    matches.sort(key=lambda t: (trailing_number(t[0]), t[1]))
    return [p for _, p in matches]


def find_images_for_global_in_map(name, indexed):
    """Per-map global match: name only, any room within the map."""
    matches = []
    for _file_room, file_desc, path in indexed:
        if desc_matches(name, file_desc):
            matches.append((file_desc, path))
    matches.sort(key=lambda t: (trailing_number(t[0]), t[1]))
    return [p for _, p in matches]
