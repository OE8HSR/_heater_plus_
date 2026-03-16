#!/bin/bash
#
# import_grafana_dashboard.sh - Heater+ Allsky Pro Dashboard manuell importieren
# Aufruf: ./import_grafana_dashboard.sh  (im heater_plus Verzeichnis)
# Bei geändertem Passwort: GRAFANA_USER=admin GRAFANA_PASS=DEIN_PASS ./import_grafana_dashboard.sh
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DASH_FILE="$SCRIPT_DIR/grafana_dashboard_heater_plus_pro.json"
GRAFANA_URL="${GRAFANA_URL:-http://localhost:3000}"
GRAFANA_USER="${GRAFANA_USER:-admin}"
GRAFANA_PASS="${GRAFANA_PASS:-admin}"

[[ -f "$DASH_FILE" ]] || { echo "Fehler: $DASH_FILE nicht gefunden."; exit 1; }
echo "Importiere Heater+ Allsky Pro Dashboard ..."
payload=$(jq -n --slurpfile d "$DASH_FILE" '{dashboard: $d[0], overwrite: true}' 2>/dev/null)
[[ -n "$payload" ]] || { echo "Fehler: JSON konnte nicht geladen werden (jq?)."; exit 1; }
resp=$(curl -s -w "\n%{http_code}" -X POST -u "$GRAFANA_USER:$GRAFANA_PASS" -H "Content-Type: application/json" -d "$payload" "$GRAFANA_URL/api/dashboards/db")
code="${resp##*$'\n'}"
if [[ "$code" == "200" ]] || [[ "$code" == "201" ]]; then
    echo "OK: Dashboard importiert."
elif [[ "$code" == "401" ]]; then
    echo "Fehler HTTP 401: Anmeldung fehlgeschlagen."
    echo "Grafana-Passwort wurde vermutlich geändert. Nutze:"
    echo "  GRAFANA_USER=admin GRAFANA_PASS=DEIN_PASSWORT ./import_grafana_dashboard.sh"
    exit 1
else
    echo "Fehler HTTP $code"
    exit 1
fi
