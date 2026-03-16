#!/bin/bash
#
# install_allsky_heaterpcb.sh
# ===========================
# Full installation and configuration for Allsky + Heater-PCB on Raspberry Pi OS Lite.
# Idempotent: Can be run multiple times (skips already completed steps).
#
# Voraussetzungen:
#   - Raspberry Pi OS Lite (oder Desktop), frisch aufgesetzt
#   - Allsky MUSS VORHER manuell (interaktiv) installiert werden
#   - Run script with sudo
#
# Ablauf:
#   1. Check Allsky
#   2. System-Pakete, I2C aktivieren
#   3. Python-Pakete (ohne venv, system-weit)
#   4. InfluxDB 2 installieren, Bucket + Token anlegen
#   5. Grafana installieren, Datasource + Dashboard
#   6. Heater+ Dateien, hp_settings.json mit Token
#   7. Allsky-Modul + Overlay integrieren
#   8. Systemd service for heater_plus
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
err()  { log "ERROR: $*"; echo "$*" >&2; }

# --- Fortschritt ---
TOTAL_STEPS=8
progress_step() {
    local step="$1" desc="$2"
    echo ""
    log ">>> Step $step/$TOTAL_STEPS: $desc <<<"
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

# --- 1. Prerequisites ---
check_prereqs() {
    progress_step 1 "Check prerequisites"
    if [[ $EUID -ne 0 ]]; then
        err "Please run with sudo: sudo $0"
        exit 1
    fi
    if [[ ! -d "$ALLSKY_HOME" ]] || [[ ! -f "$ALLSKY_HOME/variables.sh" ]]; then
        err "Allsky not found at $ALLSKY_HOME"
        err "Please install Allsky manually first, then run this script again."
        exit 1
    fi
    log "Allsky found: $ALLSKY_HOME"
    log "Architecture: $ARCH ($ARCH_FOR_INFLUX)"
}

# --- 2. System packages ---
install_system_packages() {
    progress_step 2 "Install system packages"
    apt-get update || { err "apt-get update failed"; exit 1; }

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
            log "  [$n/$total] $pkg already installed"
        else
            log "  [$n/$total] Installing $pkg ..."
            apt-get install -y "$pkg" || { err "Installation of $pkg failed"; exit 1; }
        fi
    done
}

# --- 3. Enable I2C ---
I2C_WAS_ACTIVATED=0
enable_i2c() {
    progress_step 3 "Enable I2C"
    # Methode 1: raspi-config (offiziell, funktioniert auf allen Pi-OS-Versionen)
    if command -v raspi-config >/dev/null 2>&1; then
        if raspi-config nonint get_i2c 2>/dev/null; then
            if [[ -e /dev/i2c-1 ]] || [[ -e /dev/i2c-0 ]]; then
                log "[OK] I2C already enabled"
            else
                log "[OK] I2C in config – reboot needed for /dev/i2c-1 to appear"
                I2C_WAS_ACTIVATED=1
                touch /var/run/reboot-required 2>/dev/null || true
            fi
            return 0
        fi
        if raspi-config nonint do_i2c 0 2>/dev/null; then
            log "[OK] I2C enabled (raspi-config)"
            I2C_WAS_ACTIVATED=1
            touch /var/run/reboot-required 2>/dev/null || true
            return 0
        fi
    fi

    # Method 2: Manually edit config.txt
    local cfg
    for cfg in /boot/firmware/config.txt /boot/config.txt; do
        if [[ -f "$cfg" ]]; then
            if grep -q '^dtparam=i2c_arm=on' "$cfg" 2>/dev/null; then
                if [[ -e /dev/i2c-1 ]] || [[ -e /dev/i2c-0 ]]; then
                    log "[OK] I2C already enabled"
                else
                    log "[OK] I2C in config – reboot needed for /dev/i2c-1 to appear"
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
            log "[OK] I2C enabled (config.txt edited)"
            I2C_WAS_ACTIVATED=1
            touch /var/run/reboot-required 2>/dev/null || true
            return 0
        fi
    done
    warn "config.txt not found – enable I2C manually: raspi-config → Interface Options → I2C"
}

# --- 4. Python-Pakete ---
install_python_packages() {
    progress_step 4 "Install Python packages"
    local pip_extra=""
    if pip_needs_break_system; then
        pip_extra="--break-system-packages"
        log "Using pip with --break-system-packages (PEP 668)"
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
            log "  [$n/$total] $pkg already installed"
        else
            log "  [$n/$total] Installing $pkg ..."
            python3 -m pip install --quiet $pip_extra "$install_pkg" || {
                warn "pip install $pkg failed, skipping"
            }
        fi
    done

    # tcs3448 ist lokales Modul in heater_plus, wird mit kopiert
    log "[OK] tcs3448 will be installed with Heater+ files"
}

# --- 5. InfluxDB ---
install_influxdb() {
    progress_step 5 "Install InfluxDB 2"
    if is_pkg_installed influxdb2; then
        log "[OK] InfluxDB2 already installed"
    else
        log "Adding InfluxData repository ..."
        curl -sL https://repos.influxdata.com/influxdata-archive.key -o /tmp/influxdata-archive.key
        if gpg --show-keys --with-fingerprint --with-colons /tmp/influxdata-archive.key 2>/dev/null | grep -q '24C975CBA61A024EE1B631787C3D57159FC2F927\|AC10D7449F343ADCEFDDC2B6DA61C26A0585BD3B'; then
            cat /tmp/influxdata-archive.key | gpg --dearmor | tee /etc/apt/keyrings/influxdata-archive.gpg > /dev/null
            echo "deb [signed-by=/etc/apt/keyrings/influxdata-archive.gpg] https://repos.influxdata.com/debian stable main" | tee /etc/apt/sources.list.d/influxdata.list > /dev/null
        else
            err "InfluxData GPG key could not be verified"
            exit 1
        fi
        rm -f /tmp/influxdata-archive.key
        apt-get update -qq
        apt-get install -y -qq influxdb2
    fi

    systemctl enable influxdb 2>/dev/null || systemctl enable influxdb2 2>/dev/null || true
    systemctl start influxdb 2>/dev/null || systemctl start influxdb2 2>/dev/null || true
    sleep 5

    # Setup via HTTP API (influx CLI is separate, API always works)
    INFLUX_TOKEN=""
    local setup_resp
    setup_resp=$(curl -s -X POST "http://localhost:8086/api/v2/setup" \
        -H "Content-Type: application/json" \
        -d "{\"username\":\"$INFLUX_USER\",\"password\":\"$INFLUX_PASSWORD\",\"org\":\"$INFLUX_ORG\",\"bucket\":\"$INFLUX_BUCKET\"}" 2>/dev/null) || true

    if [[ -n "$setup_resp" ]] && echo "$setup_resp" | grep -q '"token"'; then
        INFLUX_TOKEN=$(echo "$setup_resp" | jq -r '.auth.token // empty')
    fi
    if [[ -z "$INFLUX_TOKEN" ]]; then
        # Already configured? Then we need to get existing token - only via influx CLI or manually
        if curl -s "http://localhost:8086/health" | grep -q "pass"; then
            warn "InfluxDB is running, setup may already be done. Copy token from Web-UI (http://localhost:8086) and paste into hp_settings.json."
        else
            warn "InfluxDB setup failed - add token manually to hp_settings.json"
        fi
    else
        export INFLUX_TOKEN
        log "[OK] InfluxDB setup complete, token obtained"
    fi
}

# --- 6. Grafana ---
install_grafana() {
    progress_step 6 "Install Grafana"
    if is_pkg_installed grafana || is_pkg_installed grafana-server; then
        log "[OK] Grafana already installed"
    else
        log "Adding Grafana repository ..."
        mkdir -p /etc/apt/keyrings
        wget -q -O - https://apt.grafana.com/gpg.key | gpg --dearmor | tee /etc/apt/keyrings/grafana.gpg > /dev/null
        echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" | tee /etc/apt/sources.list.d/grafana.list > /dev/null
        apt-get update -qq
        apt-get install -y grafana
    fi

    # Start Grafana (after apt install: daemon-reload needed)
    systemctl daemon-reload
    systemctl enable grafana-server 2>/dev/null || true
    systemctl start grafana-server 2>/dev/null || true

    # Wait until Grafana is ready (max 30 seconds)
    log "Waiting for Grafana ..."
    local grafana_ready=0
    for i in $(seq 1 30); do
        if curl -s -o /dev/null -w "%{http_code}" -u "$GRAFANA_ADMIN_USER:$GRAFANA_ADMIN_PASSWORD" "http://localhost:3000/api/health" 2>/dev/null | grep -q "200"; then
            grafana_ready=1
            break
        fi
        sleep 1
    done
    if [[ $grafana_ready -eq 0 ]]; then
        warn "Grafana not responding after 30s – set up datasource/dashboard manually later: import_grafana_dashboard.sh"
    else
        # Datasource + Dashboard
        local grafana_url="http://localhost:3000"
        local ds_uid="influxdb-heater-plus"

        # Datasource (nur wenn Token vorhanden)
        if [[ -n "$INFLUX_TOKEN" ]]; then
            log "Setting up Grafana datasource ..."
            if curl -s -u "$GRAFANA_ADMIN_USER:$GRAFANA_ADMIN_PASSWORD" "$grafana_url/api/datasources" 2>/dev/null | grep -q "$ds_uid"; then
                log "[OK] Grafana datasource already exists"
            else
                curl -s -X POST -u "$GRAFANA_ADMIN_USER:$GRAFANA_ADMIN_PASSWORD" \
                    -H "Content-Type: application/json" \
                    -d "{\"name\":\"InfluxDB Heater+\",\"type\":\"influxdb\",\"uid\":\"$ds_uid\",\"url\":\"http://localhost:8086\",\"access\":\"proxy\",\"jsonData\":{\"version\":\"Flux\",\"organization\":\"$INFLUX_ORG\"},\"secureJsonData\":{\"token\":\"$INFLUX_TOKEN\"}}" \
                    "$grafana_url/api/datasources" 2>/dev/null && log "[OK] Datasource created" || warn "Could not create Grafana datasource"
            fi
        else
            warn "InfluxDB token missing – create datasource manually (uid: influxdb-heater-plus)"
        fi

        # Dashboard importieren
        local dash_file="${SCRIPT_DIR}/grafana_dashboard_heater_plus_pro.json"
        if [[ -f "$dash_file" ]]; then
            log "Importing Grafana dashboard ..."
            if curl -s -u "$GRAFANA_ADMIN_USER:$GRAFANA_ADMIN_PASSWORD" "$grafana_url/api/search?type=dash-db" 2>/dev/null | grep -q "heater-plus-allsky-pro"; then
                log "[OK] Grafana dashboard already exists"
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
                        log "[OK] Dashboard imported"
                    else
                        warn "Grafana dashboard import failed (HTTP $code). Manual: import_grafana_dashboard.sh"
                    fi
                else
                    warn "Could not load dashboard JSON"
                fi
            fi
        else
            warn "grafana_dashboard_heater_plus_pro.json not found in $SCRIPT_DIR"
        fi
    fi
}

# --- 7. Heater+ Dateien ---
install_heater_plus_files() {
    progress_step 7 "Install Heater+ files"
    mkdir -p "$INSTALL_DIR"
    for f in heater_plus.py allsky_heaterplussettings.py tcs3448.py hp_settings.json grafana_dashboard_heater_plus_pro.json import_grafana_dashboard.sh; do
        if [[ -f "$SCRIPT_DIR/$f" ]]; then
            cp "$SCRIPT_DIR/$f" "$INSTALL_DIR/"
            log "[OK] $f copied"
        else
            warn "$f not found in $SCRIPT_DIR"
        fi
    done

    # hp_settings.json: Token und Pfade setzen
    local hp_settings="$INSTALL_DIR/hp_settings.json"
    if [[ -f "$hp_settings" ]] && [[ -n "$INFLUX_TOKEN" ]]; then
        if command -v jq >/dev/null 2>&1; then
            jq --arg t "$INFLUX_TOKEN" '.token_db = $t' "$hp_settings" > "${hp_settings}.tmp"
            mv "${hp_settings}.tmp" "$hp_settings"
        fi
        # filename_json auf Allsky extra zeigen
        local extra_json="${ALLSKY_CONFIG:-/home/pi/allsky/config}/overlay/extra/heater_plus.json"
        if command -v jq >/dev/null 2>&1; then
            jq --arg p "$extra_json" '.filename_json = $p' "$hp_settings" > "${hp_settings}.tmp"
            mv "${hp_settings}.tmp" "$hp_settings"
        fi
    fi

    chown -R pi:pi "$INSTALL_DIR" 2>/dev/null || true
}

# --- 8. Allsky-Modul + Overlay ---
install_allsky_integration() {
    progress_step 8 "Allsky Heater+ module + overlay"
    export ALLSKY_HOME ALLSKY_CONFIG

    if [[ -f "$ALLSKY_HOME/variables.sh" ]]; then
        # shellcheck source=/dev/null
        source "$ALLSKY_HOME/variables.sh"
    fi

    local MODULES_DIR="${ALLSKY_MODULE_LOCATION:-/opt/allsky}/modules"
    local OVERLAY_EXTRA="${ALLSKY_CONFIG}/overlay/extra"
    local OVERLAY_TEMPLATES="${ALLSKY_CONFIG}/overlay/myTemplates"

    mkdir -p "$MODULES_DIR" "$OVERLAY_EXTRA" "$OVERLAY_TEMPLATES"

    # Modul
    if [[ -f "$SCRIPT_DIR/allsky_heaterplussettings.py" ]]; then
        cp "$SCRIPT_DIR/allsky_heaterplussettings.py" "$MODULES_DIR/"
        [[ -w "$MODULES_DIR" ]] || sudo chown pi:pi "$MODULES_DIR" 2>/dev/null || true
        log "[OK] Allsky module copied"
    fi

    # Fallback extra/heater_plus.json
    if [[ -f "$SCRIPT_DIR/heater_plus.json" ]]; then
        cp "$SCRIPT_DIR/heater_plus.json" "$OVERLAY_EXTRA/heater_plus.json"
    elif [[ -f "$OVERLAY_EXTRA/heater_plus.json" ]]; then
        log "[OK] heater_plus.json already exists"
    else
        echo '{"HP_TEMP_DOME":{"value":"--","expires":60}}' > "$OVERLAY_EXTRA/heater_plus.json"
    fi

    # Overlay-Template: optional aus allsky_config (Nutzer konfiguriert ggf. in Allsky-GUI)

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
        log "[OK] Heater+ added to postprocessing_periodic.json"
    else
        log "[OK] Heater+ already in postprocessing_periodic.json"
    fi

}

# --- 9. Systemd-Service ---
install_systemd_service() {
    echo ""
    log ">>> Systemd service for heater_plus <<<"
    local svc="/etc/systemd/system/heater_plus.service"
    if [[ -f "$svc" ]]; then
        log "[OK] heater_plus.service already exists"
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
        log "[OK] heater_plus.service created and enabled"
    fi
    # Do not auto-start - user starts via Allsky GUI (control_script_enabled)
}

# --- 10. Summary ---
print_summary() {
    log ""
    log "=== Installation complete ==="
    log ""
    if [[ "${I2C_WAS_ACTIVATED:-0}" -eq 1 ]]; then
        log "*** REBOOT REQUIRED ***  I2C was enabled and takes effect after reboot!"
        log "    Command:  sudo reboot"
        log ""
    fi
    log "Grafana:        http://$(hostname -I | awk '{print $1}'):3000  (admin/admin - change password!)"
    log "Allsky WebUI:   http://$(hostname -I | awk '{print $1}')/allsky"
    log "InfluxDB:       http://localhost:8086"
    log ""
    log "Next steps:"
    [[ "${I2C_WAS_ACTIVATED:-0}" -eq 1 ]] && log "  1. sudo reboot  (required for I2C)"
    log "  2. In Allsky GUI: Module Manager -> Periodic Jobs -> enable Heater+ Settings"
    log "  3. Start Heater+ control script via checkbox 'Heater+ Control-Script enabled'"
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
