#!/usr/bin/env python3
"""Build the Heater+ Allsky complete dashboard and write valid JSON."""

import json

DS = {"type": "influxdb", "uid": "${datasource}"}

def stat_panel(panel_id, x, title, unit, query):
    return {
        "datasource": DS,
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "thresholds"},
                "mappings": [],
                "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": None}]},
                "unit": unit,
            },
            "overrides": [],
        },
        "gridPos": {"h": 2, "w": 3, "x": x, "y": 0},
        "id": panel_id,
        "options": {
            "colorMode": "thresholds",
            "graphMode": "none",
            "justifyMode": "auto",
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "value_and_name",
        },
        "targets": [{"datasource": DS, "query": query, "refId": "A"}],
        "title": title,
        "type": "stat",
    }

def ts_field_defaults(unit="short"):
    return {
        "color": {"mode": "palette-classic"},
        "custom": {
            "axisCenteredZero": False,
            "axisColorMode": "text",
            "axisLabel": "",
            "axisPlacement": "auto",
            "drawStyle": "line",
            "fillOpacity": 10,
            "gradientMode": "none",
            "hideFrom": {"legend": False, "tooltip": False, "viz": False},
            "lineInterpolation": "smooth",
            "lineWidth": 1,
            "pointSize": 5,
            "scaleDistribution": {"type": "linear"},
            "showPoints": "auto",
            "spanNulls": False,
            "stacking": {"group": "A", "mode": "none"},
            "thresholdsStyle": {"mode": "off"},
            "unit": unit,
        },
        "mappings": [],
        "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": None}]},
    }

def timeseries_panel(panel_id, x, y, w, h, title, query, overrides, unit="short"):
    return {
        "datasource": DS,
        "fieldConfig": {
            "defaults": ts_field_defaults(unit),
            "overrides": overrides,
        },
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "id": panel_id,
        "options": {
            "legend": {"calcs": ["lastNotNull"], "displayMode": "list", "placement": "bottom", "showLegend": True},
            "tooltip": {"mode": "single", "sort": "none"},
        },
        "targets": [{"datasource": DS, "query": query, "refId": "A"}],
        "title": title,
        "type": "timeseries",
    }

def override(regex, display_name, unit="short"):
    return {
        "matcher": {"id": "byRegex", "options": regex},
        "properties": [
            {"id": "displayName", "value": display_name},
            {"id": "unit", "value": unit},
        ],
    }

# Stat-Panels
stats = [
    (10, "Dome Temp", "celsius", 'from(bucket: "heater_plus") |> range(start: -5m) |> filter(fn: (r) => r._measurement == "sensor_data" and r.sensor == "BME280" and r._field == "bme_temp_dome") |> last() |> yield(name: "last")'),
    (11, "Taupunkt", "celsius", 'from(bucket: "heater_plus") |> range(start: -5m) |> filter(fn: (r) => r._measurement == "sensor_data" and r.sensor == "BME280" and r._field == "bme_dewp_dome") |> last() |> yield(name: "last")'),
    (12, "Heater %", "percent", 'from(bucket: "heater_plus") |> range(start: -5m) |> filter(fn: (r) => r._measurement == "sensor_data" and r.sensor == "PWM" and r._field == "heater_duty") |> last() |> yield(name: "last")'),
    (13, "Lux", "lux", 'from(bucket: "heater_plus") |> range(start: -5m) |> filter(fn: (r) => r._measurement == "sensor_data" and r.sensor == "TSL2591" and r._field == "tsl_lux") |> last() |> yield(name: "last")'),
    (14, "Spannung", "volt", 'from(bucket: "heater_plus") |> range(start: -5m) |> filter(fn: (r) => r._measurement == "sensor_data" and r.sensor == "INA226" and r._field == "ina_vbus") |> last() |> yield(name: "last")'),
    (15, "Pi CPU", "celsius", 'from(bucket: "heater_plus") |> range(start: -5m) |> filter(fn: (r) => r._measurement == "rpi_status" and r._field == "pi_cpu_temp") |> last() |> yield(name: "last")'),
    (16, "Disk %", "percent", 'from(bucket: "heater_plus") |> range(start: -5m) |> filter(fn: (r) => r._measurement == "rpi_status" and r._field == "pi_disk_percent") |> last() |> yield(name: "last")'),
    (17, "Blitz", "short", 'from(bucket: "heater_plus") |> range(start: -5m) |> filter(fn: (r) => r._measurement == "sensor_data" and r.sensor == "AS3935" and r._field == "as_lightning_count") |> last() |> yield(name: "last")'),
]

panels = [stat_panel(pid, i * 3, title, unit, q) for i, (pid, title, unit, q) in enumerate(stats)]

# Klima Dome & Heizung
q_klima = (
    'from(bucket: "heater_plus") |> range(start: v.timeRangeStart, stop: v.timeRangeStop) '
    '|> filter(fn: (r) => r._measurement == "sensor_data" and ((r.sensor == "BME280" and (r._field == "bme_temp_dome" or r._field == "bme_dewp_dome" or r._field == "bme_hum_dome" or r._field == "heaterplus_settemp")) or (r.sensor == "PWM" and (r._field == "heater_duty" or r._field == "fan_duty")))) '
    "|> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false) |> yield(name: \"mean\")"
)
panels.append(timeseries_panel(20, 0, 2, 12, 8, "Klima Dome & Heizung", q_klima, [
    override(".*bme_temp_dome.*", "Dome Temp", "celsius"),
    override(".*bme_dewp_dome.*", "Taupunkt", "celsius"),
    override(".*heaterplus_settemp.*", "Soll", "celsius"),
    override(".*bme_hum_dome.*", "Luftfeuchte", "percent"),
    override(".*heater_duty.*", "Heater %", "percent"),
    override(".*fan_duty.*", "Fan %", "percent"),
], "celsius"))

# Heizung & Strom
q_heizung = (
    'from(bucket: "heater_plus") |> range(start: v.timeRangeStart, stop: v.timeRangeStop) '
    '|> filter(fn: (r) => r._measurement == "sensor_data" and ((r.sensor == "PWM" and (r._field == "heater_duty" or r._field == "fan_duty")) or (r.sensor == "INA226" and (r._field == "ina_vbus" or r._field == "ina_current" or r._field == "ina_power"))) '
    "|> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false) |> yield(name: \"mean\")"
)
panels.append(timeseries_panel(21, 12, 2, 12, 8, "Heizung & Strom", q_heizung, [
    override(".*heater_duty.*", "Heater %", "percent"),
    override(".*fan_duty.*", "Fan %", "percent"),
    override(".*ina_vbus.*", "Spannung", "volt"),
    override(".*ina_current.*", "Strom", "milliamps"),
    override(".*ina_power.*", "Leistung", "milliwatts"),
], "percent"))

# Helligkeit TSL2591
q_tsl = (
    'from(bucket: "heater_plus") |> range(start: v.timeRangeStart, stop: v.timeRangeStop) '
    '|> filter(fn: (r) => r._measurement == "sensor_data" and r.sensor == "TSL2591" and (r._field == "tsl_lux" or r._field == "tsl_visible" or r._field == "tsl_infrared" or r._field == "tsl_fullspectrum")) '
    "|> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false) |> yield(name: \"mean\")"
)
panels.append(timeseries_panel(22, 0, 10, 12, 8, "Helligkeit (TSL2591)", q_tsl, [
    override(".*tsl_lux.*", "Lux", "lux"),
    override(".*tsl_visible.*", "Sichtbar", "short"),
    override(".*tsl_infrared.*", "IR", "short"),
    override(".*tsl_fullspectrum.*", "Full", "short"),
], "lux"))

# Raspberry Pi
q_pi = (
    'from(bucket: "heater_plus") |> range(start: v.timeRangeStart, stop: v.timeRangeStop) '
    '|> filter(fn: (r) => r._measurement == "rpi_status") '
    "|> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false) |> yield(name: \"mean\")"
)
panels.append(timeseries_panel(23, 12, 10, 12, 8, "Raspberry Pi", q_pi, [
    override(".*pi_cpu_temp.*", "CPU Temp", "celsius"),
    override(".*pi_cpu_usage.*", "CPU %", "percent"),
    override(".*pi_disk_percent.*", "Disk %", "percent"),
    override(".*pi_mem_percent.*", "Mem %", "percent"),
], "percent"))

# Dome vs. Housing
q_dome = (
    'from(bucket: "heater_plus") |> range(start: v.timeRangeStart, stop: v.timeRangeStop) '
    '|> filter(fn: (r) => r._measurement == "sensor_data" and r.sensor == "BME280" and (r._field == "bme_temp_dome" or r._field == "bme_temp_housing" or r._field == "bme_pres_dome" or r._field == "bme_pres_housing")) '
    "|> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false) |> yield(name: \"mean\")"
)
panels.append(timeseries_panel(24, 0, 18, 12, 8, "Dome vs. Housing", q_dome, [
    override(".*bme_temp_dome.*", "Temp Dome", "celsius"),
    override(".*bme_temp_housing.*", "Temp Housing", "celsius"),
    override(".*bme_pres_dome.*", "Druck Dome", "hpa"),
    override(".*bme_pres_housing.*", "Druck Housing", "hpa"),
], "celsius"))

# TCS3448 VIS & NIR
q_vis = (
    'from(bucket: "heater_plus") |> range(start: v.timeRangeStart, stop: v.timeRangeStop) '
    '|> filter(fn: (r) => r._measurement == "sensor_data" and r.sensor == "TCS3448" and (r._field == "tcs_vis" or r._field == "tcs_vis2" or r._field == "tcs_vis3" or r._field == "tcs_nir")) '
    "|> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false) |> yield(name: \"mean\")"
)
panels.append(timeseries_panel(25, 12, 18, 12, 8, "TCS3448 VIS & NIR", q_vis, [
    override(".*tcs_vis3.*", "VIS3", "short"),
    override(".*tcs_vis2.*", "VIS2", "short"),
    override(".*tcs_vis.*", "VIS", "short"),
    override(".*tcs_nir.*", "NIR", "short"),
]))

# TCS3448 F1-F8 Spektrum
q_f18 = (
    'from(bucket: "heater_plus") |> range(start: v.timeRangeStart, stop: v.timeRangeStop) '
    '|> filter(fn: (r) => r._measurement == "sensor_data" and r.sensor == "TCS3448" and (r._field == "tcs_f1" or r._field == "tcs_f2" or r._field == "tcs_f3" or r._field == "tcs_f4" or r._field == "tcs_f5" or r._field == "tcs_f6" or r._field == "tcs_f7" or r._field == "tcs_f8")) '
    "|> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false) |> yield(name: \"mean\")"
)
panels.append(timeseries_panel(26, 0, 26, 24, 8, "TCS3448 F1-F8 Spektrum", q_f18, [
    override(".*tcs_f1.*", "F1 (407 nm)", "short"),
    override(".*tcs_f2.*", "F2 (424 nm)", "short"),
    override(".*tcs_f3.*", "F3 (473 nm)", "short"),
    override(".*tcs_f4.*", "F4 (516 nm)", "short"),
    override(".*tcs_f5.*", "F5 (546 nm)", "short"),
    override(".*tcs_f6.*", "F6 (636 nm)", "short"),
    override(".*tcs_f7.*", "F7 (687 nm)", "short"),
    override(".*tcs_f8.*", "F8 (748 nm)", "short"),
]))

dashboard = {
    "annotations": {"list": []},
    "editable": True,
    "fiscalYearStartMonth": 0,
    "graphTooltip": 0,
    "id": None,
    "links": [],
    "liveNow": False,
    "panels": panels,
    "refresh": "10s",
    "schemaVersion": 38,
    "style": "dark",
    "tags": ["heater_plus", "allsky"],
    "templating": {
        "list": [{
            "current": {},
            "hide": 0,
            "includeAll": False,
            "label": "Data source",
            "multi": False,
            "name": "datasource",
            "options": [],
            "query": "influxdb",
            "queryValue": "",
            "refresh": 1,
            "regex": "",
            "skipUrlSync": False,
            "type": "datasource",
        }],
    },
    "time": {"from": "now-6h", "to": "now"},
    "timepicker": {},
    "timezone": "browser",
    "title": "Heater+ Allsky Komplett",
    "uid": "heater-plus-allsky-complett",
    "version": 1,
    "weekStart": "",
}

out_path = "grafana_dashboard_allsky_complett.json"
with open(out_path, "w") as f:
    json.dump(dashboard, f, indent=2, ensure_ascii=False)

# Validieren
with open(out_path) as f:
    json.load(f)
print("Dashboard geschrieben:", out_path)
print("JSON ist gueltig.")
