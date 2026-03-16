#!/bin/bash
#
# Heater+ Update – holt die neueste Version von GitHub
# ===================================================
# Nur für bestehende Installationen. Änderungen an hp_settings.json
# können überschrieben werden – vorher ggf. sichern.
#
set -e

INSTALL_DIR="/home/pi/heater_plus"

if [[ ! -d "$INSTALL_DIR/.git" ]]; then
    echo "Keine Git-Installation gefunden. Nutze zuerst den Install-Einzeiler:"
    echo "  curl -sSL https://raw.githubusercontent.com/DEIN_USERNAME/heater_plus/main/install.sh | bash"
    exit 1
fi

echo ">>> Heater+ Update"
cd "$INSTALL_DIR"
git pull
echo "[OK] Aktualisiert. Starte heater_plus neu, falls es als Service läuft: sudo systemctl restart heater_plus"
