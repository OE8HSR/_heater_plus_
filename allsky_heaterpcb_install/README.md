# Allsky + Heater-PCB Installationspaket

## Inhalt

| Datei | Beschreibung |
|-------|--------------|
| heater_plus.py | Heater-PCB Steuerung |
| allsky_heaterplussettings.py | Allsky-Modul |
| tcs3448.py | TCS3448 Sensor-Treiber |
| hp_settings.json | Vollständige Vorlage für `~/heater_plus/hp_settings.json` (**im Repo**; `token_db` = `REPLACE_WITH_INFLUX_TOKEN`) |
| heater_plus.json | Overlay-Fallback |
| install_allsky_heaterpcb.sh | Haupt-Installationsscript |
| sync_dev_to_package.sh | **`~/heater_plus` → Paket** (vor `git push`) |
| sync_heater_plus_runtime.sh | **Paket → `~/heater_plus`** (nach `git pull`) |
| heater_plus_runtime_sync.inc.sh | Gemeinsame Logik (von Install + Sync gesourced) |
| ENTWICKLUNG.md | Paket ↔ Laufzeit, Symlinks, Workflow |
| grafana_dashboard_heater_plus_pro.json | Grafana-Dashboard |
| import_grafana_dashboard.sh | Grafana-Dashboard manuell importieren (falls nötig) |
| README.md | Diese Anleitung |

## Installation

### 1. Ordner auf den Pi kopieren
```bash
scp -r allsky_heaterpcb_install pi@<PI-IP>:/home/pi/
```

### 2. Allsky zuerst installieren
```bash
sudo apt update
sudo apt install -y git
cd ~
git clone --depth=1 --recursive https://github.com/AllskyTeam/allsky.git
cd allsky
sudo ./install.sh
```

### 3. Heater-PCB Installation
```bash
cd ~/allsky_heaterpcb_install
chmod +x install_allsky_heaterpcb.sh
sudo ./install_allsky_heaterpcb.sh
```
Optional ohne Influx/Grafana: `sudo ./install_allsky_heaterpcb.sh --minimal` oder `--help` für Optionen.

### 4. Reboot (falls I2C aktiviert)
```bash
sudo reboot
```

### 5. Allsky-GUI: Heater+ Settings aktivieren
Module Manager → Periodic Jobs → Heater+ Settings → aktivieren → „Heater+ Control-Script aktiv“ setzen

**Overlay:** In den Allsky-Einstellungen Tag- **und** Nacht-Overlay auf die Heater+-Vorlage stellen (z. B. `overlay1-RPi_HQ-4056x3040-both.json` unter *myTemplates*), sonst bleiben `${HP_*}`-Platzhalter leer.

### 5b. Nach Code-Update ohne Voll-Install
```bash
cd ~/allsky_heaterpcb_install   # oder Pfad zum Klon
./sync_heater_plus_runtime.sh
```

### 6. Grafana-Dashboard (falls nicht automatisch importiert)
```bash
cd ~/heater_plus
./import_grafana_dashboard.sh
```

## URLs
- Allsky: http://<PI-IP>/allsky
- Grafana: http://<PI-IP>:3000 (admin/admin – Passwort ändern!)
