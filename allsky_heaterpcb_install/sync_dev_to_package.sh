#!/bin/bash
#
# Entwickler-Workflow: ~/heater_plus/ → allsky_heaterpcb_install/ (für Git / GitHub)
#
# Du arbeitest und testest mit den Dateien unter ~/heater_plus/.
# Vor git commit / push diese Skript ausführen, damit das Paket (Repo) dieselbe Version hat
# wie deine getestete Laufzeit.
#
#   ./sync_dev_to_package.sh
#
# Umgebungsvariablen:
#   HEATER_PLUS_HOME   – Quelle (Standard: /home/pi/heater_plus)
#   HEATER_PLUS_PACKAGE – Ziel-Paketordner (Standard: Verzeichnis dieses Skripts)
#
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME="${HEATER_PLUS_HOME:-/home/pi/heater_plus}"
PACKAGE="${HEATER_PLUS_PACKAGE:-$SCRIPT_DIR}"

echo "[dev→pkg] Quelle (Laufzeit/Test): $RUNTIME"
echo "[dev→pkg] Ziel (Repo/Paket):      $PACKAGE"

missing=0
for f in heater_plus.py tcs3448.py allsky_heaterplussettings.py; do
    if [[ ! -f "$RUNTIME/$f" ]]; then
        echo "[dev→pkg] FEHLT an Laufzeit: $RUNTIME/$f" >&2
        missing=1
        continue
    fi
    cp -f "$RUNTIME/$f" "$PACKAGE/$f"
    echo "[dev→pkg] OK $f"
done

if [[ "$missing" -eq 1 ]]; then
    echo "[dev→pkg] Abgebrochen (Dateien fehlen)." >&2
    exit 1
fi

echo "[dev→pkg] Fertig. Jetzt: git diff / git commit / git push"
