#!/bin/bash
#
# Synchronisiert Python-Laufzeitdateien: Paket (allsky_heaterpcb_install) -> ~/heater_plus
#
# - Liegt das Paket unter ~/heater_plus/... (z. B. .../heater_plus/allsky_heaterpcb_install),
#   werden Symlinks angelegt – dann reicht Bearbeiten nur im Paket.
# - Sonst: Kopie (nach jeder Bearbeitung im Paket dieses Script ausführen).
#
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${HEATER_PLUS_HOME:-/home/pi/heater_plus}"

# shellcheck source=/dev/null
source "$SCRIPT_DIR/heater_plus_runtime_sync.inc.sh"

echo "[sync] Paket: $SCRIPT_DIR"
echo "[sync] Laufzeit: $INSTALL_DIR"
heater_plus_sync_runtime_scripts heater_plus.py tcs3448.py allsky_heaterplussettings.py

# Optional: Allsky-Modul (benötigt oft sudo)
if [[ "${1:-}" == "--with-module" ]] && [[ -f "$SCRIPT_DIR/allsky_heaterplussettings.py" ]]; then
    MOD="${ALLSKY_MODULE_LOCATION:-/opt/allsky}/modules"
    if [[ -w "$MOD" ]]; then
        cp -f "$SCRIPT_DIR/allsky_heaterplussettings.py" "$MOD/"
        echo "[sync] OK allsky_heaterplussettings.py -> $MOD"
    else
        echo "[sync] Hinweis: Modul nicht beschreibbar ($MOD). Bitte:" >&2
        echo "  sudo cp \"$SCRIPT_DIR/allsky_heaterplussettings.py\" \"$MOD/\"" >&2
    fi
fi

echo "[sync] Fertig. Bei laufendem heater_plus: Prozess neu starten (Allsky GUI oder pkill -f heater_plus.py …)."
