# Heater+ Allsky PCB

Steuerung und Sensoren für die Heater-PCB (BME280, TSL2591, TCS3448, INA226, AS3935) mit Allsky-Integration.

## Schnellstart (Tester)

**Installation (ein Befehl):**
```bash
curl -sSL https://raw.githubusercontent.com/DEIN_USERNAME/heater_plus/main/install.sh | bash
```

**Update (wenn du Änderungen gepusht hast):**
```bash
cd ~/heater_plus && ./update.sh
```

Oder erneut den Install-Befehl ausführen – er erkennt bestehende Installationen und macht ein `git pull`.

## Nach der Installation

```bash
# Falls I2C aktiviert wurde:
sudo reboot

# Steuerscript starten
cd ~/heater_plus && python3 heater_plus.py
```