# Heater+ Allsky PCB – Installation

Vollständige Installation von **Allsky** mit **Heater-PCB** (BME280, TSL2591, TCS3448, INA226, AS3935) auf einem frischen Raspberry Pi.

---

## Voraussetzungen

- **Raspberry Pi** mit Raspberry Pi OS (Lite oder Desktop)
- **Frische Installation** – kein Allsky, keine Vorkonfiguration nötig
- **Heater-PCB** angeschlossen (I2C, GPIO)
- Internetverbindung

---

## Übersicht

Die Installation erfolgt in zwei Schritten:

1. **Allsky** installieren (offizielles Installationsscript)
2. **Heater+** installieren (dieses Paket)

---

## Schritt 1: Raspberry Pi vorbereiten

### 1.1 System aktualisieren

```bash
sudo apt update
sudo apt full-upgrade -y
```

### 1.2 Git installieren (falls nicht vorhanden)

```bash
sudo apt install -y git
```

---

## Schritt 2: Allsky installieren

Allsky **muss vor** der Heater+-Installation installiert werden.

```bash
cd ~
git clone --depth=1 --recursive https://github.com/AllskyTeam/allsky.git
cd allsky
sudo ./install.sh
```

Das Script führt dich interaktiv durch die Installation (Kamera wählen, etc.).  
**Wichtig:** Allsky muss vollständig durchlaufen sein, bevor du fortfährst.

---

## Schritt 3: Heater+ Installationspaket herunterladen

```bash
cd ~
git clone https://github.com/OE8HSR/_heater_plus_.git
cd _heater_plus_/allsky_heaterpcb_install
```

---

## Schritt 4: Heater+ installieren

```bash
chmod +x install_allsky_heaterpcb.sh
sudo ./install_allsky_heaterpcb.sh
```

Das Script führt automatisch aus:

| Schritt | Aktion |
|---------|--------|
| 1 | Allsky prüfen |
| 2 | System-Pakete installieren, I2C aktivieren |
| 3 | Python-Pakete (BME280, TSL2591, TCS3448, INA226, AS3935, …) |
| 4 | InfluxDB 2 + Bucket + Token |
| 5 | Grafana + Datasource + Dashboard |
| 6 | Heater+ Dateien nach `~/heater_plus` |
| 7 | Allsky-Modul + Overlay-Templates |
| 8 | Systemd-Service `heater_plus.service` |

---

## Schritt 5: Reboot (falls I2C aktiviert)

Falls I2C gerade erst aktiviert wurde:

```bash
sudo reboot
```

---

## Schritt 6: Allsky-GUI konfigurieren

1. **Allsky-WebUI öffnen:** `http://DEINE-PI-IP/allsky` (oder `http://localhost/allsky`)
2. **Module Manager** → **Periodic Jobs** → **Heater+ Settings** aktivieren
3. **„Heater+ Control-Script aktiv“** setzen (damit Heater+ mit Allsky startet)
4. **Overlay Editor** → Template **„Heater_Plus“** oder das kompakte Layout wählen (RPi HQ)

---

## Schritt 7: Fertig

- **Allsky:** http://DEINE-PI-IP/allsky  
- **Grafana:** http://DEINE-PI-IP:3000 (Login: admin / admin – Passwort beim ersten Mal ändern!)  
- **Heater+** startet automatisch mit Allsky und schreibt Sensordaten ins Overlay sowie nach InfluxDB/Grafana

---

## Konfiguration (hp_settings.json)

Die Heater+-Einstellungen liegen in `~/heater_plus/hp_settings.json`.

| Parameter | Beschreibung | Standard |
|----------|--------------|----------|
| `temp_set` | Solltemperatur Dome (°C) | 15.0 |
| `enable_dewheater` | Heizung aktiv | true |
| `enable_fan` | Lüfter aktiv | false |
| `heaterpin` | GPIO Heizung | 18 |
| `fanpin` | GPIO Lüfter | 16 |

**Bearbeiten:**  
- Manuell: `nano ~/heater_plus/hp_settings.json`  
- Oder über Allsky-GUI: Module → Heater+ Settings

---

## Troubleshooting

| Problem | Lösung |
|--------|--------|
| Sensoren werden nicht gefunden | `i2cdetect -y 1` ausführen, I2C-Adressen in `hp_settings.json` anpassen |
| Allsky nicht gefunden | Allsky zuerst vollständig installieren (Schritt 2) |
| Grafana-Dashboard fehlt | `cd ~/heater_plus && ./import_grafana_dashboard.sh` |
| Heater+ startet nicht | Allsky-GUI: Heater+ Settings → Control-Script aktiv |

---

## Update

```bash
cd ~/_heater_plus_
git pull
cd allsky_heaterpcb_install
sudo ./install_allsky_heaterpcb.sh
```

Das Script ist idempotent – es kann mehrfach ausgeführt werden und überspringt bereits Erledigtes.
