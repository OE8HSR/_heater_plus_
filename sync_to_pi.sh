#!/bin/bash
#
# sync_to_pi.sh – Heater+ Dateien auf Raspberry Pi kopieren
# =========================================================
# Kopiert die aktualisierten Dateien per scp auf den Ziel-Pi.
#
# Verwendung:
#   ./sync_to_pi.sh                    # nutzt Standard-Host
#   ./sync_to_pi.sh pi@192.168.0.49    # eigener Host
#   ./sync_to_pi.sh allsky2            # Kurzform → pi@allsky2
#
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_HOST="${DEFAULT_HOST:-pi@allsky2}"

# Host aus Argument oder Default
if [[ -n "$1" ]]; then
    TARGET="$1"
    [[ "$TARGET" != *@* ]] && TARGET="pi@$TARGET"
else
    TARGET="$DEFAULT_HOST"
fi

echo ">>> Kopiere Heater+ Dateien nach $TARGET:/home/pi/heater_plus/"
echo ""

# ControlMaster: Einmal Passwort eingeben, Verbindung wird wiederverwendet
CTRL="/tmp/sync_heater_${USER}_$$"
cleanup() { ssh -S "$CTRL" -O exit "$TARGET" 2>/dev/null || true; }
trap cleanup EXIT

# Master-Verbindung öffnen (fragt hier nach Passwort)
ssh -o ControlMaster=yes -o ControlPath="$CTRL" -o ControlPersist=30 -f -N "$TARGET"
ssh -o ControlPath="$CTRL" "$TARGET" "mkdir -p /home/pi/heater_plus"

scp -o ControlPath="$CTRL" "$SCRIPT_DIR/heater_plus.py" \
    "$SCRIPT_DIR/tcs3448.py" \
    "$SCRIPT_DIR/hp_settings.json" \
    "$SCRIPT_DIR/install_minimal.sh" \
    "$TARGET:/home/pi/heater_plus/"

ssh -o ControlPath="$CTRL" "$TARGET" "chmod +x /home/pi/heater_plus/install_minimal.sh"

echo ""
echo "[OK] Fertig. Auf dem Pi:  cd ~/heater_plus && python3 heater_plus.py"
