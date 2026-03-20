# heater_plus_runtime_sync.inc.sh
# Wird von install_allsky_heaterpcb.sh und sync_heater_plus_runtime.sh gesourced.
# Voraussetzung: SCRIPT_DIR und INSTALL_DIR sind gesetzt (absolute Pfade empfohlen).
#
# Symlinks: Wenn das Paket unter INSTALL_DIR liegt (z. B. ~/heater_plus/allsky_heaterpcb_install),
#           können Symlinks nach INSTALL_DIR gelegt werden (eine physische Datei).
# HEATER_PLUS_USE_SYMLINKS=0 beim Install: immer echte Kopien nach ~/heater_plus – für den
# Workflow „in ~/heater_plus editieren, vor Git: sync_dev_to_package.sh“.

heater_plus_runtime_use_symlinks() {
    [[ "${HEATER_PLUS_USE_SYMLINKS:-}" == "0" ]] && return 1
    local inst pkg
    inst=$(realpath "$INSTALL_DIR" 2>/dev/null) || return 1
    pkg=$(realpath "$SCRIPT_DIR" 2>/dev/null) || return 1
    [[ -n "$pkg" && -n "$inst" ]] || return 1
    [[ "$pkg" == "$inst" ]] || [[ "$pkg" == "$inst"/* ]]
}

# Argumente: Liste der Dateinamen nur im Paketroot, z. B. heater_plus.py tcs3448.py
heater_plus_sync_runtime_scripts() {
    mkdir -p "$INSTALL_DIR"
    local f
    for f in "$@"; do
        [[ -f "$SCRIPT_DIR/$f" ]] || {
            echo "FEHLT: $SCRIPT_DIR/$f" >&2
            return 1
        }
        if heater_plus_runtime_use_symlinks; then
            ln -sfn "$SCRIPT_DIR/$f" "$INSTALL_DIR/$f"
            chown -h pi:pi "$INSTALL_DIR/$f" 2>/dev/null || true
            if declare -F log >/dev/null 2>&1; then
                log "[OK] $f -> Symlink ins Paket (nur dort bearbeiten; ~/heater_plus zeigt darauf)"
            else
                echo "[sync] Symlink $INSTALL_DIR/$f -> $SCRIPT_DIR/$f"
            fi
        else
            cp -f "$SCRIPT_DIR/$f" "$INSTALL_DIR/"
            if declare -F log >/dev/null 2>&1; then
                log "[OK] $f nach $INSTALL_DIR kopiert (Paket und Laufzeit getrennt – nach Änderungen sync ausführen)"
            else
                echo "[sync] kopiert $f -> $INSTALL_DIR/"
            fi
        fi
    done
}
