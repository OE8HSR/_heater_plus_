#!/bin/bash
#
# Testet ob die TCS3448-Flux-Query Daten liefert.
# Nutzt influx CLI (falls installiert) oder zeigt die Query für Grafana Explore.
#
set -e
cd "$(dirname "$0")"

echo "=== TCS3448 Flux-Query Test ==="
echo ""

# Flux-Query (wie im Dashboard)
QUERY='from(bucket: "heater_plus")
  |> range(start: -24h)
  |> filter(fn: (r) =>
    r._measurement == "sensor_data" and
    r.sensor == "TCS3448" and
    (r._field == "tcs_f1" or r._field == "tcs_f2" or r._field == "tcs_vis" or r._field == "tcs_nir")
  )
  |> limit(n: 5)'

if command -v influx &>/dev/null; then
    echo "Teste mit influx CLI..."
    echo "$QUERY" | influx query - 2>/dev/null | head -30 || echo "influx query fehlgeschlagen"
else
    echo "influx CLI nicht installiert."
fi

echo ""
echo "--- Manueller Test in Grafana ---"
echo "1. Grafana öffnen → Explore (Kompass-Icon)"
echo "2. Datasource: InfluxDB (heater_plus)"
echo "3. Query einfügen und 'Run query' klicken:"
echo ""
echo "$QUERY"
echo ""
echo "4. Wenn Daten erscheinen: Dashboard-Query ist OK, Problem liegt woanders."
echo "5. Wenn 'No data': Datasource/Bucket prüfen, oder heater_plus schreibt nicht."
echo ""
