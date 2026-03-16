# Logische Überprüfung: install_allsky_heaterpcb.sh

## 1. Voraussetzungen
- **Root/sudo**: Prüfung `EUID -ne 0` korrekt.
- **Allsky**: Prüft `$ALLSKY_HOME/variables.sh`. Standard-Pfad `/home/pi/allsky`. Bei anderer Installation: `ALLSKY_HOME=/pfad sudo ./install_allsky_heaterpcb.sh`.

## 2. System-Pakete
- `python3-pip`, `python3-venv`, `i2c-tools`, `python3-dev`, `libatlas-base-dev`, `curl`, `wget`, `gpg`, `jq`.
- **Idempotenz**: `dpkg -l` prüft vor install.
- **Hinweis**: `RPi.bmp280` entfernt (nicht in heater_plus imports).

## 3. I2C
- Pfad: `/boot/firmware/config.txt` (Bookworm) oder `/boot/config.txt`.
- **Idempotenz**: `grep -q '^dtparam=i2c_arm=on'` vor Änderung.
- **Reboot**: Script setzt nicht automatisch reboot, erwähnt es in der Zusammenfassung.

## 4. Python-Pakete (pip, PEP 668)
- **Problem PEP 668**: Ab Bookworm verhindert `EXTERNALLY-MANAGED` systemweite pip-Installs.
- **Lösung**: `pip_needs_break_system()` prüft ob Datei existiert; bei Bedarf `--break-system-packages`.
- **Glob**: `for f in /usr/lib/python3.*/EXTERNALLY-MANAGED` – unter Bookworm/Bullseye mit Python 3.11/3.13 ok.
- **Pakete**: gpiozero, adafruit-blinka, adafruit-circuitpython-bme280, adafruit-circuitpython-tsl2591, pi-ina226, simple-pid, influxdb-client, RPi.AS3935.
- **tcs3448**: Lokales Modul, wird mit Heater+-Dateien kopiert.
- **Idempotenz**: `python3 -c "import modul"` vor pip install.
- **Fehlertoleranz**: Bei fehlgeschlagenem pip install nur Warnung, kein Abbruch.

## 5. InfluxDB
- **Repo**: InfluxData apt repo (armhf + arm64 unterstützt).
- **Service**: `influxdb` oder `influxdb2` – beide getestet.
- **Setup**: HTTP-API `POST /api/v2/setup` statt CLI (influx CLI nicht im Paket enthalten).
- **Token**: Aus API-Response `auth.token` mittels jq.
- **Fallback**: Wenn Setup schon erfolgt war, gibt API 409/Error – Nutzer muss Token aus Web-UI holen.
- **Idempotenz**: API gibt Fehler wenn bereits konfiguriert; Script fährt fort.

## 6. Grafana
- **Repo**: Offizielles Grafana APT-Repository.
- **Service**: grafana-server.
- **Datasource**: API mit uid `influxdb-heater-plus` für Konsistenz.
- **Dashboard**: JSON-Import; Datasource-Variable `${datasource}` wählt InfluxDB.
- **Hinweis**: Standard admin/admin – Nutzer sollte Passwort ändern.
- **Idempotenz**: Prüft vorhandene Datasource/Dashboard vor Erstellung.

## 7. Heater+ Dateien
- **Kopierte Dateien**: heater_plus.py, allsky_heaterplussettings.py, tcs3448.py, hp_settings.json.
- **hp_settings**: jq setzt `token_db` und `filename_json`. Bestehende Keys bleiben erhalten.
- **Berechtigung**: `chown pi:pi` für Nutzer-Zugriff.
- **Hinweis**: `ina226_address` etc. sollten in hp_settings.json stehen (bereits vorhanden).

## 8. Allsky-Integration
- **Pfade**: Nutzt `ALLSKY_MODULE_LOCATION`, `ALLSKY_CONFIG` aus variables.sh.
- **Modul**: Kopiert nach `/opt/allsky/modules/`.
- **extra/heater_plus.json**: Fallback falls nicht vorhanden; sonst heater_plus.json aus Repo.
- **postprocessing_periodic.json**: Fügt Heater+ Eintrag hinzu falls fehlend.
- **install_allsky_module.sh**: Wird zusätzlich ausgeführt für vollständige Modul-Config.
- **Overlay**: Kein automatisches Overlay-Template (Nutzer konfiguriert in Allsky-GUI).

## 9. Systemd
- **Service**: heater_plus.service, User=pi.
- **WantedBy**: multi-user.target.
- **Nicht autostart**: Nutzer startet über Allsky-GUI (control_script_enabled).
- **Idempotenz**: Überspringt wenn Service bereits existiert.

## 10. Bekannte Einschränkungen / Risiken

| Thema | Risiko | Mitigation |
|-------|--------|------------|
| InfluxDB bereits konfiguriert | Setup-API schlägt fehl | Token manuell aus Web-UI holen |
| Grafana erstes Start | admin/admin bekannt | In Zusammenfassung Hinweis zum Passwortwechsel |
| 32-bit (armhf) | InfluxDB armhf im Repo | Offiziell unterstützt |
| Allsky-Pfad abweichend | ALLSKY_HOME/ALLSKY_CONFIG | Als Umgebungsvariable setzen |
| pip Paket fehlschlägt | z.B. RPi.AS3935 | Script macht weiter, nur Warnung |
| jq fehlt | hp_settings Update scheitert | jq ist in System-Paketen enthalten |

## 11. Empfohlener Testablauf
1. Frische Raspberry Pi OS Lite-Installation.
2. Allsky manuell installieren.
3. `sudo ./install_allsky_heaterpcb.sh` aus dem heater_plus-Verzeichnis.
4. Reboot falls I2C aktiviert.
5. Allsky-GUI → Module Manager → Heater+ aktivieren → Control-Script starten.
6. Grafana öffnen, Datasource prüfen, Dashboard laden.
