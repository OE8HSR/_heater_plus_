#!/usr/bin/env python3
"""
Prüft ob TCS3448-Daten in InfluxDB ankommen.
Aufruf: python3 check_influx_tcs.py [--config hp_settings.json]
"""
import json
import sys
from pathlib import Path

def main():
    cfg_path = Path("/home/pi/heater_plus/hp_settings.json")
    if "--config" in sys.argv:
        i = sys.argv.index("--config")
        if i + 1 < len(sys.argv):
            cfg_path = Path(sys.argv[i + 1])

    if not cfg_path.exists():
        print(f"Config nicht gefunden: {cfg_path}")
        sys.exit(1)

    with open(cfg_path) as f:
        cfg = json.load(f)

    url = cfg.get("url_db", "http://localhost:8086")
    token = cfg.get("token_db", "")
    org = cfg.get("org_db", "allsky")
    bucket = cfg.get("bucket_db", "heater_plus")

    if not token:
        print("token_db fehlt in hp_settings.json")
        sys.exit(1)

    try:
        from influxdb_client import InfluxDBClient
        from influxdb_client.client.query_api import QueryApi
    except ImportError:
        print("influxdb-client nicht installiert: pip3 install influxdb-client")
        sys.exit(1)

    client = InfluxDBClient(url=url, token=token, org=org)
    query_api: QueryApi = client.query_api()

    # Letzte TCS3448-Daten (24h)
    query = f'''
    from(bucket: "{bucket}")
      |> range(start: -24h)
      |> filter(fn: (r) => r._measurement == "sensor_data" and r.sensor == "TCS3448")
      |> last()
    '''
    try:
        tables = query_api.query(query)
        if not tables:
            print("Keine TCS3448-Daten in den letzten 24h gefunden.")
            print("Mögliche Ursachen:")
            print("  - sendtodb=false in hp_settings.json")
            print("  - sensor_only=true (ohne sendtodb)")
            print("  - tcs3448_address=0 (Sensor deaktiviert)")
            print("  - heater_plus.py läuft nicht oder TCS3448-Init fehlgeschlagen")
            print("  - InfluxDB nicht erreichbar:", url)
            sys.exit(1)
        for table in tables:
            for row in table.records:
                print(f"  {row.get_field()}: {row.get_value()} (Zeit: {row.get_time()})")
        print("\n[OK] TCS3448-Daten werden geschrieben.")
    except Exception as e:
        print("Fehler:", e)
        sys.exit(1)
    finally:
        client.close()

if __name__ == "__main__":
    main()
