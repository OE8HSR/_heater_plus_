#!/bin/bash
#
# install_minimal.sh – Nur Sensorboard + Steuerscript
# ==================================================
# Installiert nur das Nötige, damit heater_plus.py die PCB-Sensoren auslesen
# und Werte auf der Konsole ausgeben kann.
# KEIN InfluxDB, KEIN Grafana, KEIN Allsky.
#
# Voraussetzungen: Raspberry Pi OS, mit sudo ausführen
#
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="/home/pi/heater_plus"

log() { echo "[$(date +%H:%M:%S)] $*"; }
err() { log "ERROR: $*"; exit 1; }

# --- 1. Root-Check ---
[[ $EUID -eq 0 ]] || err "Mit sudo ausführen: sudo $0"

# --- 2. System-Pakete ---
log ">>> System-Pakete installieren"
apt-get update -qq
apt-get install -y python3-pip python3-dev python3-smbus i2c-tools libatlas-base-dev jq git

# --- 3. I2C aktivieren ---
log ">>> I2C aktivieren"
for cfg in /boot/firmware/config.txt /boot/config.txt; do
    if [[ -f "$cfg" ]]; then
        if ! grep -q '^dtparam=i2c_arm=on' "$cfg" 2>/dev/null; then
            [[ -f "$cfg" ]] && grep -q '^#dtparam=i2c_arm=on' "$cfg" && sed -i 's/^#dtparam=i2c_arm=on/dtparam=i2c_arm=on/' "$cfg" || echo "dtparam=i2c_arm=on" >> "$cfg"
            log "[OK] I2C in $cfg aktiviert – Reboot nötig!"
            touch /var/run/reboot-required 2>/dev/null || true
        else
            log "[OK] I2C bereits aktiv"
        fi
        break
    fi
done

# --- 4. Python-Pakete (nur für Sensoren) ---
log ">>> Python-Pakete installieren"
pip_extra=""
for f in /usr/lib/python3.*/EXTERNALLY-MANAGED; do
    [[ -f "$f" ]] && pip_extra="--break-system-packages" && break
done

python3 -m pip install --quiet $pip_extra \
    gpiozero \
    adafruit-blinka \
    adafruit-circuitpython-bme280 \
    adafruit-circuitpython-tsl2591 \
    "git+https://github.com/e71828/pi_ina226.git" \
    simple-pid \
    RPi.AS3935

# --- 5. Heater+ Dateien kopieren ---
log ">>> Heater+ Dateien installieren"
mkdir -p "$INSTALL_DIR"
for f in heater_plus.py tcs3448.py hp_settings.json; do
    [[ -f "$SCRIPT_DIR/$f" ]] && cp "$SCRIPT_DIR/$f" "$INSTALL_DIR/" && log "  $f kopiert" || log "  WARN: $f nicht gefunden"
done

# hp_settings: sensor_only + sendtodb aus für reine Konsole
if [[ -f "$INSTALL_DIR/hp_settings.json" ]] && command -v jq >/dev/null 2>&1; then
    jq '.sensor_only = true | .sendtodb = false | .debugoutput = true' "$INSTALL_DIR/hp_settings.json" > "${INSTALL_DIR}/hp_settings.json.tmp"
    mv "${INSTALL_DIR}/hp_settings.json.tmp" "$INSTALL_DIR/hp_settings.json"
    log "[OK] hp_settings: sensor_only=true, sendtodb=false"
fi

chown -R pi:pi "$INSTALL_DIR" 2>/dev/null || true

# Overlay-JSON: Verzeichnis anlegen und Rechte setzen (Standard-Allsky-Pfad)
OVERLAY_EXTRA="/home/pi/allsky/config/overlay/extra"
mkdir -p "$OVERLAY_EXTRA"
chown -R pi:pi "$OVERLAY_EXTRA" 2>/dev/null || true
log "[OK] Overlay-Pfad $OVERLAY_EXTRA bereit für heater_plus.json"

# --- Fertig ---
log ""
log "=== Minimal-Installation fertig ==="
log ""
log "Falls I2C gerade aktiviert:  sudo reboot"
log ""
log "Steuerscript starten:"
log "  cd $INSTALL_DIR"
log "  python3 heater_plus.py"
log ""
log "Strg+C zum Beenden."
log ""
