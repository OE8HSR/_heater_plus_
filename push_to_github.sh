#!/bin/bash
#
# Änderungen committen und zu GitHub pushen (Repo-Root = Verzeichnis dieses Skripts).
#
#   ./push_to_github.sh
#   ./push_to_github.sh "Kurze Beschreibung der Änderung"
#
set -e
cd "$(dirname "$0")"

MSG="${1:-Update $(date '+%Y-%m-%d %H:%M')}"

git add -A
if git diff --cached --quiet; then
    echo "[push] Nichts zu committen (Arbeitsbaum leer)."
    exit 0
fi

echo "[push] Commit: $MSG"
git commit -m "$MSG"
echo "[push] Push zu origin …"
git push
