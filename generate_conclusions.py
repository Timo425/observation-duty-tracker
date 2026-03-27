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

        lines.append(f"--- {diff} Mode ---")

        if not results:
            all_sessions = backend.get_all_sessions()
            lines.append(f"  Sessions logged: {len(all_sessions)}")
            lines.append(f"  Not enough data yet (need at least 3 sessions with 2+ anomalies each).")
            lines.append("")
            continue

        # Separate hard locks from potential errors
        hard_locks = [r for r in results if r["status"] == "Hard Lock"]
        likely = [r for r in results if r["status"] == "Likely Excl."]
        errors = [r for r in results if r["status"] == "POTENTIAL ERROR"]

        lines.append(f"  Total sessions analyzed: {results[0]['N'] if results else 0}")
        N = results[0]['N']
        lines.append("")

        # Collect per-anomaly frequency from the exclusivity data
        anom_freq = {}
        for r in results:
            a1, a2 = r["pair"]
            anom_freq[a1] = r["n1"]
            anom_freq[a2] = r["n2"]

        if hard_locks:
            lines.append(f"  Confirmed Exclusivity Groups (>95% confidence):")
            # Group into clusters: if A excludes B and A excludes C, they form a group
            groups = _cluster_pairs(hard_locks)
            for i, group in enumerate(groups, 1):
                # Sort by frequency within group (most common first)
                members = sorted(group, key=lambda a: anom_freq.get(a, 0), reverse=True)
                member_strs = [f"{a} ({anom_freq.get(a, '?')}/{N})" for a in members]
                lines.append(f"    Group {i}: {', '.join(member_strs)}")
            lines.append("")

        if likely:
            lines.append(f"  Likely Exclusions (needs more data):")
            for r in likely:
                a1, a2 = r["pair"]
                lines.append(f"    {a1} <-> {a2}  (seen {r['n1']}x / {r['n2']}x, likelihood {r['likelihood']:.2f})")
            lines.append("")

        if errors:
            lines.append(f"  Audit Flags (possible misidentifications):")
            for r in errors:
                a1, a2 = r["pair"]
                lines.append(f"    {a1} + {a2}: co-occurred {r['actual']}x but expected {r['expected']:.1f}x")
            lines.append("")

        # Anomaly occurrence frequency
        if anom_freq:
            lines.append(f"  Anomaly Occurrence (sessions seen / total):")
            for anom, count in sorted(anom_freq.items(), key=lambda x: x[1], reverse=True):
                pct = (count / N) * 100
                lines.append(f"    {anom}: {count}/{N} ({pct:.0f}%)")
            lines.append("")

    return "\n".join(lines)


def _cluster_pairs(pair_results):
    """Cluster exclusivity pairs into groups.
    
    If A-B and A-C are both hard locks, they form one group {A, B, C}.
    Uses union-find for grouping.
    """
    parent = {}

    def find(x):
        if x not in parent:
            parent[x] = x
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    for r in pair_results:
        a1, a2 = r["pair"]
        union(a1, a2)

    groups = {}
    for node in parent:
        root = find(node)
        groups.setdefault(root, set()).add(node)

    return list(groups.values())


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
