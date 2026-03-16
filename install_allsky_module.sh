#!/bin/bash
#
# Install the Heater+ Allsky module into any Allsky installation.
# Does NOT modify Allsky source – only user modules and config.
#
# Usage:
#   ./install_allsky_module.sh
#   ./install_allsky_module.sh /path/to/allsky
#
# Expects: ALLSKY_MODULE_LOCATION (e.g. /opt/allsky) for Python modules
#          ALLSKY_MODULES (e.g. .../config/modules) for postprocessing_*.json
#

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_SRC="${SCRIPT_DIR}/allsky_heaterplussettings.py"

if [[ ! -f "$MODULE_SRC" ]]; then
    echo "Error: allsky_heaterplussettings.py not found in $SCRIPT_DIR"
    exit 1
fi

# Allsky-Pfade ermitteln
if [[ -n "$1" ]]; then
    ALLSKY_HOME="$1"
elif [[ -n "$ALLSKY_HOME" ]]; then
    :
elif [[ -d /home/pi/allsky ]]; then
    ALLSKY_HOME="/home/pi/allsky"
elif [[ -d /opt/allsky ]]; then
    ALLSKY_HOME="/opt/allsky"
else
    echo "Allsky not found. Please specify: ./install_allsky_module.sh /path/to/allsky"
    exit 1
fi

# Load variables.sh for ALLSKY_MODULE_LOCATION, ALLSKY_MODULES
if [[ -f "${ALLSKY_HOME}/variables.sh" ]]; then
    export ALLSKY_HOME
    # shellcheck source=/dev/null
    source "${ALLSKY_HOME}/variables.sh"
else
    echo "variables.sh not found. Using default paths."
    ALLSKY_MODULE_LOCATION="${ALLSKY_MODULE_LOCATION:-/opt/allsky}"
    ALLSKY_MODULES="${ALLSKY_MODULES:-${ALLSKY_HOME}/config/modules}"
fi

MODULES_DIR="${ALLSKY_MODULE_LOCATION}/modules"
CONFIG_MODULES="${ALLSKY_MODULES}"
PERIODIC_JSON="${CONFIG_MODULES}/postprocessing_periodic.json"

echo "=== Install Heater+ Allsky Module ==="
echo "  Modul-Quelle:     $MODULE_SRC"
echo "  Ziel (Python):   $MODULES_DIR"
echo "  Config:          $CONFIG_MODULES"
echo ""

# Copy module (to both standard locations for maximum compatibility)
# 1. User-Module: /opt/allsky/modules
mkdir -p "$MODULES_DIR" 2>/dev/null || sudo mkdir -p "$MODULES_DIR"
if [[ -w "$MODULES_DIR" ]] 2>/dev/null; then
    cp "$MODULE_SRC" "$MODULES_DIR/allsky_heaterplussettings.py"
else
    sudo cp "$MODULE_SRC" "$MODULES_DIR/allsky_heaterplussettings.py"
fi
echo "[OK] Modul kopiert nach $MODULES_DIR/"

# 2. Scripts-Module: ALLSKY_SCRIPTS/modules (Fallback)
SCRIPTS_MODULES="${ALLSKY_SCRIPTS:-${ALLSKY_HOME}/scripts}/modules"
if [[ -d "$SCRIPTS_MODULES" ]] && [[ "$SCRIPTS_MODULES" != "$MODULES_DIR" ]]; then
    cp "$MODULE_SRC" "$SCRIPTS_MODULES/allsky_heaterplussettings.py"
    echo "[OK] Module also copied to $SCRIPTS_MODULES/ (fallback)"
fi

# postprocessing_periodic.json aktualisieren
mkdir -p "$CONFIG_MODULES"
if [[ ! -f "$PERIODIC_JSON" ]] || [[ ! -s "$PERIODIC_JSON" ]]; then
    echo '{}' > "$PERIODIC_JSON"
fi

# Check if module is already in periodic flow
if grep -q '"heaterplussettings"' "$PERIODIC_JSON" 2>/dev/null; then
    echo "[OK] Heater+ Settings bereits in postprocessing_periodic.json"
else
    python3 << PYEOF
import json
path = "${PERIODIC_JSON}"
try:
    with open(path) as f:
        data = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    data = {}
entry = {
    "heaterplussettings": {
        "module": "allsky_heaterplussettings.py",
        "metadata": {
            "name": "Heater+ Settings",
            "description": "Edit Heater+ PCB settings via Allsky GUI",
            "module": "allsky_heaterplussettings",
            "events": ["periodic"],
            "arguments": {
                "temp_set": 20, "heaterpin": 18, "fanpin": 16, "enable_dewheater": "true",
                "enable_fan": "true", "deltacooling": 2, "deltadewpoint": 4, "settodewpoint": "false",
                "pid_p": 15, "pid_i": 0.3, "pid_d": 0, "sensorupdateintervall": 2,
                "tslgainindex": 0, "tslintmindex": 0, "tsl_autogain": "true", "tcs_autogain": "true",
                "tsl_high_threshold": 40000, "tsl_low_threshold": 1000,
                "tcs_high_threshold": 17500, "tcs_low_threshold": 2000,
                "temp_max_dome": 0, "enable_json": "true", "sea_level_pressure": 1013.25,
                "heater_power_check": "true", "heater_duty_min_for_check": 20, "sensor_only": "false",
            },
        },
        "type": "user",
        "enabled": True,
        "lastexecutiontime": "0",
        "lastexecutionresult": "",
    },
}
data.update(entry)
with open(path, "w") as f:
    json.dump(data, f, indent=4)
print("[OK] Heater+ Settings added to postprocessing_periodic.json")
PYEOF
fi

echo ""
echo "=== Installation complete ==="
echo "In Allsky GUI under 'Module Manager' select flow 'Periodic Jobs',"
echo "then enable and configure 'Heater+ Settings'."
echo ""
echo "Note: heater_plus.py must be running for settings to take effect."
echo "      The module checks periodically whether the control script is running."
