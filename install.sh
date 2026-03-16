#!/bin/bash
#
# Heater+ Minimal-Installation – per Link ausführbar
# =================================================
# Einzeiler:
#   curl -sSL https://raw.githubusercontent.com/DEIN_USERNAME/heater_plus/main/install.sh | bash
#
# Oder mit wget:
#   wget -qO- https://raw.githubusercontent.com/DEIN_USERNAME/heater_plus/main/install.sh | bash
#
# Vor dem Hochladen: DEIN_USERNAME durch deinen GitHub-Benutzernamen ersetzen!
#
set -e

REPO_URL="https://github.com/DEIN_USERNAME/heater_plus"
INSTALL_DIR="/home/pi/heater_plus"

echo ">>> Heater+ Installation (Sensorboard + Steuerscript)"
echo ">>> Quelle: $REPO_URL"
echo ""

# Git vorhanden?
if ! command -v git &>/dev/null; then
    echo "Git wird installiert..."
    sudo apt-get update -qq && sudo apt-get install -y git
fi

# Repo klonen oder aktualisieren
if [[ -d "$INSTALL_DIR/.git" ]]; then
    echo "Bestehende Installation gefunden, aktualisiere..."
    cd "$INSTALL_DIR"
    git pull
    echo "[OK] Aktualisiert. Starte heater_plus ggf. neu."
    exit 0
fi

echo "Lade Heater+ herunter..."
rm -rf "$INSTALL_DIR"
git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
cd "$INSTALL_DIR"

# Installationsscript ausführen (nur bei Neuinstallation)
if [[ -f "$INSTALL_DIR/install_minimal.sh" ]]; then
    chmod +x "$INSTALL_DIR/install_minimal.sh"
    chmod +x "$INSTALL_DIR/update.sh" 2>/dev/null || true
    sudo "$INSTALL_DIR/install_minimal.sh"
else
    echo "Fehler: install_minimal.sh nicht gefunden."
    exit 1
fi
