#!/usr/bin/env python3
"""
Aktualisiert die Extra-Label-Datei für indi-allsky aus heater_plus.json.
Läuft als Daemon/Cron oder im Hintergrund; indi-allsky liest diese Datei für IMAGE_EXTRA_TEXT.

Usage:
  python3 update_indi_extra_labels.py   # einmalig
  Oder als systemd Service / cron alle 10 Sekunden
"""
import json
import sys
import time
from pathlib import Path

HEATER_JSON = Path("/home/pi/heater_plus/heater_plus.json")
OUTPUT_FILE = Path("/var/lib/indi-allsky/heater_plus_labels.txt")

def read_and_write():
    try:
        with open(HEATER_JSON) as f:
            d = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        return False

    def val(key, default="--"):
        entry = d.get(key, {})
        if isinstance(entry, dict):
            return entry.get("value", default)
        return default

    lines = [
        "# xy:15,-180",
        "# color:0,200,200",
        f"Dome {val('HP_temperature_dome')}°C  DP {val('HP_dewpoint_dome')}°C  Hum {val('HP_humidity_dome')}%",
        f"Heater {val('HP_heater_duty')}%  Fan {val('HP_fan_duty')}%",
        f"Lux {val('HP_light_lux')}  {val('HP_ina_vbus')}V {val('HP_ina_power')}mW",
    ]

    try:
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_FILE, "w") as f:
            f.write("\n".join(lines) + "\n")
        return True
    except PermissionError:
        return False

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "daemon":
        while True:
            read_and_write()
            time.sleep(10)
    else:
        ok = read_and_write()
        sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
