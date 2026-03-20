#!/bin/bash
#
# install_allsky_heaterpcb.sh
# ===========================
# Vollständige Installation und Konfiguration für Allsky + Heater-PCB auf Raspberry Pi OS Lite.
# Idempotent: Kann mehrfach ausgeführt werden (überspringt bereits Erledigtes).
#
# Voraussetzungen:
#   - Raspberry Pi OS Lite (oder Desktop), frisch aufgesetzt
#   - Allsky MUSS VORHER manuell (interaktiv) installiert werden
#   - Script mit sudo ausführen
#
# Ablauf:
#   1. Allsky prüfen
#   2. System-Pakete, I2C aktivieren
#   3. Python-Pakete (ohne venv, system-weit)
#   4. InfluxDB 2 installieren, Bucket + Token anlegen
#   5. Grafana installieren, Datasource + Dashboard
#   6. Heater+ Dateien, hp_settings.json (Pfade + optional Token)
#   7. Allsky-Modul + Overlay integrieren
#   8. Systemd-Service für heater_plus (optional)
#
set -e

# --- Konfiguration ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="/home/pi/heater_plus"
ALLSKY_HOME="${ALLSKY_HOME:-/home/pi/allsky}"
ALLSKY_CONFIG="${ALLSKY_CONFIG:-/home/pi/allsky/config}"
INFLUX_ORG="allsky"
INFLUX_BUCKET="heater_plus"
INFLUX_USER="admin"
INFLUX_PASSWORD="allskyheater"
GRAFANA_ADMIN_USER="admin"
GRAFANA_ADMIN_PASSWORD="admin"

# --- Architektur (32/64-bit) ---
ARCH="$(uname -m)"
case "$ARCH" in
    aarch64|arm64)  ARCH_FOR_INFLUX="arm64" ;;
    armv7l|armhf)   ARCH_FOR_INFLUX="armhf" ;;
    *)              ARCH_FOR_INFLUX="" ;;
esac

# --- Logging ---
log() { echo "[$(date +%H:%M:%S)] $*"; }
warn() { log "WARN: $*"; }
err()  { log "FEHLER: $*"; echo "$*" >&2; }

# --- Fortschritt ---
TOTAL_STEPS=8
progress_step() {
    local step="$1" desc="$2"
    echo ""
    log ">>> Schritt $step/$TOTAL_STEPS: $desc <<<"
}

# --- Hilfsfunktionen (Idempotenz) ---
is_pkg_installed() {
    dpkg -l "$1" 2>/dev/null | grep -q '^ii'
}

is_pip_installed() {
    python3 -c "import $1" 2>/dev/null
}

pip_needs_break_system() {
    for f in /usr/lib/python3.*/EXTERNALLY-MANAGED; do
        [[ -f "$f" ]] && return 0
    done
    return 1
}

influx_bucket_exists() {
    influx bucket list --org "$INFLUX_ORG" 2>/dev/null | grep -q "$INFLUX_BUCKET"
}

# --- 1. Voraussetzungen ---
check_prereqs() {
    progress_step 1 "Voraussetzungen prüfen"
    if [[ $EUID -ne 0 ]]; then
        err "Bitte mit sudo ausführen: sudo $0"
        exit 1
    fi
    if [[ ! -d "$ALLSKY_HOME" ]] || [[ ! -f "$ALLSKY_HOME/variables.sh" ]]; then
        err "Allsky nicht gefunden unter $ALLSKY_HOME"
        err "Bitte zuerst Allsky manuell installieren, danach dieses Script erneut ausführen."
        exit 1
    fi
    log "Allsky gefunden: $ALLSKY_HOME"
    log "Architektur: $ARCH ($ARCH_FOR_INFLUX)"
}

# --- 2. System-Pakete ---
install_system_packages() {
    progress_step 2 "System-Pakete installieren"
    apt-get update || { err "apt-get update fehlgeschlagen"; exit 1; }

    local packages=(
        python3-pip
        python3-venv
        python3-dev
        python3-smbus
        git
        i2c-tools
        libatlas-base-dev
        curl
        wget
        gpg
        jq
    )
    local n=0 total="${#packages[@]}"
    for pkg in "${packages[@]}"; do
        n=$((n + 1))
        if is_pkg_installed "$pkg"; then
            log "  [$n/$total] $pkg bereits installiert"
        else
            log "  [$n/$total] Installiere $pkg ..."
            apt-get install -y "$pkg" || { err "Installation von $pkg fehlgeschlagen"; exit 1; }
        fi
    done
}

# --- 3. I2C aktivieren ---
I2C_WAS_ACTIVATED=0
enable_i2c() {
    progress_step 3 "I2C aktivieren"
    # Methode 1: raspi-config (offiziell, funktioniert auf allen Pi-OS-Versionen)
    if command -v raspi-config >/dev/null 2>&1; then
        if raspi-config nonint get_i2c 2>/dev/null; then
            if [[ -e /dev/i2c-1 ]] || [[ -e /dev/i2c-0 ]]; then
                log "[OK] I2C bereits aktiviert"
            else
                log "[OK] I2C in Config aktiv – Reboot nötig damit /dev/i2c-1 erscheint"
                I2C_WAS_ACTIVATED=1
                touch /var/run/reboot-required 2>/dev/null || true
            fi
            return 0
        fi
        if raspi-config nonint do_i2c 0 2>/dev/null; then
            log "[OK] I2C aktiviert (raspi-config)"
            I2C_WAS_ACTIVATED=1
            touch /var/run/reboot-required 2>/dev/null || true
            return 0
        fi
    fi

    # Methode 2: Manuell config.txt bearbeiten
    local cfg
    for cfg in /boot/firmware/config.txt /boot/config.txt; do
        if [[ -f "$cfg" ]]; then
            if grep -q '^dtparam=i2c_arm=on' "$cfg" 2>/dev/null; then
                if [[ -e /dev/i2c-1 ]] || [[ -e /dev/i2c-0 ]]; then
                    log "[OK] I2C bereits aktiviert"
                else
                    log "[OK] I2C in Config aktiv – Reboot nötig damit /dev/i2c-1 erscheint"
                    I2C_WAS_ACTIVATED=1
                    touch /var/run/reboot-required 2>/dev/null || true
                fi
                return 0
            fi
            if grep -q '^#dtparam=i2c_arm=on' "$cfg" 2>/dev/null; then
                sed -i 's/^#dtparam=i2c_arm=on/dtparam=i2c_arm=on/' "$cfg"
            else
                echo "dtparam=i2c_arm=on" >> "$cfg"
            fi
            log "[OK] I2C aktiviert (config.txt bearbeitet)"
            I2C_WAS_ACTIVATED=1
            touch /var/run/reboot-required 2>/dev/null || true
            return 0
        fi
    done
    warn "config.txt nicht gefunden – I2C manuell aktivieren: raspi-config → Interface Options → I2C"
}

# --- 4. Python-Pakete ---
install_python_packages() {
    progress_step 4 "Python-Pakete installieren"
    local pip_extra=""
    if pip_needs_break_system; then
        pip_extra="--break-system-packages"
        log "Verwende pip mit --break-system-packages (PEP 668)"
    fi

    local packages=(
        gpiozero
        adafruit-blinka
        adafruit-circuitpython-bme280
        adafruit-circuitpython-tsl2591
        pi-ina226
        simple-pid
        influxdb-client
        RPi.AS3935
    )

    local n=0 total="${#packages[@]}"
    for pkg in "${packages[@]}"; do
        n=$((n + 1))
        local mod
        case "$pkg" in
            gpiozero) mod="gpiozero" ;;
            adafruit-blinka) mod="board" ;;
            adafruit-circuitpython-bme280) mod="adafruit_bme280" ;;
            adafruit-circuitpython-tsl2591) mod="adafruit_tsl2591" ;;
            pi-ina226) mod="ina226" ;;
            simple-pid) mod="simple_pid" ;;
            influxdb-client) mod="influxdb_client" ;;
            RPi.AS3935) mod="RPi_AS3935" ;;
            *) mod="" ;;
        esac
        local install_pkg="$pkg"
        [[ "$pkg" == "pi-ina226" ]] && install_pkg="git+https://github.com/e71828/pi_ina226.git"
        if [[ -n "$mod" ]] && is_pip_installed "$mod" 2>/dev/null; then
            log "  [$n/$total] $pkg bereits installiert"
        else
            log "  [$n/$total] Installiere $pkg ..."
            python3 -m pip install --quiet $pip_extra "$install_pkg" || {
                warn "pip install $pkg fehlgeschlagen, überspringe"
            }
        fi
    done

    # tcs3448 ist lokales Modul in heater_plus, wird mit kopiert
    log "[OK] tcs3448 wird mit Heater+ Dateien installiert"
}

# --- 5. InfluxDB ---
install_influxdb() {
    progress_step 5 "InfluxDB 2 installieren"
    if is_pkg_installed influxdb2; then
        log "[OK] InfluxDB2 bereits installiert"
    else
        log "InfluxData Repository hinzufügen ..."
        curl -sL https://repos.influxdata.com/influxdata-archive.key -o /tmp/influxdata-archive.key
        if gpg --show-keys --with-fingerprint --with-colons /tmp/influxdata-archive.key 2>/dev/null | grep -q '24C975CBA61A024EE1B631787C3D57159FC2F927\|AC10D7449F343ADCEFDDC2B6DA61C26A0585BD3B'; then
            cat /tmp/influxdata-archive.key | gpg --dearmor | tee /etc/apt/keyrings/influxdata-archive.gpg > /dev/null
            echo "deb [signed-by=/etc/apt/keyrings/influxdata-archive.gpg] https://repos.influxdata.com/debian stable main" | tee /etc/apt/sources.list.d/influxdata.list > /dev/null
        else
            err "InfluxData GPG-Key konnte nicht verifiziert werden"
            exit 1
        fi
        rm -f /tmp/influxdata-archive.key
        apt-get update -qq
        apt-get install -y -qq influxdb2
    fi

    systemctl enable influxdb 2>/dev/null || systemctl enable influxdb2 2>/dev/null || true
    systemctl start influxdb 2>/dev/null || systemctl start influxdb2 2>/dev/null || true
    sleep 5

    # Setup per HTTP-API (influx CLI ist separat, API funktioniert immer)
    INFLUX_TOKEN=""
    local setup_resp
    setup_resp=$(curl -s -X POST "http://localhost:8086/api/v2/setup" \
        -H "Content-Type: application/json" \
        -d "{\"username\":\"$INFLUX_USER\",\"password\":\"$INFLUX_PASSWORD\",\"org\":\"$INFLUX_ORG\",\"bucket\":\"$INFLUX_BUCKET\"}" 2>/dev/null) || true

    if [[ -n "$setup_resp" ]] && echo "$setup_resp" | grep -q '"token"'; then
        INFLUX_TOKEN=$(echo "$setup_resp" | jq -r '.auth.token // empty')
    fi
    if [[ -z "$INFLUX_TOKEN" ]]; then
        # Bereits konfiguriert? Dann müssen wir existierenden Token holen - nur via influx CLI oder manuell
        if curl -s "http://localhost:8086/health" | grep -q "pass"; then
            warn "InfluxDB läuft, Setup war evtl. schon erfolgt. Token bitte aus Web-UI (http://localhost:8086) kopieren und in hp_settings.json eintragen."
        else
            warn "InfluxDB Setup fehlgeschlagen - Token manuell in hp_settings.json eintragen"
        fi
    else
        export INFLUX_TOKEN
        log "[OK] InfluxDB Setup fertig, Token ermittelt"
    fi
}

# --- 6. Grafana ---
install_grafana() {
    progress_step 6 "Grafana installieren"
    if is_pkg_installed grafana || is_pkg_installed grafana-server; then
        log "[OK] Grafana bereits installiert"
    else
        log "Grafana Repository hinzufügen ..."
        mkdir -p /etc/apt/keyrings
        wget -q -O - https://apt.grafana.com/gpg.key | gpg --dearmor | tee /etc/apt/keyrings/grafana.gpg > /dev/null
        echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" | tee /etc/apt/sources.list.d/grafana.list > /dev/null
        apt-get update -qq
        apt-get install -y grafana
    fi

    # Grafana starten (nach apt install: daemon-reload nötig)
    systemctl daemon-reload
    systemctl enable grafana-server 2>/dev/null || true
    systemctl start grafana-server 2>/dev/null || true

    # Warten bis Grafana bereit ist (max. 30 Sekunden)
    log "Warte auf Grafana ..."
    local grafana_ready=0
    for i in $(seq 1 30); do
        if curl -s -o /dev/null -w "%{http_code}" -u "$GRAFANA_ADMIN_USER:$GRAFANA_ADMIN_PASSWORD" "http://localhost:3000/api/health" 2>/dev/null | grep -q "200"; then
            grafana_ready=1
            break
        fi
        sleep 1
    done
    if [[ $grafana_ready -eq 0 ]]; then
        warn "Grafana reagiert nicht nach 30s – Datasource/Dashboard evtl. später manuell: import_grafana_dashboard.sh"
    else
        # Datasource + Dashboard
        local grafana_url="http://localhost:3000"
        local ds_uid="influxdb-heater-plus"

        # Datasource (nur wenn Token vorhanden)
        if [[ -n "$INFLUX_TOKEN" ]]; then
            log "Grafana Datasource einrichten ..."
            if curl -s -u "$GRAFANA_ADMIN_USER:$GRAFANA_ADMIN_PASSWORD" "$grafana_url/api/datasources" 2>/dev/null | grep -q "$ds_uid"; then
                log "[OK] Grafana Datasource bereits vorhanden"
            else
                curl -s -X POST -u "$GRAFANA_ADMIN_USER:$GRAFANA_ADMIN_PASSWORD" \
                    -H "Content-Type: application/json" \
                    -d "{\"name\":\"InfluxDB Heater+\",\"type\":\"influxdb\",\"uid\":\"$ds_uid\",\"url\":\"http://localhost:8086\",\"access\":\"proxy\",\"jsonData\":{\"version\":\"Flux\",\"organization\":\"$INFLUX_ORG\"},\"secureJsonData\":{\"token\":\"$INFLUX_TOKEN\"}}" \
                    "$grafana_url/api/datasources" 2>/dev/null && log "[OK] Datasource erstellt" || warn "Grafana Datasource konnte nicht erstellt werden"
            fi
        else
            warn "InfluxDB Token fehlt – Datasource manuell anlegen (uid: influxdb-heater-plus)"
        fi

        # Dashboard importieren
        local dash_file="${SCRIPT_DIR}/grafana_dashboard_heater_plus_pro.json"
        if [[ -f "$dash_file" ]]; then
            log "Grafana Dashboard importieren ..."
            if curl -s -u "$GRAFANA_ADMIN_USER:$GRAFANA_ADMIN_PASSWORD" "$grafana_url/api/search?type=dash-db" 2>/dev/null | grep -q "heater-plus-allsky-pro"; then
                log "[OK] Grafana Dashboard bereits vorhanden"
            else
                local payload
                payload=$(jq -n --slurpfile d "$dash_file" '{dashboard: $d[0], overwrite: true}' 2>/dev/null)
                if [[ -n "$payload" ]]; then
                    local resp
                    resp=$(curl -s -w "\n%{http_code}" -X POST -u "$GRAFANA_ADMIN_USER:$GRAFANA_ADMIN_PASSWORD" \
                        -H "Content-Type: application/json" \
                        -d "$payload" \
                        "$grafana_url/api/dashboards/db" 2>/dev/null)
                    local code="${resp##*$'\n'}"
                    if [[ "$code" == "200" ]] || [[ "$code" == "201" ]]; then
                        log "[OK] Dashboard importiert"
                    else
                        warn "Grafana Dashboard Import fehlgeschlagen (HTTP $code). Manuell: import_grafana_dashboard.sh"
                    fi
                else
                    warn "Dashboard-JSON konnte nicht geladen werden"
                fi
            fi
        else
            warn "grafana_dashboard_heater_plus_pro.json nicht gefunden in $SCRIPT_DIR"
        fi
    fi
}

# --- 7. Heater+ Dateien ---
install_heater_plus_files() {
    progress_step 7 "Heater+ Dateien installieren"
    # shellcheck source=/dev/null
    source "$SCRIPT_DIR/heater_plus_runtime_sync.inc.sh"

    mkdir -p "$INSTALL_DIR"
    # Python: Symlink wenn Paket unter $INSTALL_DIR liegt, sonst Kopie (siehe heater_plus_runtime_sync.inc.sh)
    heater_plus_sync_runtime_scripts heater_plus.py tcs3448.py allsky_heaterplussettings.py

    # hp_settings.json: liegt im Git-Paket mit Platzhalter-Token; Install kopiert bei Erst-Installation
    local hp_settings="$INSTALL_DIR/hp_settings.json"
    if [[ ! -f "$hp_settings" ]]; then
        if [[ -f "$SCRIPT_DIR/hp_settings.json" ]]; then
            cp -f "$SCRIPT_DIR/hp_settings.json" "$INSTALL_DIR/hp_settings.json"
            log "[OK] hp_settings.json aus Paket nach $INSTALL_DIR (token_db ggf. REPLACE_WITH_INFLUX_TOKEN → echtes Token setzen)"
        else
            warn "hp_settings.json fehlt im Paket – bitte Repo prüfen"
        fi
    else
        log "[OK] hp_settings.json existiert bereits – nicht überschrieben"
    fi

    for f in grafana_dashboard_heater_plus_pro.json import_grafana_dashboard.sh; do
        if [[ -f "$SCRIPT_DIR/$f" ]]; then
            cp -f "$SCRIPT_DIR/$f" "$INSTALL_DIR/"
            log "[OK] $f kopiert"
        else
            warn "$f nicht gefunden in $SCRIPT_DIR"
        fi
    done

    # hp_settings.json: Pfade IMMER setzen (auch ohne Influx-Token – sonst falsche Overlay-Pfade)
    local extra_json="${ALLSKY_CONFIG:-/home/pi/allsky/config}/overlay/extra/heater_plus.json"
    if [[ -f "$hp_settings" ]] && command -v jq >/dev/null 2>&1; then
        jq --arg p "$extra_json" '.filename_json = $p' "$hp_settings" > "${hp_settings}.tmp"
        mv "${hp_settings}.tmp" "$hp_settings"
        if [[ -n "$INFLUX_TOKEN" ]]; then
            jq --arg t "$INFLUX_TOKEN" '.token_db = $t' "$hp_settings" > "${hp_settings}.tmp"
            mv "${hp_settings}.tmp" "$hp_settings"
        fi
    elif [[ -f "$hp_settings" ]] && [[ -n "$INFLUX_TOKEN" ]] && command -v jq >/dev/null 2>&1; then
        jq --arg t "$INFLUX_TOKEN" '.token_db = $t' "$hp_settings" > "${hp_settings}.tmp"
        mv "${hp_settings}.tmp" "$hp_settings"
    fi

    if [[ -f "$hp_settings" ]] && grep -q 'REPLACE_WITH_INFLUX_TOKEN' "$hp_settings" 2>/dev/null; then
        warn "token_db noch Platzhalter – InfluxDB-Token in http://localhost:8086 anlegen und in $hp_settings eintragen (oder Install erneut mit erfolgreichem Influx-Setup)"
    fi

    chown -R pi:pi "$INSTALL_DIR" 2>/dev/null || true
}

# --- 8. Allsky-Modul + Overlay ---
install_allsky_integration() {
    progress_step 8 "Allsky Heater+ Modul + Overlay"
    export ALLSKY_HOME ALLSKY_CONFIG

    if [[ -f "$ALLSKY_HOME/variables.sh" ]]; then
        # shellcheck source=/dev/null
        source "$ALLSKY_HOME/variables.sh"
    fi

    local MODULES_DIR="${ALLSKY_MODULE_LOCATION:-/opt/allsky}/modules"
    local OVERLAY_EXTRA="${ALLSKY_CONFIG}/overlay/extra"
    local OVERLAY_TEMPLATES="${ALLSKY_CONFIG}/overlay/myTemplates"

    mkdir -p "$MODULES_DIR" "$OVERLAY_EXTRA" "$OVERLAY_TEMPLATES"
    chmod 775 "$OVERLAY_EXTRA" 2>/dev/null || true
    chown pi:pi "$OVERLAY_EXTRA" 2>/dev/null || true

    # Modul
    if [[ -f "$SCRIPT_DIR/allsky_heaterplussettings.py" ]]; then
        cp "$SCRIPT_DIR/allsky_heaterplussettings.py" "$MODULES_DIR/"
        [[ -w "$MODULES_DIR" ]] || sudo chown pi:pi "$MODULES_DIR" 2>/dev/null || true
        log "[OK] Allsky-Modul kopiert"
    fi

    # Fallback extra/heater_plus.json (Allsky lädt ALLE *.json aus overlay/extra/)
    if [[ -f "$SCRIPT_DIR/heater_plus.json" ]]; then
        cp "$SCRIPT_DIR/heater_plus.json" "$OVERLAY_EXTRA/heater_plus.json"
    elif [[ -f "$OVERLAY_EXTRA/heater_plus.json" ]]; then
        log "[OK] heater_plus.json existiert bereits"
    else
        echo '{"HP_TEMP_DOME":{"value":"--","expires":60}}' > "$OVERLAY_EXTRA/heater_plus.json"
    fi
    chmod 664 "$OVERLAY_EXTRA/heater_plus.json" 2>/dev/null || true
    chown pi:pi "$OVERLAY_EXTRA/heater_plus.json" 2>/dev/null || true

    # Overlay-Templates und userfields installieren
    local OVERLAY_CONFIG_SRC="${SCRIPT_DIR}/overlay_config"
    [[ ! -d "$OVERLAY_CONFIG_SRC" ]] && OVERLAY_CONFIG_SRC="$(dirname "$SCRIPT_DIR")/overlay_config"
    local OVERLAY_CONFIG_DST="${ALLSKY_CONFIG}/overlay/config"
    if [[ -d "$OVERLAY_CONFIG_SRC" ]]; then
        mkdir -p "$OVERLAY_CONFIG_DST" "$OVERLAY_TEMPLATES"
        # userfields.json: HeaterPlus-Felder mergen
        if [[ -f "$OVERLAY_CONFIG_SRC/config/userfields.json" ]]; then
            python3 << PYEOF
import json
dst_path = "$OVERLAY_CONFIG_DST/userfields.json"
src_path = "$OVERLAY_CONFIG_SRC/config/userfields.json"
try:
    with open(dst_path) as f:
        existing = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    existing = {"data": []}
with open(src_path) as f:
    hp_data = json.load(f)
hp_ids = {e["id"] for e in hp_data.get("data", [])}
merged = [e for e in existing.get("data", []) if e.get("id") not in hp_ids]
merged.extend(hp_data.get("data", []))
merged.sort(key=lambda x: x.get("id", 0))
with open(dst_path, "w") as f:
    json.dump({"data": merged}, f, separators=(",", ":"))
PYEOF
            log "[OK] userfields.json (HeaterPlus) installiert/gemerged"
        fi
        # Overlay-Configs kopieren
        for f in overlay-RPi.json overlay-RPi_HQ-4056x3040-both.json; do
            if [[ -f "$OVERLAY_CONFIG_SRC/config/$f" ]]; then
                cp "$OVERLAY_CONFIG_SRC/config/$f" "$OVERLAY_CONFIG_DST/"
                log "[OK] Overlay $f installiert"
            fi
        done
        # Template nach myTemplates
        if [[ -f "$OVERLAY_CONFIG_SRC/myTemplates/overlay1-RPi_HQ-4056x3040-both.json" ]]; then
            cp "$OVERLAY_CONFIG_SRC/myTemplates/overlay1-RPi_HQ-4056x3040-both.json" "$OVERLAY_TEMPLATES/"
            log "[OK] Heater+ Overlay-Template installiert (myTemplates)"
        fi
        chown -R pi:pi "$OVERLAY_CONFIG_DST" "$OVERLAY_TEMPLATES" 2>/dev/null || true
    else
        log "[INFO] overlay_config nicht gefunden, Overlay-Templates übersprungen"
    fi

    # postprocessing_periodic.json
    local PERIODIC_JSON="${ALLSKY_MODULES:-$ALLSKY_CONFIG/modules}/postprocessing_periodic.json"
    mkdir -p "$(dirname "$PERIODIC_JSON")"
    if [[ ! -f "$PERIODIC_JSON" ]] || [[ ! -s "$PERIODIC_JSON" ]]; then
        echo '{}' > "$PERIODIC_JSON"
    fi
    if ! grep -q '"heaterplussettings"' "$PERIODIC_JSON" 2>/dev/null; then
        python3 << PYEOF
import json
path = "$PERIODIC_JSON"
try:
    with open(path) as f:
        data = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    data = {}
data["heaterplussettings"] = {
    "module": "allsky_heaterplussettings.py",
    "metadata": {"name": "Heater+ Settings", "module": "allsky_heaterplussettings", "events": ["periodic"], "arguments": {"control_script_enabled": "true"}},
    "type": "user", "enabled": True
}
with open(path, "w") as f:
    json.dump(data, f, indent=4)
PYEOF
        log "[OK] Heater+ in postprocessing_periodic.json eingetragen"
    else
        log "[OK] Heater+ bereits in postprocessing_periodic.json"
    fi

}

# --- 9. Systemd-Service ---
install_systemd_service() {
    echo ""
    log ">>> Systemd-Service für heater_plus <<<"
    local svc="/etc/systemd/system/heater_plus.service"
    if [[ -f "$svc" ]]; then
        log "[OK] heater_plus.service bereits vorhanden"
    else
        cat > "$svc" << 'SVCEOF'
[Unit]
Description=Heater+ PCB Control
After=network.target influxdb.service

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/heater_plus
ExecStart=/usr/bin/python3 /home/pi/heater_plus/heater_plus.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
SVCEOF
        systemctl daemon-reload
        systemctl enable heater_plus.service
        log "[OK] heater_plus.service erstellt und aktiviert"
    fi
    # Nicht automatisch starten - Nutzer startet über Allsky-GUI (control_script_enabled)
}

# --- 10. Abschluss ---
print_summary() {
    log ""
    log "=== Installation abgeschlossen ==="
    log ""
    if [[ "${I2C_WAS_ACTIVATED:-0}" -eq 1 ]]; then
        log "*** REBOOT JETZT NÖTIG ***  I2C wurde aktiviert und wirkt erst nach Neustart!"
        log "    Befehl:  sudo reboot"
        log ""
    fi
    log "Grafana:        http://$(hostname -I | awk '{print $1}'):3000  (admin/admin - Passwort ändern!)"
    log "Allsky WebUI:   http://$(hostname -I | awk '{print $1}')/allsky"
    log "InfluxDB:       http://localhost:8086"
    log ""
    log "Nächste Schritte:"
    [[ "${I2C_WAS_ACTIVATED:-0}" -eq 1 ]] && log "  1. sudo reboot  (zwingend für I2C)"
    log "  2. Im Allsky-GUI: Module Manager -> Periodic Jobs -> Heater+ Settings aktivieren"
    log "  3. Heater+ Control-Script über die Checkbox 'Heater+ Control-Script aktiv' starten"
    log "  4. Allsky: WebUI -> Overlay – Tag- und Nacht-Overlay auf Heater+-Vorlage stellen"
    log "     (z. B. overlay1-RPi_HQ-4056x3040-both.json unter myTemplates), sonst keine HP-Felder"
    log "  5. Entwicklung in ~/heater_plus: vor git push ./sync_dev_to_package.sh (Paket = GitHub)"
    log "  6. Echte Kopien statt Symlinks: HEATER_PLUS_USE_SYMLINKS=0 sudo $0"
    log ""
}

# --- Hauptablauf ---
main() {
    log "=== Allsky + Heater-PCB Installation ==="
    check_prereqs
    install_system_packages
    enable_i2c
    install_python_packages
    install_influxdb
    install_grafana
    install_heater_plus_files
    install_allsky_integration
    install_systemd_service
    print_summary
}

main "$@"
