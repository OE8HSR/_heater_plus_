"""
allsky_heaterplussettings.py

Allsky module for editing Heater+ PCB settings via Allsky GUI.
Runs as periodic job. Writes changes to hp_settings.json;
heater_plus.py auto-reloads these. Can start/stop the control script.
"""
import os
import sys
import json
import subprocess
import allsky_shared as s

# Paths (standard as in heater_plus.py)
HP_SETTINGS_PATH = "/home/pi/heater_plus/hp_settings.json"
HP_CONTROL_SCRIPT = "/home/pi/heater_plus/heater_plus.py"

# Mapping: Argument name -> (hp_settings key, type function)
_ARG_MAP = {
    "temp_set": ("temp_set", float),
    "heaterpin": ("heaterpin", int),
    "fanpin": ("fanpin", int),
    "enable_dewheater": ("enable_dewheater", lambda x: str(x).lower() in ("true", "1", "yes")),
    "enable_fan": ("enable_fan", lambda x: str(x).lower() in ("true", "1", "yes")),
    "deltacooling": ("deltacooling", float),
    "deltadewpoint": ("deltadewpoint", float),
    "settodewpoint": ("settodewpoint", lambda x: str(x).lower() in ("true", "1", "yes")),
    "pid_p": ("pid_p", float),
    "pid_i": ("pid_i", float),
    "pid_d": ("pid_d", float),
    "pid_proximity_band": ("pid_proximity_band", float),
    "sensorupdateintervall": ("sensorupdateintervall", int),
    "tslgainindex": ("tslgainindex", int),
    "tslintmindex": ("tslintmindex", int),
    "tsl_autogain": ("tsl_autogain", lambda x: str(x).lower() in ("true", "1", "yes")),
    "tcs_autogain": ("tcs_autogain", lambda x: str(x).lower() in ("true", "1", "yes")),
    "tsl_high_threshold": ("tsl_high_threshold", int),
    "tsl_low_threshold": ("tsl_low_threshold", int),
    "tcs_high_threshold": ("tcs_high_threshold", int),
    "tcs_low_threshold": ("tcs_low_threshold", int),
    "temp_max_dome": ("temp_max_dome", float),
    "enable_json": ("enable_json", lambda x: str(x).lower() in ("true", "1", "yes")),
    "sea_level_pressure": ("sea_level_pressure", float),
    "heater_power_check": ("heater_power_check", lambda x: str(x).lower() in ("true", "1", "yes")),
    "heater_duty_min_for_check": ("heater_duty_min_for_check", float),
    "sensor_only": ("sensor_only", lambda x: str(x).lower() in ("true", "1", "yes")),
    "bme280_dome_address": ("bme280_dome_address", int),
    "bme280_housing_address": ("bme280_housing_address", int),
    "tsl2591_address": ("tsl2591_address", int),
    "as3935_adress": ("as3935_adress", int),
    "ina226_address": ("ina226_address", int),
    "tcs3448_address": ("tcs3448_address", int),
}

# metaData must be JSON-compatible (true/false lowercase, no Python True/False)
metaData = {
    "name": "Heater+ Settings",
    "description": "Edit Heater+ PCB settings via Allsky GUI. Controls start/stop of heater_plus.py.",
    "module": "allsky_heaterplussettings",
    "events": ["periodic"],
    "arguments": {
        "temp_set": 20,
        "heaterpin": 18,
        "fanpin": 16,
        "enable_dewheater": "true",
        "enable_fan": "true",
        "deltacooling": 2,
        "deltadewpoint": 4,
        "settodewpoint": "false",
        "pid_p": 15,
        "pid_i": 0.3,
        "pid_d": 0,
        "pid_proximity_band": 0.5,
        "sensorupdateintervall": 2,
        "tslgainindex": 0,
        "tslintmindex": 0,
        "tsl_autogain": "true",
        "tcs_autogain": "true",
        "tsl_high_threshold": 40000,
        "tsl_low_threshold": 1000,
        "tcs_high_threshold": 17500,
        "tcs_low_threshold": 2000,
        "temp_max_dome": 0,
        "enable_json": "true",
        "sea_level_pressure": 1013.25,
        "heater_power_check": "true",
        "heater_duty_min_for_check": 20,
        "sensor_only": "false",
        "control_script_enabled": "true",
        "bme280_dome_address": 119,
        "bme280_housing_address": 118,
        "tsl2591_address": 41,
        "as3935_adress": 3,
        "ina226_address": 64,
        "tcs3448_address": 89
    },
    "argumentdetails": {
        "temp_set": {
            "required": "true",
            "tab": "Heater / Fan",
            "description": "Setpoint temperature (°C)",
            "help": "Target temperature for the heater",
            "type": {"fieldtype": "spinner", "min": -20, "max": 80, "step": 0.5}
        },
        "heaterpin": {
            "required": "true",
            "tab": "Heater / Fan",
            "description": "Heater GPIO (BCM)",
            "help": "BCM pin number for heater (0=off)",
            "type": {"fieldtype": "spinner", "min": 0, "max": 27, "step": 1}
        },
        "fanpin": {
            "required": "true",
            "tab": "Heater / Fan",
            "description": "Fan GPIO (BCM)",
            "help": "BCM pin number for fan (0=off)",
            "type": {"fieldtype": "spinner", "min": 0, "max": 27, "step": 1}
        },
        "enable_dewheater": {
            "required": "false",
            "tab": "Heater / Fan",
            "description": "Heater enabled",
            "help": "Enable or disable dew heater",
            "type": {"fieldtype": "checkbox"}
        },
        "enable_fan": {
            "required": "false",
            "tab": "Heater / Fan",
            "description": "Fan enabled",
            "help": "Enable or disable fan",
            "type": {"fieldtype": "checkbox"}
        },
        "deltacooling": {
            "required": "false",
            "tab": "Heater / Fan",
            "description": "Cooling delta (°C)",
            "help": "Threshold for fan cooling",
            "type": {"fieldtype": "spinner", "min": 0, "max": 10, "step": 0.5}
        },
        "deltadewpoint": {
            "required": "false",
            "tab": "Heater / Fan",
            "description": "Dewpoint delta (°C)",
            "help": "Offset for dewpoint control",
            "type": {"fieldtype": "spinner", "min": 0, "max": 20, "step": 0.5}
        },
        "settodewpoint": {
            "required": "false",
            "tab": "Heater / Fan",
            "description": "Regulate to dewpoint",
            "help": "Setpoint = dewpoint instead of fixed value",
            "type": {"fieldtype": "checkbox"}
        },
        "pid_p": {
            "required": "false",
            "tab": "PID",
            "description": "PID P",
            "help": "Proportional term of heater control",
            "type": {"fieldtype": "spinner", "min": 0, "max": 100, "step": 0.5}
        },
        "pid_i": {
            "required": "false",
            "tab": "PID",
            "description": "PID I",
            "help": "Integral term",
            "type": {"fieldtype": "spinner", "min": 0, "max": 5, "step": 0.1}
        },
        "pid_d": {
            "required": "false",
            "tab": "PID",
            "description": "PID D",
            "help": "Derivative term. 2–5 reduces oscillation around setpoint (0 may cause strong swing)",
            "type": {"fieldtype": "spinner", "min": 0, "max": 50, "step": 0.1}
        },
        "pid_proximity_band": {
            "required": "false",
            "tab": "PID",
            "description": "Proximity zone (°C)",
            "help": "Reduce heater when closer than this to setpoint. 0.5 reduces overshoot. 0=off",
            "type": {"fieldtype": "spinner", "min": 0, "max": 2, "step": 0.1}
        },
        "sensorupdateintervall": {
            "required": "false",
            "tab": "Sensors",
            "description": "Sensor update (s)",
            "help": "Sensor update interval in seconds",
            "type": {"fieldtype": "spinner", "min": 1, "max": 60, "step": 1}
        },
        "tslgainindex": {
            "required": "false",
            "tab": "TSL2591",
            "description": "TSL Gain index",
            "help": "TSL2591 gain stage (0=LOW, 1=MED, 2=HIGH, 3=MAX)",
            "type": {"fieldtype": "spinner", "min": 0, "max": 3, "step": 1}
        },
        "tslintmindex": {
            "required": "false",
            "tab": "TSL2591",
            "description": "TSL integration index",
            "help": "TSL2591 integration time index (0=100ms … 5=600ms)",
            "type": {"fieldtype": "spinner", "min": 0, "max": 5, "step": 1}
        },
        "tsl_autogain": {
            "required": "false",
            "tab": "TSL2591",
            "description": "TSL autogain",
            "help": "Automatic TSL2591 gain adjustment",
            "type": {"fieldtype": "checkbox"}
        },
        "tsl_high_threshold": {
            "required": "false",
            "tab": "TSL2591",
            "description": "TSL high threshold",
            "help": "Upper limit for autogain (reduce)",
            "type": {"fieldtype": "spinner", "min": 0, "max": 65535, "step": 1000}
        },
        "tsl_low_threshold": {
            "required": "false",
            "tab": "TSL2591",
            "description": "TSL low threshold",
            "help": "Lower limit for autogain (increase)",
            "type": {"fieldtype": "spinner", "min": 0, "max": 65535, "step": 100}
        },
        "tcs_autogain": {
            "required": "false",
            "tab": "TCS3448",
            "description": "TCS autogain",
            "help": "Automatic TCS3448 gain adjustment",
            "type": {"fieldtype": "checkbox"}
        },
        "tcs_high_threshold": {
            "required": "false",
            "tab": "TCS3448",
            "description": "TCS high threshold",
            "help": "Upper limit for autogain",
            "type": {"fieldtype": "spinner", "min": 0, "max": 65535, "step": 500}
        },
        "tcs_low_threshold": {
            "required": "false",
            "tab": "TCS3448",
            "description": "TCS low threshold",
            "help": "Lower limit for autogain",
            "type": {"fieldtype": "spinner", "min": 0, "max": 65535, "step": 500}
        },
        "temp_max_dome": {
            "required": "false",
            "tab": "Safety",
            "description": "Max dome temp (°C)",
            "help": "Heater off when dome >= this (0=disabled)",
            "type": {"fieldtype": "spinner", "min": 0, "max": 90, "step": 1}
        },
        "enable_json": {
            "required": "false",
            "tab": "Allsky",
            "description": "JSON for overlay",
            "help": "Write heater_plus.json for Allsky overlay",
            "type": {"fieldtype": "checkbox"}
        },
        "sea_level_pressure": {
            "required": "false",
            "tab": "BME280",
            "description": "Pressure reference (hPa)",
            "help": "Sea-level pressure for altitude calculation",
            "type": {"fieldtype": "spinner", "min": 900, "max": 1100, "step": 1}
        },
        "heater_power_check": {
            "required": "false",
            "tab": "Safety",
            "description": "Heater power check",
            "help": "Verify heater draws current when on",
            "type": {"fieldtype": "checkbox"}
        },
        "heater_duty_min_for_check": {
            "required": "false",
            "tab": "Safety",
            "description": "Min duty for check (%)",
            "help": "Check starts above this duty",
            "type": {"fieldtype": "spinner", "min": 0, "max": 100, "step": 5}
        },
        "sensor_only": {
            "required": "false",
            "tab": "Operation",
            "description": "Sensors only",
            "help": "No heater/fan, sensor readout only",
            "type": {"fieldtype": "checkbox"}
        },
        "control_script_enabled": {
            "required": "false",
            "tab": "Operation",
            "description": "Heater+ control script enabled",
            "help": "On: start heater_plus.py (if stopped). Off: stop heater_plus.py. Takes effect on next periodic run (~60 s).",
            "type": {"fieldtype": "checkbox"}
        },
        "bme280_dome_address": {
            "required": "false",
            "tab": "Sensors",
            "description": "BME280 dome I2C address",
            "help": "Decimal (119=0x77). 0=disable sensor (not connected). No dome = no heater!",
            "type": {"fieldtype": "spinner", "min": 0, "max": 119, "step": 1}
        },
        "bme280_housing_address": {
            "required": "false",
            "tab": "Sensors",
            "description": "BME280 housing I2C address",
            "help": "Decimal (118=0x76). 0=disable sensor.",
            "type": {"fieldtype": "spinner", "min": 0, "max": 119, "step": 1}
        },
        "tsl2591_address": {
            "required": "false",
            "tab": "Sensors",
            "description": "TSL2591 I2C address",
            "help": "Decimal (41=0x29). 0=disable sensor.",
            "type": {"fieldtype": "spinner", "min": 0, "max": 119, "step": 1}
        },
        "as3935_adress": {
            "required": "false",
            "tab": "Sensors",
            "description": "AS3935 lightning I2C address",
            "help": "Decimal (3=0x03). 0=disable sensor.",
            "type": {"fieldtype": "spinner", "min": 0, "max": 119, "step": 1}
        },
        "ina226_address": {
            "required": "false",
            "tab": "Sensors",
            "description": "INA226 current I2C address",
            "help": "Decimal (64=0x40). 0=disable sensor.",
            "type": {"fieldtype": "spinner", "min": 0, "max": 119, "step": 1}
        },
        "tcs3448_address": {
            "required": "false",
            "tab": "Sensors",
            "description": "TCS3448 spectral I2C address",
            "help": "Decimal (89=0x59). 0=disable sensor.",
            "type": {"fieldtype": "spinner", "min": 0, "max": 119, "step": 1}
        }
    }
}


def _control_script_running():
    """Check if heater_plus.py is running (not the allsky_heaterplussettings module)."""
    try:
        r = subprocess.run(
            ["pgrep", "-f", "heater_plus\\.py"],
            capture_output=True,
            timeout=2,
        )
        return r.returncode == 0
    except Exception:
        return False


def _start_control_script():
    """Start heater_plus.py in background (detached from Allsky process)."""
    try:
        subprocess.Popen(
            [sys.executable, HP_CONTROL_SCRIPT],
            cwd=os.path.dirname(HP_CONTROL_SCRIPT),
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        s.log(3, "Heater+ Settings: heater_plus.py started.")
    except Exception as e:
        s.log(0, f"Heater+ Settings: Start failed: {e}")


def _stop_control_script():
    """Stop heater_plus.py via SIGTERM (graceful shutdown with ramp-down)."""
    try:
        r = subprocess.run(
            ["pkill", "-f", "heater_plus\\.py"],
            capture_output=True,
            timeout=5,
        )
        if r.returncode == 0:
            s.log(3, "Heater+ Settings: heater_plus.py stopped.")
    except Exception as e:
        s.log(0, f"Heater+ Settings: Stop failed: {e}")


def _parse_value(val, conv):
    """Parse value; empty strings ignored (None = do not change)."""
    if val is None or (isinstance(val, str) and val.strip() == ""):
        return None
    try:
        return conv(val)
    except (ValueError, TypeError):
        return None


def heaterplussettings(params, event):
    """
    Write Heater+ parameters changed via Allsky GUI to hp_settings.json.
    heater_plus.py detects changes by mtime and reloads settings.
    Controls start/stop of heater_plus.py per control_script_enabled.
    """
    # Start/stop: sync desired state with actual
    enabled = str(params.get("control_script_enabled", "true")).lower() in ("true", "1", "yes")
    running = _control_script_running()
    if enabled and not running:
        _start_control_script()
    elif not enabled and running:
        _stop_control_script()

    if not _control_script_running():
        s.log(2, "Heater+ Settings: heater_plus.py not running – settings will still be saved.")

    if not os.path.isfile(HP_SETTINGS_PATH):
        s.log(0, f"Heater+ Settings: {HP_SETTINGS_PATH} not found.")
        return "Heater+ Settings: File not found."

    try:
        with open(HP_SETTINGS_PATH, "r", encoding="utf-8") as f:
            settings = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        s.log(0, f"Heater+ Settings: Read error: {e}")
        return f"Read error: {e}"

    changed = False
    for arg_name, (hp_key, conv) in _ARG_MAP.items():
        if arg_name not in params:
            continue
        parsed = _parse_value(params.get(arg_name), conv)
        if parsed is None:
            continue
        if settings.get(hp_key) != parsed:
            settings[hp_key] = parsed
            changed = True

    if not changed:
        return "Heater+ Settings: No changes."

    try:
        with open(HP_SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
    except OSError as e:
        s.log(0, f"Heater+ Settings: Write error: {e}")
        return f"Write error: {e}"

    s.log(3, "Heater+ Settings: Updated.")
    return "Heater+ Settings updated."
