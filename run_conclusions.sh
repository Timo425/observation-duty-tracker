#!/usr/bin/env bash
# Cron-friendly wrapper around generate_conclusions.py.
#
# - Regenerates the per-game conclusions for every game with logs.
# - Markdown lands inside the repo (conclusions_<game>.md), HTML lands next
#   to the screenshots in Obsidian (set OBSDUTY_IMAGES_DIR or pass --images-dir).
# - If any conclusions_*.md changed, commits and pushes. The HTML is gitignored.
#
# Expected cron line:
#   0 9 * * 0 OBSDUTY_IMAGES_DIR="…" /…/observation-duty-tracker/run_conclusions.sh \
#            >> /tmp/obsduty-conclusions.log 2>&1
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"

# Currently only game_8 is tracked; add more here as they come online.
GAMES=("game_8")

for game in "${GAMES[@]}"; do
    python3 generate_conclusions.py --game "$game"
done

# Stage only the conclusions_*.md files. Anything else the user has in
# flight stays untouched.
git add conclusions_*.md 2>/dev/null || true

if git diff --cached --quiet -- conclusions_*.md; then
    echo "[$(date '+%F %T')] no conclusions changes to commit"
    exit 0
fi

git commit -m "Weekly conclusions update ($(date '+%F'))"
git push
echo "[$(date '+%F %T')] conclusions committed and pushed"
