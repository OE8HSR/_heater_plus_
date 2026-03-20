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

### Was ins **öffentliche Git-Repo** gehört

Nur das, was andere zum **Installieren** brauchen:

- **`README.md`**
- **`allsky_heaterpcb_install/`** (Install-Skripte, Overlay, Grafana-JSON, **`hp_settings.json`** mit Platzhalter-Token `REPLACE_WITH_INFLUX_TOKEN`, …)

**Nicht** mit pushen (stehen in **`.gitignore`**): lokale Laufzeit-Kopien im Repo-Root (`heater_plus.py`, …), **`/hp_settings.json`** im Root (falls du dort testest – kann echtes Token enthalten), Hilfs-/Analyse-Skripte (z. B. `compare_measured_vs_weather.py`, `SPEKTRUM_ANALYSE.md`). **`allsky_heaterpcb_install/hp_settings.json`** dagegen **im Repo**: nur mit **`REPLACE_WITH_INFLUX_TOKEN`** – **nie** ein echtes Token dort committen.

Nach einem früheren Commit mit solchen Dateien:  
`git rm --cached compare_measured_vs_weather.py SPEKTRUM_ANALYSE.md` (und ggf. weitere), dann committen.

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
| 6 | Heater+ nach `~/heater_plus`: Python-Skripte Symlink oder Kopie; **`hp_settings.json`** aus Paket kopieren, falls `~/heater_plus` noch keine hat |
| 7 | Allsky-Modul + Overlay-Templates + Rechte `overlay/extra` |
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
3. **„Heater+ Control-Script aktiv“** setzen (damit `heater_plus.py` läuft und `heater_plus.json` schreibt)
4. **Overlay (wichtig – sonst keine Heater+-Werte im Bild):**
   - Allsky lädt automatisch **alle** `.json`-Dateien aus `~/allsky/config/overlay/extra/` (Variable `ALLSKY_EXTRA`). Die Datei `heater_plus.json` muss dort liegen und von User **pi** beschreibbar sein (macht das Install-Skript).
   - Zusätzlich muss das **aktive Tag- und Nacht-Overlay** Felder wie `${HP_TEMP_DOME}` enthalten. Nur ein Template unter *myTemplates* reicht nicht, wenn unter **Einstellungen → Overlay** noch ein altes Layout ohne diese Felder gewählt ist.
   - **WebUI:** Einstellungen / Overlay → **Daytime overlay** und **Nighttime overlay** auf die Heater+-Vorlage stellen, z. B. `overlay1-RPi_HQ-4056x3040-both.json` (liegt nach Installation unter `overlay/myTemplates/`).
   - Alternativ im **Overlay Editor** die Felder aus *Userfelder* („HeaterPlus“) einfügen.

---

## Entwickeln in `~/heater_plus` → GitHub (Paket aktualisieren)

Viele arbeiten **in `~/heater_plus/`** (Test/Laufzeit). Die gleichen Skripte liegen im Repo unter **`allsky_heaterpcb_install/`**.

**Vor `git commit` / `git push`:**

```bash
cd ~/heater_plus/allsky_heaterpcb_install
./sync_dev_to_package.sh
```

Damit werden `heater_plus.py`, `tcs3448.py`, `allsky_heaterplussettings.py` **von der Laufzeit ins Paket** kopiert – andere Nutzer bekommen per `git pull` deine getestete Version.

Echte Kopien in `~/heater_plus` (keine Symlinks) beim Install erzwingen:

```bash
HEATER_PLUS_USE_SYMLINKS=0 sudo ./install_allsky_heaterpcb.sh
```

Details: `allsky_heaterpcb_install/ENTWICKLUNG.md`.

## Paket → Laufzeit (nach `git pull` oder Änderungen nur im Repo)

```bash
cd …/allsky_heaterpcb_install
./sync_heater_plus_runtime.sh
./sync_heater_plus_runtime.sh --with-module   # optional Allsky-Modul
```

Dann `heater_plus.py` neu starten.

**Alternative:** Repo unter `~/heater_plus` mit **Symlinks** (Standard-Install) – dann ist die Datei im Paket = Laufzeit; für „nur in `~/heater_plus` editieren“ siehe oben **`HEATER_PLUS_USE_SYMLINKS=0`**.

---

## Fehler-Log (Support)

Bei Problemen wird in **`~/heater_plus/heater_plus_errors.log`** protokolliert (Pfad in `hp_settings.json`: `error_log_path`). Diese Datei kannst du mitschicken.

---

## Schritt 7: Fertig

- **Allsky:** http://DEINE-PI-IP/allsky  
- **Grafana:** http://DEINE-PI-IP:3000 (Login: admin / admin – Passwort beim ersten Mal ändern!)  
- **Heater+** startet automatisch mit Allsky und schreibt Sensordaten ins Overlay sowie nach InfluxDB/Grafana

---

## Konfiguration (hp_settings.json)

Die Einstellungen liegen in **`~/heater_plus/hp_settings.json`**. Beim **ersten** Install legt das Script sie aus **`allsky_heaterpcb_install/hp_settings.json`** an (liegt **im Git-Repo** mit allen Schlüsseln; **`token_db`** = Platzhalter **`REPLACE_WITH_INFLUX_TOKEN`**). Tester sehen so die gleiche Struktur wie im Repo. **Echtes InfluxDB-Token** per Install-Script (wenn Setup klappt) oder manuell in `~/heater_plus/hp_settings.json` setzen.

**Wichtig:** Im **öffentlichen Repo** nur die Vorlage-Version mit Platzhalter committen – **nie** ein echtes Token in `allsky_heaterpcb_install/hp_settings.json` pushen.

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
| **DB/Overlay aktualisiert sich nicht** | `pgrep -af heater_plus` – Prozess muss laufen. `./sync_heater_plus_runtime.sh` aus `allsky_heaterpcb_install/`. In `hp_settings.json`: `enable_json` = true, `filename_json` = `…/overlay/extra/heater_plus.json` |
| **Overlay zeigt `--` / leer** | Tag-/Nacht-Overlay in der Allsky-WebUI auf Heater+-Template umstellen (siehe Schritt 6). Prüfen: `ls -la ~/allsky/config/overlay/extra/heater_plus.json` (beschreibbar für `pi`) |
| **Fehler analysieren** | `~/heater_plus/heater_plus_errors.log` ansehen und ggf. mitschicken |
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
./sync_heater_plus_runtime.sh
# bei Bedarf vollständig (Rechte, Overlay, Module):
sudo ./install_allsky_heaterpcb.sh
```

`install_allsky_heaterpcb.sh` ist idempotent. Nach eigenen Änderungen in `~/heater_plus`: vor Push **`./sync_dev_to_package.sh`**. Nach `git pull`: **`./sync_heater_plus_runtime.sh`** + ggf. Neustart von `heater_plus.py`.
