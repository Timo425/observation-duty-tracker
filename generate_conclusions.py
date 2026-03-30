"""
Generates statistical conclusions from local session logs.

Uses the same Backend logic that powers the GUI's live exclusivity analysis.
Run: python3 generate_conclusions.py [--game game_8] [--output conclusions.txt]
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backend import Backend


def generate_report(backend, difficulties=None):
    """Generate a text report of exclusivity findings using Backend's own analysis.

    Returns the report as a string.
    """
    if difficulties is None:
        difficulties = backend.data.get("Difficulties", ["Normal"])

    lines = []
    lines.append(f"=== Exclusivity Analysis Report ===")
    lines.append(f"Game: {backend.game_id}")
    lines.append(f"Log file: {backend.logs_path}")
    lines.append("")

    for diff in difficulties:
        backend.difficulty = diff
        results = backend.analyze_exclusivity()
        groups = results.get("groups", [])
        violations = results.get("violations", [])

        lines.append(f"--- {diff} Mode ---")

        if not groups and not violations:
            all_sessions = backend.get_all_sessions()
            lines.append(f"  Shifts logged: {len(all_sessions)}")
            lines.append(f"  Not enough data yet (need at least 3 shifts with 2+ anomalies each).")
            lines.append("")
            continue

        N = groups[0]["N"] if groups else "?"
        lines.append(f"  Total sessions analyzed: {N}")
        lines.append("")

        confirmed = [g for g in groups if "CONFIRMED" in g["status"]]
        likely = [g for g in groups if "LIKELY" in g["status"]]

        if confirmed:
            lines.append(f"  Confirmed Exclusion Groups (>95% confidence):")
            for i, g in enumerate(confirmed, 1):
                members = sorted(g["members"], key=lambda m: m["sightings"], reverse=True)
                member_strs = [f"{m['name']} ({m['sightings']}/{N})" for m in members]
                lines.append(f"    Group {i}: {', '.join(member_strs)}")
            lines.append("")

        if likely:
            lines.append(f"  Likely Exclusion Groups (needs more data):")
            for i, g in enumerate(likely, 1):
                members = sorted(g["members"], key=lambda m: m["sightings"], reverse=True)
                member_strs = [f"{m['name']} ({m['sightings']}/{N})" for m in members]
                lines.append(f"    Group {i}: {', '.join(member_strs)} — certainty {g['certainty']:.0%}")
            lines.append("")

        violations = results.get("violations", [])
        if violations:
            lines.append(f"  Possible Group Violations:")
            for v in violations:
                group_str = ", ".join(v["group_names"])
                shifts_str = ", ".join(f"#{s}" for s in v["conflict_shifts"])
                lines.append(f"    {v['candidate']} may belong to group {{{group_str}}}")
                lines.append(f"      but co-occurs with {v['conflicts_with']} in shifts {shifts_str}")
                lines.append(f"      (expected overlap: {v['expected_overlap']:.1f}, actual: {v['actual_overlap']})")
            lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate exclusivity conclusions from session logs")
    parser.add_argument("--game", default="game_8", help="Game ID (default: game_8)")
    parser.add_argument("--output", default=None, help="Output file path (default: print to stdout)")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    backend = Backend(base_dir)
    backend.set_game(args.game)

    report = generate_report(backend)

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"Report written to {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
