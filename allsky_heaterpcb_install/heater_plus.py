#!/usr/bin/env python3
import os
import sys
import time
import json
import signal
import atexit
import math
import subprocess
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from collections import deque
from pathlib import Path
from typing import Optional

import board
import busio
from gpiozero import PWMOutputDevice, Button
from adafruit_bme280 import basic as adafruit_bme280
import adafruit_tsl2591
from RPi_AS3935.RPi_AS3935 import RPi_AS3935
from simple_pid import PID
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

from tcs3448 import TCS3448
from ina226 import INA226  # INA226 class: must accept busnum, address, shunt_ohms

# Persistente Fehler-Logdatei (Support): unabhängig von debugoutput / log_file
DEFAULT_ERROR_LOG_PATH = "/home/pi/heater_plus/heater_plus_errors.log"


def _write_error_log_file(path: str, message: str, traceback_text: str = "") -> None:
    """Schreibt einen Fehlereintrag in die Datei (append). Fehler beim Schreiben werden ignoriert."""
    try:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        parent = Path(path).parent
        parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as ef:
            ef.write(f"[{ts}] {message}\n")
            if traceback_text:
                ef.write(traceback_text.rstrip() + "\n")
            ef.write("---\n")
            ef.flush()
    except Exception:
        pass


def _parse_meminfo(text, key):
    """Parse a value from /proc/meminfo (e.g. 'MemTotal:        7932352 kB' -> 7932352)."""
    for line in text.splitlines():
        if line.startswith(key):
            parts = line.split()
            if len(parts) >= 2:
                return int(parts[1])
    return 0


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class DBConfig:
    url: str
    org: str
    bucket: str
    token: str


@dataclass
class SensorConfig:
    bme_dome_addr: int
    bme_housing_addr: int
    tsl_addr: int
    as3935_addr: int
    as3935_int_pin: int
    ina_addr: int
    ina_shunt_ohms: float
    tcs_addr: int
    # TCS3448: Integration (atime 0..255, astep 0..65535), Gain (0..12, siehe Datenblatt)
    tcs_atime_steps: int
    tcs_astep: int
    tcs_gain_index: int


@dataclass
class PIDConfig:
    P: float
    I: float
    D: float


@dataclass
class GPIOConfig:
    heater_pin: int
    fan_pin: int


@dataclass
class LogicConfig:
    run: bool
    debug: bool
    send_to_db: bool
    upd_interval_db: int
    upd_interval_sensor: int
    temp_set: float
    delta_cooling: float
    delta_dewpoint: float
    set_to_dewpoint: bool
    enable_dewheater: bool
    enable_fan: bool
    sea_level_pressure: float
    tsl_saturation: int
    filename_json: str
    enable_json: bool   # JSON-Datei erstellen/aktualisieren (z. B. für Allsky)
    tmp_settings_path: str
    sensor_only: bool
    # Autogain: Start bei minimalem Gain, bei zu wenig Signal erhöhen, bei Sättigung verringern
    tsl_autogain: bool
    tcs_autogain: bool
    tsl_high_threshold: int   # unterhalb davon: OK; darüber: Gain/Integration verringern
    tsl_low_threshold: int    # darunter: Gain/Integration erhöhen
    tcs_high_threshold: int   # Kanalwert darüber → Gain verringern
    tcs_low_threshold: int    # Kanalwert darunter → Gain erhöhen
    # Sicherheit: Temp-Obergrenze Dome; Leistungsprüfung Heizung
    temp_max_dome: float       # Heizung aus wenn Dome >= dies (°C), 0 = deaktiviert
    heater_power_check: bool   # Prüfen ob Strom steigt wenn Heizung an
    heater_duty_min_for_check: float   # Ab diesem Duty (%) Prüfung
    heater_min_current_above_idle: float  # Erwarteter Stromanstieg (mA) bei Heizung an
    heater_fault_cycles: int   # Zyklen mit zu wenig Strom → Heizer-Fehler
    # Logdatei (leer = nur Konsole)
    log_file: str
    # Fehler-Log für Support (immer bei schwerwiegenden Fehlern beschrieben)
    error_log_path: str
    # Sensor-Ausfall: Heizung aus wenn BME Dome keine gültige Temperatur für X Sekunden liefert (0=deaktiviert)
    sensor_fault_timeout_sec: float
    # Graceful Shutdown: Heizung über X Sekunden rampen statt sofort ausschalten (0=sofort)
    shutdown_heater_ramp_sec: float
    # PID: Annäherungszone (°C) – Heizung drosseln wenn < dieser Abstand zum Sollwert (0=aus)
    pid_proximity_band: float


class HeaterPlusController:
    def __init__(self, settings_path="/home/pi/heater_plus/hp_settings.json"):
        self.settings_path = settings_path

        self.db_cfg: DBConfig | None = None
        self.sensor_cfg: SensorConfig | None = None
        self.pid_cfg: PIDConfig | None = None
        self.gpio_cfg: GPIOConfig | None = None
        self.logic_cfg: LogicConfig | None = None

        self.running = True
        self.data = {}
        self.pid = None

        self.client = None
        self.write_api = None
        self.db_connected = False
        self.db_reconnect_delay = 2

        self.i2c = None
        self.bme280_dome = None
        self.bme280_housing = None
        self.tsl2591 = None
        self.as3935 = None
        self.ina = None
        
        self.tcs = None
        self.tcs_gain_index = 0  # Runtime für TCS-Autogain
        self.tcs_atime_steps = 29  # Runtime Integration (wird in setup_hardware aus Settings gesetzt)
        self.tcs_astep = 599
        self.irq = None

        self.heater = None
        self.fan = None
        self.heater_duty = 0.0
        self.fan_duty = 0.0

        self.tslgainindex = 0
        self.tslintmindex = 0
        self.tslluxaverage = deque(maxlen=5)
        self.tsliraverage = deque(maxlen=5)
        self.tcs_max_average = deque(maxlen=15)  # TCS-Autogain: mehr Samples für stabile Entscheidung
        self.tcs_autogain_cooldown = 0  # Zyklen bis nächste Änderung erlaubt

        self.integration_times = [
            adafruit_tsl2591.INTEGRATIONTIME_100MS,
            adafruit_tsl2591.INTEGRATIONTIME_200MS,
            adafruit_tsl2591.INTEGRATIONTIME_300MS,
            adafruit_tsl2591.INTEGRATIONTIME_400MS,
            adafruit_tsl2591.INTEGRATIONTIME_500MS,
            adafruit_tsl2591.INTEGRATIONTIME_600MS,
        ]
        self.integration_time_ms = [100, 200, 300, 400, 500, 600]

        self.gains = [
            adafruit_tsl2591.GAIN_LOW,
            adafruit_tsl2591.GAIN_MED,
            adafruit_tsl2591.GAIN_HIGH,
            adafruit_tsl2591.GAIN_MAX,
        ]
        self.gain_multiplier = [1, 25, 428, 9876]

        self.control_temp = 0.0

        self.lightning_count = 0
        self.last_distance = 0
        self.last_energy = 0

        # For CPU usage from /proc/stat (delta between two readings)
        self._cpu_stat_prev = None
        self._cpu_stat_time_prev = None

        # INA226 zero offset (current only; power is derived from V * I)
        self.ina_offset_current = 0.0  # mA
        # Dynamisches Neuladen der Settings (Prüfung auf Änderung der Datei)
        self._settings_mtime = 0.0
        # Sicherheit: Heizer-Fehler (Leistung steigt nicht bei Ansteuerung)
        self._heater_fault = False
        self._heater_low_current_cycles = 0
        self._heater_ok_cycles = 0  # Zyklen mit Duty=0 zum Zurücksetzen des Fehlers
        self._log_file = None
        # Sensor-Ausfall: Zeitpunkt des letzten gültigen BME-Dome-Lesewerts
        self._last_valid_bme_dome_time = None
        # Graceful Shutdown: Verhindert Doppelausführung von exit_script
        self._exit_done = False

    @property
    def debug(self):
        return self.logic_cfg.debug if self.logic_cfg else True

    def error_log_path_resolved(self) -> str:
        if self.logic_cfg and getattr(self.logic_cfg, "error_log_path", "").strip():
            return self.logic_cfg.error_log_path.strip()
        return DEFAULT_ERROR_LOG_PATH

    def log_error(self, message: str, exc: Optional[BaseException] = None) -> None:
        """Schreibt in heater_plus_errors.log (und stderr). Unabhängig von debugoutput."""
        path = self.error_log_path_resolved()
        tb = ""
        if exc is not None:
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        _write_error_log_file(path, message, tb)
        print(f"[ERROR] {message}", file=sys.stderr)
        if tb and self.debug:
            print(tb, file=sys.stderr)

    def log(self, *args):
        msg = " ".join(str(a) for a in args)
        if self.debug:
            print(*args)
        if self._log_file:
            try:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._log_file.write(f"{ts}  {msg}\n")
                self._log_file.flush()
            except Exception:
                pass

    # -----------------------------------------------------------------------
    # Load settings
    # -----------------------------------------------------------------------
    def load_settings(self):
        if not os.path.exists(self.settings_path):
            _write_error_log_file(
                DEFAULT_ERROR_LOG_PATH,
                f"hp_settings.json nicht gefunden: {self.settings_path}",
                "",
            )
            print("[Settings] Settings file not found:", self.settings_path)
            sys.exit(1)

        with open(self.settings_path) as f:
            s = json.load(f)

        self.logic_cfg = LogicConfig(
            run=bool(s.get("running", True)),
            debug=bool(s.get("debugoutput", True)),
            send_to_db=bool(s.get("sendtodb", True)),
            upd_interval_db=s.get("updateinterval_db", 10),
            upd_interval_sensor=s.get("sensorupdateintervall", 2),
            temp_set=float(s.get("temp_set", 15.0)),
            delta_cooling=float(s.get("deltacooling", 1.0)),
            delta_dewpoint=float(s.get("deltadewpoint", 4.0)),
            set_to_dewpoint=bool(s.get("settodewpoint", False)),
            enable_dewheater=bool(s.get("enable_dewheater", True)),
            enable_fan=bool(s.get("enable_fan", True)),
            sea_level_pressure=float(s.get("sea_level_pressure", 1013.25)),
            tsl_saturation=int(s.get("tslsaturationsetvalue", 65000)),
            filename_json=s.get("filename_json", "/home/pi/allsky/config/overlay/extra/heater_plus.json"),
            enable_json=bool(s.get("enable_json", True)),
            tmp_settings_path=s.get("tmpsettingsfilepath", self.settings_path),
            sensor_only=bool(s.get("sensor_only", False)),
            tsl_autogain=bool(s.get("tsl_autogain", True)),
            tcs_autogain=bool(s.get("tcs_autogain", True)),
            tsl_high_threshold=int(s.get("tsl_high_threshold", 40000)),
            tsl_low_threshold=int(s.get("tsl_low_threshold", 100)),
            tcs_high_threshold=int(s.get("tcs_high_threshold", 0)),  # 0 = Auto (85% von max_count)
            tcs_low_threshold=int(s.get("tcs_low_threshold", 2000)),
            temp_max_dome=float(s.get("temp_max_dome", 0)),
            heater_power_check=bool(s.get("heater_power_check", False)),
            heater_duty_min_for_check=float(s.get("heater_duty_min_for_check", 20.0)),
            heater_min_current_above_idle=float(s.get("heater_min_current_above_idle", 10.0)),
            heater_fault_cycles=int(s.get("heater_fault_cycles", 5)),
            log_file=(s.get("log_file") or s.get("logfile_path") or "").strip() or "",
            error_log_path=(s.get("error_log_path") or "").strip() or DEFAULT_ERROR_LOG_PATH,
            sensor_fault_timeout_sec=float(s.get("sensor_fault_timeout_sec", 10.0)),
            shutdown_heater_ramp_sec=float(s.get("shutdown_heater_ramp_sec", 1.5)),
            pid_proximity_band=float(s.get("pid_proximity_band", 0.5)),
        )

        self.db_cfg = DBConfig(
            url=s.get("url_db", "http://localhost:8086"),
            org=s.get("org_db", "allsky"),
            bucket=s.get("bucket_db", "heater_plus"),
            token=s.get("token_db", ""),
        )

        self.sensor_cfg = SensorConfig(
            bme_dome_addr=s.get("bme280_dome_address", 0x77),
            bme_housing_addr=s.get("bme280_housing_address", 0x76),
            tsl_addr=s.get("tsl2591_address", 0x29),
            as3935_addr=s.get("as3935_adress", 0x03),
            as3935_int_pin=s.get("as3935interruptpin", 17),
            ina_addr=s.get("ina226_address", 0x40),
            ina_shunt_ohms=float(s.get("ina226_shunt_ohms", 0.025)),
            tcs_addr=s.get("tcs3448_address", 0x59),
            tcs_atime_steps=int(s.get("tcs3448_atime_steps", 9)),
            tcs_astep=int(s.get("tcs3448_astep", 599)),
            tcs_gain_index=int(s.get("tcs3448_gain_index", 0)),
        )
        # TSL2591: Start-Gain und Integrationszeit aus Settings (0 = LOW/100ms, wird bei Sättigung automatisch erhöht)
        # Start low (gain 0, integration 0); autogain ramps up as needed
        self.tslgainindex = max(0, min(len(self.gains) - 1, int(s.get("tslgainindex", 0))))
        self.tslintmindex = max(0, min(len(self.integration_times) - 1, int(s.get("tslintmindex", 0))))

        self.pid_cfg = PIDConfig(
            P=float(s.get("pid_p", 15.0)),
            I=float(s.get("pid_i", 0.3)),
            D=float(s.get("pid_d", 0.0)),
        )

        self.gpio_cfg = GPIOConfig(
            heater_pin=s.get("heaterpin", 18),
            fan_pin=s.get("fanpin", 16),
        )

        self.log("[Settings] Loaded from", self.settings_path)
        try:
            self._settings_mtime = os.path.getmtime(self.settings_path)
        except OSError:
            pass

    # -----------------------------------------------------------------------
    # Settings validation
    # -----------------------------------------------------------------------
    def validate_settings(self, exit_on_error=True):
        """Prüft sinnvolle Grenzen. Bei exit_on_error=True: beendet mit Fehlermeldung. Sonst: gibt False zurück."""
        err = []
        c = self.logic_cfg
        s = self.sensor_cfg
        p = self.pid_cfg
        g = self.gpio_cfg
        if c.temp_set < -20 or c.temp_set > 80:
            err.append(f"temp_set={c.temp_set} außerhalb -20..80 °C")
        if c.temp_max_dome > 0 and (c.temp_max_dome < 30 or c.temp_max_dome > 90):
            err.append(f"temp_max_dome={c.temp_max_dome} außerhalb 30..90 °C (0=aus)")
        if p.P < 0 or p.I < 0 or p.D < 0:
            err.append(f"PID-Werte müssen >= 0 (pid_p={p.P}, pid_i={p.I}, pid_d={p.D})")
        pb = getattr(c, "pid_proximity_band", 0)
        if pb < 0 or pb > 2.0:
            err.append(f"pid_proximity_band={pb} muss 0..2 °C sein (0=aus)")
        if c.upd_interval_sensor < 1:
            err.append(f"sensorupdateintervall={c.upd_interval_sensor} muss >= 1")
        if c.upd_interval_db < 1:
            err.append(f"updateinterval_db={c.upd_interval_db} muss >= 1")
        for name, addr in [("bme280_dome", s.bme_dome_addr), ("bme280_housing", s.bme_housing_addr),
                           ("tsl2591", s.tsl_addr), ("ina226", s.ina_addr), ("tcs3448", s.tcs_addr)]:
            if addr and (addr < 0x08 or addr > 0x77):
                err.append(f"I2C-Adresse {name}=0x{addr:02X} außerhalb 0x08..0x77")
        if s.ina_shunt_ohms <= 0 or s.ina_shunt_ohms > 1:
            err.append(f"ina226_shunt_ohms={s.ina_shunt_ohms} sinnvoll 0.001..1 Ohm")
        if g.heater_pin and (g.heater_pin < 2 or g.heater_pin > 27):
            err.append(f"heaterpin={g.heater_pin} außerhalb 2..27 (BCM), 0=aus")
        if g.fan_pin and (g.fan_pin < 2 or g.fan_pin > 27):
            err.append(f"fanpin={g.fan_pin} außerhalb 2..27 (BCM), 0=aus")
        if c.heater_power_check and (c.heater_duty_min_for_check < 0 or c.heater_duty_min_for_check > 100):
            err.append("heater_duty_min_for_check muss 0..100")
        if c.heater_power_check and c.heater_fault_cycles < 1:
            err.append("heater_fault_cycles muss >= 1")
        if c.tsl_high_threshold < 0 or c.tsl_high_threshold > 65535:
            err.append(f"tsl_high_threshold={c.tsl_high_threshold} muss 0..65535")
        if c.tcs_high_threshold < 0 or c.tcs_high_threshold > 65535:
            err.append(f"tcs_high_threshold={c.tcs_high_threshold} muss 0..65535")
        if getattr(c, "sensor_fault_timeout_sec", 10) < 0:
            err.append("sensor_fault_timeout_sec muss >= 0 (0=deaktiviert)")
        if getattr(c, "shutdown_heater_ramp_sec", 1.5) < 0:
            err.append("shutdown_heater_ramp_sec muss >= 0 (0=sofort ausschalten)")
        if err:
            detail = "\n".join(f"  - {e}" for e in err)
            print("[Settings] Validierung fehlgeschlagen:")
            for e in err:
                print("  -", e)
            print("Bitte hp_settings.json anpassen.")
            self.log_error("[Settings] Validierung fehlgeschlagen:\n" + detail, None)
            if exit_on_error:
                sys.exit(1)
            return False
        return True

    # -----------------------------------------------------------------------
    # Dynamisches Neuladen der Settings
    # -----------------------------------------------------------------------
    def reload_runtime_settings(self, s):
        """Lädt Laufzeit-relevante Einstellungen aus dict s (ohne Hardware-Änderung)."""
        self.logic_cfg = LogicConfig(
            run=bool(s.get("running", True)),
            debug=bool(s.get("debugoutput", True)),
            send_to_db=bool(s.get("sendtodb", True)),
            upd_interval_db=s.get("updateinterval_db", 10),
            upd_interval_sensor=s.get("sensorupdateintervall", 2),
            temp_set=float(s.get("temp_set", 15.0)),
            delta_cooling=float(s.get("deltacooling", 1.0)),
            delta_dewpoint=float(s.get("deltadewpoint", 4.0)),
            set_to_dewpoint=bool(s.get("settodewpoint", False)),
            enable_dewheater=bool(s.get("enable_dewheater", True)),
            enable_fan=bool(s.get("enable_fan", True)),
            sea_level_pressure=float(s.get("sea_level_pressure", 1013.25)),
            tsl_saturation=int(s.get("tslsaturationsetvalue", 65000)),
            filename_json=s.get("filename_json", "/home/pi/allsky/config/overlay/extra/heater_plus.json"),
            enable_json=bool(s.get("enable_json", True)),
            tmp_settings_path=s.get("tmpsettingsfilepath", self.settings_path),
            sensor_only=bool(s.get("sensor_only", False)),
            tsl_autogain=bool(s.get("tsl_autogain", True)),
            tcs_autogain=bool(s.get("tcs_autogain", True)),
            tsl_high_threshold=int(s.get("tsl_high_threshold", 40000)),
            tsl_low_threshold=int(s.get("tsl_low_threshold", 100)),
            tcs_high_threshold=int(s.get("tcs_high_threshold", 0)),  # 0 = Auto (85% von max_count)
            tcs_low_threshold=int(s.get("tcs_low_threshold", 2000)),
            temp_max_dome=float(s.get("temp_max_dome", 0)),
            heater_power_check=bool(s.get("heater_power_check", False)),
            heater_duty_min_for_check=float(s.get("heater_duty_min_for_check", 20.0)),
            heater_min_current_above_idle=float(s.get("heater_min_current_above_idle", 10.0)),
            heater_fault_cycles=int(s.get("heater_fault_cycles", 5)),
            log_file=(s.get("log_file") or s.get("logfile_path") or "").strip() or "",
            error_log_path=(s.get("error_log_path") or "").strip() or DEFAULT_ERROR_LOG_PATH,
            sensor_fault_timeout_sec=float(s.get("sensor_fault_timeout_sec", 10.0)),
            shutdown_heater_ramp_sec=float(s.get("shutdown_heater_ramp_sec", 1.5)),
            pid_proximity_band=float(s.get("pid_proximity_band", 0.5)),
        )
        self.db_cfg = DBConfig(
            url=s.get("url_db", "http://localhost:8086"),
            org=s.get("org_db", "allsky"),
            bucket=s.get("bucket_db", "heater_plus"),
            token=s.get("token_db", ""),
        )
        self.pid_cfg = PIDConfig(
            P=float(s.get("pid_p", 15.0)),
            I=float(s.get("pid_i", 0.3)),
            D=float(s.get("pid_d", 0.0)),
        )
        if self.pid:
            self.pid.Kp = self.pid_cfg.P
            self.pid.Ki = self.pid_cfg.I
            self.pid.Kd = self.pid_cfg.D
        for bme in [self.bme280_dome, self.bme280_housing]:
            if bme:
                bme.sea_level_pressure = self.logic_cfg.sea_level_pressure
        self.log("[Settings] Neu geladen (temp_set=", self.logic_cfg.temp_set, ", pid=", self.pid_cfg.P, "/", self.pid_cfg.I, "/", self.pid_cfg.D, ")")

    def check_and_reload_settings(self):
        """Prüft ob hp_settings.json geändert wurde und lädt ggf. neu."""
        try:
            mtime = os.path.getmtime(self.settings_path)
        except OSError:
            return
        if mtime <= self._settings_mtime:
            return
        try:
            with open(self.settings_path) as f:
                s = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            self.log_error("[Settings] Neuladen fehlgeschlagen", e)
            return
        self._settings_mtime = mtime
        if not self.validate_settings(exit_on_error=False):
            self.log("[Settings] Neuladen übersprungen: Validierung fehlgeschlagen.")
            return
        self.reload_runtime_settings(s)

    # -----------------------------------------------------------------------
    # Hardware Setup
    # -----------------------------------------------------------------------
    def setup_hardware(self):
        self.i2c = busio.I2C(board.SCL, board.SDA)

        # BME280 Dome
        if self.sensor_cfg.bme_dome_addr:
            try:
                self.bme280_dome = adafruit_bme280.Adafruit_BME280_I2C(
                    self.i2c, address=self.sensor_cfg.bme_dome_addr
                )
                self.bme280_dome.sea_level_pressure = self.logic_cfg.sea_level_pressure
                self.log("[Init] BME280 Dome OK.")
            except Exception as e:
                self.log_error("[Init] BME280 Dome error", e)

        # BME280 Housing
        if self.sensor_cfg.bme_housing_addr:
            try:
                self.bme280_housing = adafruit_bme280.Adafruit_BME280_I2C(
                    self.i2c, address=self.sensor_cfg.bme_housing_addr
                )
                self.bme280_housing.sea_level_pressure = self.logic_cfg.sea_level_pressure
                self.log("[Init] BME280 Housing OK.")
            except Exception as e:
                self.log_error("[Init] BME280 Housing error", e)

        # TSL2591
        if self.sensor_cfg.tsl_addr:
            try:
                self.tsl2591 = adafruit_tsl2591.TSL2591(self.i2c)
                self.tsl2591.gain = self.gains[self.tslgainindex]
                self.tsl2591.integration_time = self.integration_times[self.tslintmindex]
                self.log(f"[Init] TSL2591 OK (gain={self.tslgainindex}, integration={self.integration_time_ms[self.tslintmindex]} ms).")
            except Exception as e:
                self.log_error("[Init] TSL2591 error", e)

        # AS3935
        if self.sensor_cfg.as3935_addr:
            try:
                self.as3935 = RPi_AS3935(address=self.sensor_cfg.as3935_addr, bus=1)
                self.as3935.set_indoors(True)
                self.as3935.set_min_strikes(1)
                self.as3935.calibrate()
                # AS3935 IRQ ist aktiv HIGH – pull_up=False damit when_pressed auf steigende Flanke reagiert
                self.irq = Button(self.sensor_cfg.as3935_int_pin, pull_up=False)
                self.irq.when_pressed = self.handle_irq
                self.data["as_lightning_count"] = 0
                self.data["as_last_distance"] = 0
                self.data["as_last_energy"] = 0
                self.log("[Init] AS3935 OK (Interrupt + Polling).")
            except Exception as e:
                self.log_error("[Init] AS3935 error", e)

        # INA226 (Adresse 0 = deaktiviert, Sensor nicht angeschlossen)
        if self.sensor_cfg.ina_addr:
            try:
                self.ina = INA226(
                    busnum=1,
                    address=self.sensor_cfg.ina_addr,
                    shunt_ohms=self.sensor_cfg.ina_shunt_ohms,
                )
                self.ina.configure()
                self.log("[Init] INA226 OK.")
            except Exception as e:
                self.log_error("[Init] INA226 error", e)
                self.ina = None
        else:
            self.log("[Init] INA226 deaktiviert (ina226_address=0).")

        # TCS3448 (Adresse 0 = deaktiviert, Sensor nicht angeschlossen)
        if self.sensor_cfg.tcs_addr:
            try:
                self.tcs = TCS3448(
                    self.i2c,
                    address=self.sensor_cfg.tcs_addr,
                    atime_steps=self.sensor_cfg.tcs_atime_steps,
                    astep=self.sensor_cfg.tcs_astep,
                    gain_index=self.sensor_cfg.tcs_gain_index,
                )
                self.tcs_gain_index = self.sensor_cfg.tcs_gain_index
                self.tcs_atime_steps = self.sensor_cfg.tcs_atime_steps
                self.tcs_astep = self.sensor_cfg.tcs_astep
                self.log(f"[Init] TCS3448 OK (atime={self.tcs_atime_steps}, astep={self.tcs_astep}, gain={self.tcs_gain_index}).")
            except Exception as e:
                self.log_error("[Init] TCS3448 error", e)
                self.tcs = None
        else:
            self.log("[Init] TCS3448 deaktiviert (tcs3448_address=0).")

        # GPIO PWM (nur wenn nicht sensor_only – sonst GPIO evtl. von Kamera/anderem belegt)
        if not self.logic_cfg.sensor_only:
            if self.gpio_cfg.heater_pin:
                self.heater = PWMOutputDevice(self.gpio_cfg.heater_pin, frequency=10000)
            if self.gpio_cfg.fan_pin:
                self.fan = PWMOutputDevice(self.gpio_cfg.fan_pin, frequency=10000)
            self.log("[Init] GPIO PWM ready.")
        else:
            self.log("[Init] GPIO PWM übersprungen (sensor_only).")

    # -----------------------------------------------------------------------
    # INA226 zero calibration (with heater off)
    # -----------------------------------------------------------------------
    def calibrate_ina_zero(self, settle_sec=2.0, samples=10):
        """
        Measure INA226 current with heater off and use as zero offset.
        Power is then computed as P = V_bus * I_corrected, so no separate power offset.
        Call once after setup_hardware() when the heater is off (e.g. at script start).
        """
        if not self.ina:
            return
        if self.heater:
            self.heater.value = 0.0
        if self.fan:
            self.fan.value = 0.0
        time.sleep(settle_sec)
        currents = []
        for _ in range(samples):
            try:
                currents.append(float(self.ina.current()))
            except Exception:
                pass
            time.sleep(0.1)
        if currents:
            self.ina_offset_current = sum(currents) / len(currents)
            self.log("[Init] INA226 zero offset: current={:.2f} mA".format(self.ina_offset_current))

    # -----------------------------------------------------------------------
    # PID + Signals
    # -----------------------------------------------------------------------
    def setup_pid(self):
        sample_time = self.logic_cfg.upd_interval_sensor
        self.pid = PID(
            self.pid_cfg.P,
            self.pid_cfg.I,
            self.pid_cfg.D,
            sample_time=sample_time,
            output_limits=(0, 100),
        )

    def setup_signals(self):
        signal.signal(signal.SIGINT, self.exit_script)
        signal.signal(signal.SIGTERM, self.exit_script)
        atexit.register(self.exit_script)

    # -----------------------------------------------------------------------
    # InfluxDB 2.x
    # -----------------------------------------------------------------------
    def influxdb_connect(self):
        if not self.logic_cfg.send_to_db:
            return
        tok = (self.db_cfg.token or "").strip()
        if not tok or tok == "REPLACE_WITH_INFLUX_TOKEN":
            self.db_connected = False
            self.log_error(
                "[InfluxDB] token_db fehlt oder ist Platzhalter REPLACE_WITH_INFLUX_TOKEN – "
                "echtes Token in hp_settings.json setzen (http://localhost:8086)",
                None,
            )
            return
        try:
            self.client = InfluxDBClient(
                url=self.db_cfg.url,
                token=self.db_cfg.token,
                org=self.db_cfg.org,
            )
            self.write_api = self.client.write_api(write_options=SYNCHRONOUS)
            self.db_connected = True
            self.log("[Init] InfluxDB2 OK.")
        except Exception as e:
            self.db_connected = False
            self.log_error("[Init] InfluxDB2 error", e)

    def influxdb_reconnect(self):
        if not self.db_connected and self.logic_cfg.send_to_db:
            self.log(f"[InfluxDB] Reconnect in {self.db_reconnect_delay}s...")
            time.sleep(self.db_reconnect_delay)
            self.influxdb_connect()

    def influxdb_write(self):
        if not self.logic_cfg.send_to_db:
            return
        if not self.db_connected:
            self.influxdb_reconnect()
        if not self.db_connected:
            self.log("[InfluxDB] No connection.")
            return

        try:
            # Use timezone-aware timestamp instead of utcnow()
            ts = datetime.now(timezone.utc)

            # TSL2591
            if "tsl_lux" in self.data and self.sensor_cfg.tsl_addr:
                p = (
                    Point("sensor_data")
                    .tag("sensor", "tsl2591")
                    .tag("location", "dome")
                    .tag("measurement", "light")
                    .field("tsl_lux", self.data["tsl_lux"])
                    .field("tsl_infrared", self.data["tsl_infrared"])
                    .field("tsl_fullspectrum", self.data["tsl_fullspectrum"])
                    .field("tsl_visible", self.data["tsl_visible"])
                    .field("tsl_gain_index", self.data["tsl_gain_index"])
                    .field("tsl_integration_index", self.data["tsl_intmindex"])
                    .field("tsl_gainmultipl", self.data["tsl_gainmultipl"])
                    .field("tsl_inttm", self.data["tsl_inttm"])
                    .time(ts, WritePrecision.S)
                )
                self.write_api.write(self.db_cfg.bucket, self.db_cfg.org, p)

            # BME Dome
            if "bme_temp_dome" in self.data and self.sensor_cfg.bme_dome_addr:
                p = (
                    Point("sensor_data")
                    .tag("sensor", "BME280")
                    .tag("location", "dome")
                    .tag("measurement", "temp_press_hum")
                    .field("bme_temp_dome", self.data["bme_temp_dome"])
                    .field("bme_hum_dome", self.data["bme_hum_dome"])
                    .field("bme_pres_dome", self.data["bme_pres_dome"])
                    .field("bme_dewp_dome", self.data["bme_dewp_dome"])
                    .field("heaterplus_settemp", self.data["heaterplus_settemp"])
                    .time(ts, WritePrecision.S)
                )
                self.write_api.write(self.db_cfg.bucket, self.db_cfg.org, p)

            # BME Housing
            if "bme_temp_housing" in self.data and self.sensor_cfg.bme_housing_addr:
                p = (
                    Point("sensor_data")
                    .tag("sensor", "BME280")
                    .tag("location", "housing")
                    .tag("measurement", "temp_press_hum")
                    .field("bme_temp_housing", self.data["bme_temp_housing"])
                    .field("bme_hum_housing", self.data["bme_hum_housing"])
                    .field("bme_pres_housing", self.data["bme_pres_housing"])
                    .field("bme_dewp_housing", self.data["bme_dewp_housing"])
                    .time(ts, WritePrecision.S)
                )
                self.write_api.write(self.db_cfg.bucket, self.db_cfg.org, p)

            # Heater / Fan
            if "heater_duty" in self.data and self.gpio_cfg.heater_pin:
                p = (
                    Point("sensor_data")
                    .tag("sensor", "PWM")
                    .tag("measurement", "pwm_duty")
                    .field("heater_duty", self.data["heater_duty"])
                    .field("heater_fault", self.data.get("heater_fault", False))
                    .field("heater_safety_temp", self.data.get("heater_safety_temp", False))
                    .field("heater_safety_sensor", self.data.get("heater_safety_sensor", False))
                    .time(ts, WritePrecision.S)
                )
                self.write_api.write(self.db_cfg.bucket, self.db_cfg.org, p)

            if "fan_duty" in self.data and self.gpio_cfg.fan_pin:
                p = (
                    Point("sensor_data")
                    .tag("sensor", "PWM")
                    .tag("measurement", "pwm_duty")
                    .field("fan_duty", self.data["fan_duty"])
                    .time(ts, WritePrecision.S)
                )
                self.write_api.write(self.db_cfg.bucket, self.db_cfg.org, p)

            # INA226
            if "ina_vbus" in self.data and self.ina:
                p = (
                    Point("sensor_data")
                    .tag("sensor", "INA226")
                    .tag("measurement", "supply")
                    .field("ina_vbus", self.data["ina_vbus"])
                    .field("ina_current", self.data["ina_current"])
                    .field("ina_power", self.data["ina_power"])
                    .time(ts, WritePrecision.S)
                )
                self.write_api.write(self.db_cfg.bucket, self.db_cfg.org, p)

            # TCS3448 spectrum (only numeric values, skip invalid to avoid write errors)
            if self.tcs:
                raw = {k: v for k, v in self.data.items() if k.startswith("tcs_")}
                fields = {}
                for k, v in raw.items():
                    try:
                        if isinstance(v, (int, float)) and not (isinstance(v, bool)):
                            fields[k] = int(v)
                    except (TypeError, ValueError):
                        pass
                if fields:
                    try:
                        p = (
                            Point("sensor_data")
                            .tag("sensor", "TCS3448")
                            .tag("measurement", "spectrum")
                            .time(ts, WritePrecision.S)
                        )
                        for k, v in fields.items():
                            p = p.field(k, v)
                        self.write_api.write(self.db_cfg.bucket, self.db_cfg.org, p)
                    except Exception as e:
                        self.log_error("[InfluxDB] TCS3448 write error", e)

            # Raspberry Pi status (measurement "rpi_status" for Grafana)
            pi_fields = {}
            if "pi_cpu_temp" in self.data:
                pi_fields["pi_cpu_temp"] = self.data["pi_cpu_temp"]
            if "pi_disk_percent" in self.data:
                pi_fields["pi_disk_percent"] = self.data["pi_disk_percent"]
            if "pi_cpu_usage" in self.data:
                pi_fields["pi_cpu_usage"] = self.data["pi_cpu_usage"]
            if "pi_mem_percent" in self.data:
                pi_fields["pi_mem_percent"] = self.data["pi_mem_percent"]
            if pi_fields:
                p = Point("rpi_status").time(ts, WritePrecision.S)
                for k, v in pi_fields.items():
                    p = p.field(k, v)
                self.write_api.write(self.db_cfg.bucket, self.db_cfg.org, p)

            # AS3935 lightning
            if self.as3935 and "as_lightning_count" in self.data:
                p = (
                    Point("sensor_data")
                    .tag("sensor", "AS3935")
                    .tag("measurement", "lightning")
                    .field("as_lightning_count", self.data["as_lightning_count"])
                    .field("as_last_distance", self.data["as_last_distance"])
                    .field("as_last_energy", self.data["as_last_energy"])
                    .time(ts, WritePrecision.S)
                )
                self.write_api.write(self.db_cfg.bucket, self.db_cfg.org, p)

        except Exception as e:
            self.log_error("[InfluxDB] Write error", e)
            self.db_connected = False

    def influxdb_close(self):
        try:
            if self.client:
                self.client.close()
                self.db_connected = False
                self.log("[InfluxDB] Connection closed.")
        except Exception as e:
            self.log_error("[InfluxDB] Close error", e)

    # -----------------------------------------------------------------------
    # JSON output for Allsky Overlay (config/overlay/extra/)
    # -----------------------------------------------------------------------
    @staticmethod
    def ascii_bar(value, vmin, vmax, width=10):
        """Erzeugt ASCII-Balken aus Unicode-Blöcken. value zwischen vmin und vmax."""
        try:
            v = float(value)
            if vmax <= vmin:
                return "\u2588" * width  # voll bei undefiniert
            r = (v - vmin) / (vmax - vmin)
            r = max(0.0, min(1.0, r))
            filled = int(round(r * width))
            return "\u2588" * filled + "\u2591" * (width - filled)
        except (TypeError, ValueError):
            return "\u2591" * width

    def json_write(self):
        """Schreibt Sensorwerte als JSON für Allsky Overlay (extra data file)."""
        try:
            if not self.logic_cfg.enable_json or not self.logic_cfg.filename_json:
                return
            d = self.data

            def to_float(val, default=0.0):
                if val is None:
                    return default
                try:
                    return float(val)
                except (TypeError, ValueError):
                    return default

            def to_str(val, default="--"):
                if val is None:
                    return default
                return str(val)

            bar = self.ascii_bar

            # Format für Allsky allsky_overlay.py (Variable → value + optional expires)
            expiry = 60
            out = {
                # BME Dome
                "HP_TEMP_DOME": {"value": f"{to_float(d.get('bme_temp_dome')):.1f}", "expires": expiry},
                "HP_DEWPOINT_DOME": {"value": f"{to_float(d.get('bme_dewp_dome')):.1f}", "expires": expiry},
                "HP_HUMIDITY_DOME": {"value": f"{to_float(d.get('bme_hum_dome')):.1f}", "expires": expiry},
                "HP_PRES_DOME": {"value": f"{to_float(d.get('bme_pres_dome')):.0f}", "expires": expiry},
                # BME Housing
                "HP_TEMP_HOUSING": {"value": f"{to_float(d.get('bme_temp_housing')):.1f}", "expires": expiry},
                "HP_DEWPOINT_HOUSING": {"value": f"{to_float(d.get('bme_dewp_housing')):.1f}", "expires": expiry},
                "HP_HUMIDITY_HOUSING": {"value": f"{to_float(d.get('bme_hum_housing')):.1f}", "expires": expiry},
                "HP_PRES_HOUSING": {"value": f"{to_float(d.get('bme_pres_housing')):.0f}", "expires": expiry},
                # Heizung
                "HP_SETPOINT": {"value": f"{to_float(d.get('heaterplus_settemp')):.1f}", "expires": expiry},
                "HP_HEATER_DUTY": {"value": f"{to_float(d.get('heater_duty')):5.1f}", "expires": expiry},
                "HP_FAN_DUTY": {"value": f"{to_float(d.get('fan_duty')):5.1f}", "expires": expiry},
                # TSL2591
                "HP_LUX": {"value": f"{to_float(d.get('tsl_lux')):.1f}", "expires": expiry},
                "HP_TSL_INFRARED": {"value": f"{to_float(d.get('tsl_infrared')):.1f}", "expires": expiry},
                "HP_TSL_VISIBLE": {"value": f"{to_float(d.get('tsl_visible')):.1f}", "expires": expiry},
                "HP_TSL_GAIN": {"value": f"{int(d.get('tsl_gainmultipl', 1)):>4}", "expires": expiry},
                "HP_TSL_ATIME": {"value": f"{int(d.get('tsl_inttm', 0)):>3}", "expires": expiry},
                # TCS3448
                "HP_TCS_VIS": {"value": f"{int(d.get('tcs_vis', 0))}", "expires": expiry},
                "HP_TCS_NIR": {"value": f"{int(d.get('tcs_nir', 0))}", "expires": expiry},
                "HP_TCS_GAIN": {"value": f"{int(d.get('tcs_gain_index', 0)):>2}", "expires": expiry},
                "HP_TCS_ATIME": {"value": f"{int(d.get('tcs_atime_steps', 0)):>3}", "expires": expiry},
                "HP_TCS_F1": {"value": f"{int(d.get('tcs_f1', 0)):>5}", "expires": expiry},
                "HP_TCS_F2": {"value": f"{int(d.get('tcs_f2', 0)):>5}", "expires": expiry},
                "HP_TCS_F3": {"value": f"{int(d.get('tcs_f3', 0)):>5}", "expires": expiry},
                "HP_TCS_F4": {"value": f"{int(d.get('tcs_f4', 0)):>5}", "expires": expiry},
                "HP_TCS_F5": {"value": f"{int(d.get('tcs_f5', 0)):>5}", "expires": expiry},
                "HP_TCS_F6": {"value": f"{int(d.get('tcs_f6', 0)):>5}", "expires": expiry},
                "HP_TCS_F7": {"value": f"{int(d.get('tcs_f7', 0)):>5}", "expires": expiry},
                "HP_TCS_F8": {"value": f"{int(d.get('tcs_f8', 0)):>5}", "expires": expiry},
                # INA226
                "HP_VOLTAGE": {"value": f"{to_float(d.get('ina_vbus')):.2f}", "expires": expiry},
                "HP_CURRENT": {"value": f"{to_float(d.get('ina_current')):.2f}", "expires": expiry},
                "HP_POWER_MW": {"value": f"{to_float(d.get('ina_power')):.0f}", "expires": expiry},
                # AS3935
                "HP_LIGHTNING_COUNT": {"value": f"{int(d.get('as_lightning_count', 0))}", "expires": expiry},
                "HP_LAST_DISTANCE": {"value": to_str(d.get("as_last_distance"), "--"), "expires": expiry},
                "HP_LAST_ENERGY": {"value": to_str(d.get("as_last_energy"), "--"), "expires": expiry},
                # Raspberry Pi
                "HP_PI_CPU_TEMP": {"value": f"{to_float(d.get('pi_cpu_temp')):5.1f}", "expires": expiry},
                "HP_PI_DISK_PERCENT": {"value": f"{to_float(d.get('pi_disk_percent')):5.1f}", "expires": expiry},
                "HP_PI_MEM_PERCENT": {"value": f"{to_float(d.get('pi_mem_percent')):5.1f}", "expires": expiry},
                "HP_PI_CPU_USAGE": {"value": f"{to_float(d.get('pi_cpu_usage')):5.1f}", "expires": expiry},
                # ASCII-Balken (0-10 Zeichen)
                "HP_BAR_TEMP_DOME": {"value": bar(to_float(d.get("bme_temp_dome")), -10, 50), "expires": expiry},
                "HP_BAR_HUM_DOME": {"value": bar(to_float(d.get("bme_hum_dome")), 0, 100), "expires": expiry},
                "HP_BAR_HEATER": {"value": bar(to_float(d.get("heater_duty")), 0, 100), "expires": expiry},
                "HP_BAR_FAN": {"value": bar(to_float(d.get("fan_duty")), 0, 100), "expires": expiry},
                "HP_BAR_LUX": {"value": bar(min(to_float(d.get("tsl_lux")), 10000), 0, 10000), "expires": expiry},
                "HP_BAR_TSL_GAIN": {"value": bar(int(d.get("tsl_gain_index", 0)), 0, 3), "expires": expiry},
                "HP_BAR_TSL_ATIME": {"value": bar(int(d.get("tsl_inttm", 100)), 100, 600), "expires": expiry},
                "HP_BAR_TCS_GAIN": {"value": bar(int(d.get("tcs_gain_index", 0)), 0, 12), "expires": expiry},
                "HP_BAR_TCS_ATIME": {"value": bar(int(d.get("tcs_atime_steps", 0)), 0, 255), "expires": expiry},
                "HP_BAR_CPU_TEMP": {"value": bar(to_float(d.get("pi_cpu_temp")), 0, 80), "expires": expiry},
                "HP_BAR_DISK": {"value": bar(to_float(d.get("pi_disk_percent")), 0, 100), "expires": expiry},
                "HP_BAR_MEM": {"value": bar(to_float(d.get("pi_mem_percent")), 0, 100), "expires": expiry},
                "HP_BAR_CPU_USAGE": {"value": bar(to_float(d.get("pi_cpu_usage")), 0, 100), "expires": expiry},
                "HP_BAR_F1": {"value": bar(int(d.get("tcs_f1", 0)), 0, int(d.get("tcs_max_count", 65535))), "expires": expiry},
                "HP_BAR_F2": {"value": bar(int(d.get("tcs_f2", 0)), 0, int(d.get("tcs_max_count", 65535))), "expires": expiry},
                "HP_BAR_F3": {"value": bar(int(d.get("tcs_f3", 0)), 0, int(d.get("tcs_max_count", 65535))), "expires": expiry},
                "HP_BAR_F4": {"value": bar(int(d.get("tcs_f4", 0)), 0, int(d.get("tcs_max_count", 65535))), "expires": expiry},
                "HP_BAR_F5": {"value": bar(int(d.get("tcs_f5", 0)), 0, int(d.get("tcs_max_count", 65535))), "expires": expiry},
                "HP_BAR_F6": {"value": bar(int(d.get("tcs_f6", 0)), 0, int(d.get("tcs_max_count", 65535))), "expires": expiry},
                "HP_BAR_F7": {"value": bar(int(d.get("tcs_f7", 0)), 0, int(d.get("tcs_max_count", 65535))), "expires": expiry},
                "HP_BAR_F8": {"value": bar(int(d.get("tcs_f8", 0)), 0, int(d.get("tcs_max_count", 65535))), "expires": expiry},
            }
            p = Path(self.logic_cfg.filename_json)
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w") as f:
                json.dump(out, f, indent=2)
            self.log("[JSON] Written", self.logic_cfg.filename_json)
        except Exception as e:
            self.log_error("[JSON] Overlay-Datei konnte nicht geschrieben werden", e)

    # -----------------------------------------------------------------------
    # Sensor-Reads
    # -----------------------------------------------------------------------
    @staticmethod
    def calc_dewpoint(temp_c, hum):
        a = 17.27
        b = 237.7
        alpha = ((a * temp_c) / (b + temp_c)) + math.log(hum / 100.0)
        return (b * alpha) / (a - alpha)

    def read_bme(self):
        try:
            if self.bme280_dome:
                t = round(self.bme280_dome.temperature, 1)
                h = round(self.bme280_dome.humidity, 1)
                p = round(self.bme280_dome.pressure, 1)
                d = round(self.calc_dewpoint(t, h), 1)
                self.data["bme_temp_dome"] = t
                self.data["bme_hum_dome"] = h
                self.data["bme_pres_dome"] = p
                self.data["bme_dewp_dome"] = d
                if t is not None and -40 < t < 80:
                    self._last_valid_bme_dome_time = time.time()
        except Exception as e:
            self.log("[HARDW] BME Dome error:", e)

        try:
            if self.bme280_housing:
                t = round(self.bme280_housing.temperature, 1)
                h = round(self.bme280_housing.humidity, 1)
                p = round(self.bme280_housing.pressure, 1)
                d = round(self.calc_dewpoint(t, h), 1)
                self.data["bme_temp_housing"] = t
                self.data["bme_hum_housing"] = h
                self.data["bme_pres_housing"] = p
                self.data["bme_dewp_housing"] = d
        except Exception as e:
            self.log("[HARDW] BME Housing error:", e)

    def read_tsl(self):
        try:
            if not self.tsl2591:
                return
            lux = self.tsl2591.lux
            ir = self.tsl2591.infrared
            full = self.tsl2591.full_spectrum
            vis = self.tsl2591.visible

            self.data["tsl_lux"] = round(lux, 1) if lux is not None else 0.0
            self.data["tsl_infrared"] = round(ir, 1) if ir is not None else 0.0
            self.data["tsl_fullspectrum"] = round(full, 1) if full is not None else 0.0
            self.data["tsl_visible"] = round(vis, 1) if vis is not None else 0.0

            self.data["tsl_gainmultipl"] = self.gain_multiplier[self.tslgainindex]
            self.data["tsl_inttm"] = self.integration_time_ms[self.tslintmindex]
            self.data["tsl_gain_index"] = self.tslgainindex
            self.data["tsl_intmindex"] = self.tslintmindex

            self.tsl2591.gain = self.gains[self.tslgainindex]
            self.tsl2591.integration_time = self.integration_times[self.tslintmindex]

            self.tslluxaverage.append(self.data["tsl_lux"])
            self.tsliraverage.append(self.data["tsl_infrared"])

            # Autogain: bei zu wenig Signal erhöhen, bei Sättigung verringern
            if self.logic_cfg and getattr(self.logic_cfg, "tsl_autogain", True):
                high = getattr(self.logic_cfg, "tsl_high_threshold", 40000)
                low = getattr(self.logic_cfg, "tsl_low_threshold", 100)
                # Sättigung: full_spectrum oder Lux zu hoch → Gain/Integration verringern
                if (full is not None and full >= high) or (lux is not None and lux >= high):
                    if self.tslintmindex > 0:
                        self.tslintmindex -= 1
                    elif self.tslgainindex > 0:
                        self.tslgainindex -= 1
                    self.tslluxaverage.clear()
                    self.tsliraverage.clear()
                elif (
                    len(self.tslluxaverage) == self.tslluxaverage.maxlen
                    and len(self.tsliraverage) == self.tsliraverage.maxlen
                ):
                    luxavg = sum(self.tslluxaverage) / len(self.tslluxaverage)
                    iravg = sum(self.tsliraverage) / len(self.tsliraverage)
                    if luxavg < low and iravg < low:
                        if self.tslintmindex < len(self.integration_times) - 1:
                            self.tslintmindex += 1
                        elif self.tslgainindex < len(self.gains) - 1:
                            self.tslgainindex += 1
                        self.tslluxaverage.clear()
                        self.tsliraverage.clear()

        except Exception as e:
            self.data["tsl_lux"] = float(self.logic_cfg.tsl_saturation)
            self.data["tsl_infrared"] = float(self.logic_cfg.tsl_saturation)
            self.data["tsl_fullspectrum"] = 0.0
            self.data["tsl_visible"] = 0.0
            self.tslluxaverage.clear()
            self.tsliraverage.clear()
            self.tslgainindex = 0
            self.tslintmindex = 0
            if self.tsl2591:
                self.tsl2591.gain = self.gains[self.tslgainindex]
                self.tsl2591.integration_time = self.integration_times[self.tslintmindex]
            self.log("[HARDW] TSL2591 error:", e)

    def read_ina(self):
        if not self.ina:
            return
        try:
            vbus = float(self.ina.voltage())
            # Current (mA): subtract zero offset (calibrated with heater+fan off)
            current_raw = float(self.ina.current())
            current = max(0.0, current_raw - self.ina_offset_current)
            # Power (mW) = V * I. INA226 misst Gesamtstrom (Heizung + Lüfter + Platine), nicht nur Heizung.
            pwr = vbus * current  # V * mA -> mW (1 V * 1 mA = 1 mW)

            self.data["ina_vbus"] = round(vbus, 3)
            self.data["ina_current"] = round(current, 2)
            self.data["ina_power"] = round(pwr, 2)
        except Exception as e:
            self.log("[HARDW] INA226 error:", e)
            # On error ensure keys exist so Influx write does not crash
            self.data.setdefault("ina_vbus", 0.0)
            self.data.setdefault("ina_current", 0.0)
            self.data.setdefault("ina_power", 0.0)



    def read_tcs(self):
        if not self.tcs:
            return
        try:
            ch = self.tcs.read_channels_dict()
            for name, val in ch.items():
                self.data[f"tcs_{name.lower()}"] = int(val)
            self.data["tcs_gain_index"] = self.tcs_gain_index
            self.data["tcs_atime_steps"] = self.tcs_atime_steps
            self.data["tcs_asat"] = int(self.tcs.last_asat)  # Analog saturation
            self.data["tcs_max_count"] = min(
                65535,
                (self.tcs_atime_steps + 1) * (self.tcs_astep + 1),
            )

            # Autogain: Gain 0..12, bei Bedarf auch Integration (atime) anpassen
            # TCS3448: max_count = (ATIME+1)*(ASTEP+1), max 65535
            # Zielbereich: 25–70 % von max_count (relative Schwellen, skaliert mit Integration)
            # Hysterese + Cooldown verhindern Springen
            if self.logic_cfg and getattr(self.logic_cfg, "tcs_autogain", True):
                atime_step = 10
                asat = self.tcs.last_asat

                asat_reduce = False
                if asat:
                    # ASAT kann von FD (Flicker) ausgelöst werden, auch wenn Spektralkanäle OK sind.
                    # Nur reduzieren, wenn Spektralsignal selbst hoch ist.
                    spectral_keys = [k for k in ch if "fd" not in k.lower()]
                    max_spectral = max((ch[k] for k in spectral_keys), default=0) if spectral_keys else 0
                    tcs_max_count = min(
                        65535,
                        (self.tcs_atime_steps + 1) * (self.tcs_astep + 1),
                    )
                    high = tcs_max_count * 0.70
                    high_cfg = getattr(self.logic_cfg, "tcs_high_threshold", 0)
                    if 0 < high_cfg <= tcs_max_count:
                        high = high_cfg
                    if max_spectral >= high:
                        asat_reduce = True
                        if self.tcs_gain_index > 0:
                            self.tcs_gain_index -= 1
                            self.tcs.set_gain(self.tcs_gain_index)
                            self.tcs_max_average.clear()
                            self.tcs_autogain_cooldown = 8
                        elif self.tcs_atime_steps >= atime_step:
                            self.tcs_atime_steps = max(1, self.tcs_atime_steps - atime_step)
                            self.tcs.set_integration_time(
                                self.tcs_atime_steps, self.tcs_astep
                            )
                            self.tcs_max_average.clear()
                            self.tcs_autogain_cooldown = 8

                if not asat_reduce:
                    # Nur Spektralkanäle (ohne FD)
                    spectral_keys = [k for k in ch if "fd" not in k.lower()]
                    max_val = max((ch[k] for k in spectral_keys), default=0) if spectral_keys else 0
                    self.tcs_max_average.append(max_val)

                    if self.tcs_autogain_cooldown > 0:
                        self.tcs_autogain_cooldown -= 1

                    if (
                        self.tcs_autogain_cooldown == 0
                        and len(self.tcs_max_average) == self.tcs_max_average.maxlen
                    ):
                        avg = sum(self.tcs_max_average) / len(self.tcs_max_average)
                        tcs_max_count = min(
                            65535,
                            (self.tcs_atime_steps + 1) * (self.tcs_astep + 1),
                        )
                        # Relative Schwellen: 25% und 70% von max_count (Zielband 25–70%)
                        low = tcs_max_count * 0.25
                        high = tcs_max_count * 0.70
                        high_cfg = getattr(self.logic_cfg, "tcs_high_threshold", 0)
                        low_cfg = getattr(self.logic_cfg, "tcs_low_threshold", 0)
                        if 0 < high_cfg <= tcs_max_count:
                            high = high_cfg
                        if 0 < low_cfg < high:
                            low = low_cfg

                        if avg >= high:
                            if self.tcs_gain_index > 0:
                                self.tcs_gain_index -= 1
                                self.tcs.set_gain(self.tcs_gain_index)
                                self.tcs_max_average.clear()
                                self.tcs_autogain_cooldown = 6
                            elif self.tcs_atime_steps >= atime_step:
                                self.tcs_atime_steps = max(
                                    1, self.tcs_atime_steps - atime_step
                                )
                                self.tcs.set_integration_time(
                                    self.tcs_atime_steps, self.tcs_astep
                                )
                                self.tcs_max_average.clear()
                                self.tcs_autogain_cooldown = 6
                        elif avg < low:
                            if self.tcs_gain_index < 12:
                                self.tcs_gain_index += 1
                                self.tcs.set_gain(self.tcs_gain_index)
                                self.tcs_max_average.clear()
                                self.tcs_autogain_cooldown = 6
                            elif self.tcs_atime_steps < 255:
                                self.tcs_atime_steps = min(
                                    255,
                                    self.tcs_atime_steps + atime_step,
                                )
                                self.tcs.set_integration_time(
                                    self.tcs_atime_steps, self.tcs_astep
                                )
                                self.tcs_max_average.clear()
                                self.tcs_autogain_cooldown = 6
        except Exception as e:
            self.log("[HARDW] TCS3448 error:", e)

    def read_as3935_poll(self):
        """AS3935 Blitz: Polling-Fallback falls GPIO-Interrupt nicht funktioniert."""
        if not self.as3935:
            return
        try:
            reason = self.as3935.get_interrupt()
            if reason in (0x08, 0x04):  # 0x08=Lightning, 0x04=Disturber (Test)
                self.lightning_count += 1
                self.last_distance = self.as3935.get_distance()
                self.last_energy = self.as3935.get_energy()
                self.data["as_lightning_count"] = self.lightning_count
                self.data["as_last_distance"] = self.last_distance
                self.data["as_last_energy"] = self.last_energy
                evt = "Lightning" if reason == 0x08 else "Disturber"
                self.log(f"[AS3935] {evt} #{self.lightning_count} dist={self.last_distance} energy={self.last_energy}")
        except Exception as e:
            self.log("[HARDW] AS3935 poll error:", e)

    def read_pi_status(self):
        # CPU temperature (vcgencmd)
        try:
            out = subprocess.check_output(["vcgencmd", "measure_temp"]).decode()
            self.data["pi_cpu_temp"] = round(
                float(out.replace("temp=", "").replace("'C\n", "").strip()), 1
            )
        except Exception:
            pass

        # Disk usage % (root filesystem)
        try:
            st = os.statvfs("/")
            total_blocks = st.f_blocks * st.f_frsize
            free_blocks = st.f_bavail * st.f_frsize
            used_pct = 100.0 - (free_blocks / total_blocks * 100.0) if total_blocks else 0.0
            self.data["pi_disk_percent"] = round(used_pct, 1)
        except Exception:
            pass

        # Memory usage % from /proc/meminfo
        try:
            with open("/proc/meminfo") as f:
                lines = f.read()
            total = _parse_meminfo(lines, "MemTotal:")
            available = _parse_meminfo(lines, "MemAvailable:")
            if total and total > 0:
                self.data["pi_mem_percent"] = round((1.0 - available / total) * 100.0, 1)
            else:
                self.data["pi_mem_percent"] = 0.0
        except Exception:
            pass

        # CPU usage % from /proc/stat (delta since last call)
        try:
            with open("/proc/stat") as f:
                cpu_line = f.readline()  # "cpu  user nice system idle ..."
            parts = cpu_line.split()
            if parts[0] == "cpu" and len(parts) >= 5:
                user = int(parts[1])
                nice = int(parts[2])
                system = int(parts[3])
                idle = int(parts[4])
                iowait = int(parts[5]) if len(parts) > 5 else 0
                total = user + nice + system + idle + iowait
                now = time.time()
                if self._cpu_stat_prev is not None and self._cpu_stat_time_prev is not None:
                    dt = now - self._cpu_stat_time_prev
                    if dt >= 0.5:
                        prev_total, prev_idle = self._cpu_stat_prev
                        d_total = total - prev_total
                        d_idle = idle - prev_idle
                        if d_total > 0:
                            self.data["pi_cpu_usage"] = round(
                                (1.0 - d_idle / d_total) * 100.0, 1
                            )
                        else:
                            self.data["pi_cpu_usage"] = 0.0
                self._cpu_stat_prev = (total, idle)
                self._cpu_stat_time_prev = now
            else:
                self.data.setdefault("pi_cpu_usage", 0.0)
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # Read all sensors (central)
    # -----------------------------------------------------------------------
    def read_all_sensors(self):
        """Read all sensors in sequence and write results to self.data."""
        self.read_bme()
        self.read_tsl()
        self.read_ina()
        self.read_tcs()
        self.read_as3935_poll()
        self.read_pi_status()

    # -----------------------------------------------------------------------
    # Console output (formatted, block-style)
    # -----------------------------------------------------------------------
    def print_sensor_data(self):
        """Print all sensor values formatted to the console."""
        d = self.data
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sep = "  " + "-" * 58

        lines = [sep, f"  Heater+ Sensors  {ts}", sep]

        # BME280 Dome
        if self.bme280_dome and any(k in d for k in ("bme_temp_dome", "bme_hum_dome")):
            t = d.get("bme_temp_dome", "--")
            h = d.get("bme_hum_dome", "--")
            p = d.get("bme_pres_dome", "--")
            dp = d.get("bme_dewp_dome", "--")
            lines.append(f"  BME280 Dome     Temp: {t} °C   Humidity: {h} %   Pressure: {p} hPa   Dewpoint: {dp} °C")
        else:
            lines.append("  BME280 Dome     -- (not available)")

        # BME280 Housing
        if self.bme280_housing and any(k in d for k in ("bme_temp_housing", "bme_hum_housing")):
            t = d.get("bme_temp_housing", "--")
            h = d.get("bme_hum_housing", "--")
            p = d.get("bme_pres_housing", "--")
            dp = d.get("bme_dewp_housing", "--")
            lines.append(f"  BME280 Housing  Temp: {t} °C   Humidity: {h} %   Pressure: {p} hPa   Dewpoint: {dp} °C")
        else:
            lines.append("  BME280 Housing  -- (not available)")

        # TSL2591 (inkl. Gain und Integrationszeit)
        if self.tsl2591:
            def _v(k, default="--"):
                v = d.get(k, default)
                return v if v is not None else default
            lux = _v("tsl_lux")
            ir = _v("tsl_infrared")
            fs = _v("tsl_fullspectrum")
            vis = _v("tsl_visible")
            gidx = _v("tsl_gain_index")
            gmul = _v("tsl_gainmultipl")
            intms = _v("tsl_inttm")
            lines.append(f"  TSL2591         Lux: {lux}   IR: {ir}   Full: {fs}   Vis: {vis}   |   Gain: {gidx} ({gmul}x)   Int: {intms} ms")
        else:
            lines.append("  TSL2591         -- (not available)")

        # INA226 (Strom/Leistung = gesamte Versorgung: Heizung + Lüfter + Platine, nicht nur Heizung)
        if self.ina and "ina_vbus" in d:
            v = d.get("ina_vbus", "--")
            i = d.get("ina_current", "--")
            pwr = d.get("ina_power", "--")
            lines.append(f"  INA226          Vbus: {v} V   Strom: {i} mA   Leistung: {pwr} mW (Gesamtversorgung)")
        else:
            lines.append("  INA226          -- (not available)")

        # TCS3448 (Gain, ggf. Atime, dann alle Kanäle)
        if self.tcs:
            gain_idx = d.get("tcs_gain_index", "--")
            atime = getattr(self, "tcs_atime_steps", None)
            ch_keys = sorted(
                k
                for k in d.keys()
                if k.startswith("tcs_")
                and k not in ("tcs_gain_index", "tcs_atime_steps", "tcs_asat", "tcs_max_count")
            )
            if ch_keys:
                gain_atime = f"Gain: {gain_idx}"
                if atime is not None:
                    gain_atime += f"  Atime: {atime}"
                parts = [f"{k.replace('tcs_','')}={d[k]}" for k in ch_keys]
                lines.append("  TCS3448         " + gain_atime + "  |  " + "  ".join(parts))
            else:
                lines.append(f"  TCS3448         Gain: {gain_idx}  -- (no data)")
        else:
            lines.append("  TCS3448         -- (not available)")

        # Raspberry Pi (rpi_status)
        pi_parts = []
        if "pi_cpu_temp" in d:
            pi_parts.append(f"Temp: {d['pi_cpu_temp']} °C")
        if "pi_disk_percent" in d:
            pi_parts.append(f"Disk: {d['pi_disk_percent']} %")
        if "pi_mem_percent" in d:
            pi_parts.append(f"Mem: {d['pi_mem_percent']} %")
        if "pi_cpu_usage" in d:
            pi_parts.append(f"CPU: {d['pi_cpu_usage']} %")
        if pi_parts:
            lines.append("  Pi (rpi_status)  " + "   ".join(pi_parts))
        else:
            lines.append("  Pi (rpi_status)  --")

        # AS3935 (lightning)
        if self.as3935:
            cnt = d.get("as_lightning_count", 0)
            dist = d.get("as_last_distance", "--")
            energy = d.get("as_last_energy", "--")
            lines.append(f"  AS3935          Lightning: {cnt}   Last distance: {dist} km   Energy: {energy}")
        else:
            lines.append("  AS3935          -- (not available)")

        # Heater/Fan only in normal mode
        if not self.logic_cfg.sensor_only and (self.heater or self.fan):
            lines.append(sep)
            lines.append(f"  Setpoint: {d.get('heaterplus_settemp', '--')} °C   Heater: {d.get('heater_duty', '--')} %   Fan: {d.get('fan_duty', '--')} %")

        lines.append(sep)
        print("\n".join(lines))

    # -----------------------------------------------------------------------
    # Lightning interrupt handling
    # -----------------------------------------------------------------------
    def handle_irq(self):
        if not self.as3935:
            return
        reason = self.as3935.get_interrupt()
        if reason in (0x08, 0x04):
            self.lightning_count += 1
            self.last_distance = self.as3935.get_distance()
            self.last_energy = self.as3935.get_energy()
            self.data["as_lightning_count"] = self.lightning_count
            self.data["as_last_distance"] = self.last_distance
            self.data["as_last_energy"] = self.last_energy

    # -----------------------------------------------------------------------
    # Heater/Fan control
    # -----------------------------------------------------------------------
    def update_setpoint(self):
        t = self.data.get("bme_temp_dome", None)
        d = self.data.get("bme_dewp_dome", None)
        if self.logic_cfg.set_to_dewpoint and t is not None and d is not None:
            sp = d + self.logic_cfg.delta_dewpoint
        else:
            sp = self.logic_cfg.temp_set
        if self.pid is not None:
            self.pid.setpoint = sp
        self.control_temp = t if t is not None else sp
        self.data["heaterplus_settemp"] = round(sp, 1)
        self.data["heaterplus_controltemp"] = round(self.control_temp, 1)

    def apply_pid(self):
        self.data["heater_safety_temp"] = False
        self.data["heater_safety_sensor"] = False
        self.data["heater_fault"] = self._heater_fault

        # BME Dome fehlt/deaktiviert: Heizung aus (sonst ohne Temperaturrückmeldung gefährlich)
        if (
            not self.logic_cfg.sensor_only
            and self.logic_cfg.enable_dewheater
            and not self.bme280_dome
        ):
            self.heater_duty = 0.0
            self.data["heater_safety_sensor"] = True
            self.log("[Safety] Heizung aus: BME Dome nicht angeschlossen oder deaktiviert (bme280_dome_address=0).")

        # Sensor-Ausfall: Heizung aus wenn BME Dome > X Sekunden keine gültige Temperatur liefert
        c = self.logic_cfg
        if (
            not self.logic_cfg.sensor_only
            and self.bme280_dome
            and c.sensor_fault_timeout_sec > 0
        ):
            now = time.time()
            if self._last_valid_bme_dome_time is None:
                self._last_valid_bme_dome_time = now  # Erster Start: noch keine Lesung
            if now - self._last_valid_bme_dome_time > c.sensor_fault_timeout_sec:
                self.heater_duty = 0.0
                self.data["heater_safety_sensor"] = True
                self.log(
                    "[Safety] Heizung aus: BME Dome seit",
                    round(now - self._last_valid_bme_dome_time, 1),
                    "s keine gültige Temperatur (sensor_fault_timeout_sec=",
                    c.sensor_fault_timeout_sec,
                    ")",
                )

        if not self.data.get("heater_safety_sensor"):
            if not self.pid or not self.logic_cfg.enable_dewheater:
                self.heater_duty = 0.0
            else:
                output = self.pid(self.control_temp)
                # Annäherungszone: Heizung drosseln kurz vor Sollwert, reduziert Overshoot
                band = self.logic_cfg.pid_proximity_band
                if band > 0 and self.control_temp is not None:
                    sp = self.pid.setpoint
                    err = sp - self.control_temp  # positiv = unter Sollwert
                    if 0 < err < band:
                        scale = 0.5 + 0.5 * (err / band)
                        output *= scale
                self.heater_duty = max(0.0, min(100.0, output))

        # Sicherheit: Temp-Obergrenze Dome (Überhitzung vermeiden)
        c = self.logic_cfg
        if c.temp_max_dome > 0:
            t_dome = self.data.get("bme_temp_dome")
            if t_dome is not None and t_dome >= c.temp_max_dome:
                self.heater_duty = 0.0
                self.data["heater_safety_temp"] = True
                self.log("[Safety] Heizung aus: Dome-Temperatur", t_dome, ">= temp_max_dome", c.temp_max_dome)

        # Sicherheit: Heizer-Leistungsprüfung (Strom muss steigen wenn Heizung an)
        if c.heater_power_check and self.ina and not self.logic_cfg.sensor_only:
            current = self.data.get("ina_current")
            if current is not None:
                idle = self.ina_offset_current
                above_idle = current - idle
                if self.heater_duty >= c.heater_duty_min_for_check:
                    if above_idle < c.heater_min_current_above_idle:
                        self._heater_low_current_cycles += 1
                        if self._heater_low_current_cycles >= c.heater_fault_cycles:
                            if not self._heater_fault:
                                self._heater_fault = True
                                self.log("[Safety] Heizer-Fehler: Leistung steigt nicht bei Duty", self.heater_duty, "%; Strom", round(current, 1), "mA (erwartet >", round(idle + c.heater_min_current_above_idle, 1), "mA)")
                            self.heater_duty = 0.0
                    else:
                        self._heater_low_current_cycles = 0
                    self._heater_ok_cycles = 0
                else:
                    self._heater_low_current_cycles = 0
                    if self._heater_fault:
                        self._heater_ok_cycles += 1
                        if self._heater_ok_cycles >= 5:
                            self._heater_fault = False
                            self._heater_ok_cycles = 0
                            self.log("[Safety] Heizer-Fehler zurückgesetzt (Duty war 0)")
        if self._heater_fault:
            self.heater_duty = 0.0

        self.data["heater_duty"] = round(self.heater_duty, 1)
        if self.heater:
            self.heater.value = self.heater_duty / 100.0

    def update_fan(self):
        if not self.logic_cfg.enable_fan:
            self.fan_duty = 0.0
        else:
            td = self.data.get("bme_temp_dome")
            th = self.data.get("bme_temp_housing")
            # Nur auswerten wenn beide Sensoren gültige Werte haben (nicht None, sinnvoll 0..60°C)
            if td is not None and th is not None and 0 < td < 80 and 0 < th < 80:
                if td >= th + self.logic_cfg.delta_cooling:
                    self.fan_duty = 100.0
                else:
                    self.fan_duty = 0.0
            else:
                self.fan_duty = 0.0  # Bei fehlenden/unplausiblen Werten: Lüfter aus

        prev = self.data.get("fan_duty", -1)
        self.data["fan_duty"] = round(self.fan_duty, 1)
        if self.fan:
            self.fan.value = self.fan_duty / 100.0
        if prev != self.data["fan_duty"] and self.fan:
            self.log("[Fan] Duty:", self.data["fan_duty"], "% (Dome:", self.data.get("bme_temp_dome"), "°C, Housing:", self.data.get("bme_temp_housing"), "°C, delta_cooling:", self.logic_cfg.delta_cooling, ")")

    # -----------------------------------------------------------------------
    # Main Loop
    # -----------------------------------------------------------------------
    def loop(self):
        last_db = 0
        while self.running and self.logic_cfg.run:
            try:
                self.check_and_reload_settings()
                t0 = time.time()

                self.read_all_sensors()

                if self.logic_cfg.sensor_only:
                    # Nur Sensoren: JSON/DB trotzdem periodisch (Overlay + optional DB)
                    self.print_sensor_data()
                    if time.time() - last_db >= self.logic_cfg.upd_interval_db:
                        if self.logic_cfg.send_to_db and self.db_connected:
                            self.influxdb_write()
                        self.json_write()
                        last_db = time.time()
                else:
                    self.update_setpoint()
                    self.apply_pid()
                    self.update_fan()
                    self.print_sensor_data()

                    if time.time() - last_db >= self.logic_cfg.upd_interval_db:
                        self.influxdb_write()
                        self.json_write()
                        last_db = time.time()

                dt = time.time() - t0
                sleep_time = max(0.0, self.logic_cfg.upd_interval_sensor - dt)
                time.sleep(sleep_time)
            except Exception as e:
                self.log_error("[Loop] Unerwarteter Fehler (Zyklus wird fortgesetzt)", e)
                time.sleep(max(1.0, float(self.logic_cfg.upd_interval_sensor)))

    # -----------------------------------------------------------------------
    # Exit (Graceful Shutdown)
    # -----------------------------------------------------------------------
    def exit_script(self, *args):
        if self._exit_done:
            return
        self._exit_done = True
        self.running = False

        # Graceful Shutdown: Heizung über Rampe ausschalten (weniger Spannungsspitzen, schonender)
        ramp_sec = getattr(self.logic_cfg, "shutdown_heater_ramp_sec", 1.5)
        if ramp_sec > 0 and self.heater and self.heater_duty > 0:
            steps = max(5, int(ramp_sec * 10))
            step_time = ramp_sec / steps
            start_duty = self.heater_duty
            for i in range(1, steps + 1):
                duty = max(0.0, start_duty * (1.0 - i / steps))
                self.heater.value = duty / 100.0
                time.sleep(step_time)
            self.log("[Exit] Heizung rampenweise ausgeschaltet (", round(ramp_sec, 1), "s)")
        if self.heater:
            self.heater.value = 0.0
        if self.fan:
            self.fan.value = 0.0

        self.influxdb_close()
        if self._log_file:
            try:
                self._log_file.close()
            except Exception:
                pass
            self._log_file = None
        self.log("[Exit] HeaterPlusController stopped.")
        sys.exit(0)


if __name__ == "__main__":
    ctrl = HeaterPlusController()
    ctrl.load_settings()
    ctrl.validate_settings()
    if ctrl.logic_cfg.log_file:
        try:
            ctrl._log_file = open(ctrl.logic_cfg.log_file, "a", encoding="utf-8")
        except Exception as e:
            print("[Log] Konnte Logdatei nicht öffnen:", ctrl.logic_cfg.log_file, e)
    ctrl.setup_hardware()
    # Optional: Lüfter kurz testen (hp_settings.json: "fan_test_sec": 3)
    with open(ctrl.settings_path) as f:
        _s = json.load(f)
    fan_test = float(_s.get("fan_test_sec", 0))
    if fan_test > 0 and ctrl.fan:
        print(f"[Init] Lüfter-Test {fan_test}s (100%)...")
        ctrl.fan.value = 1.0
        time.sleep(fan_test)
        ctrl.fan.value = 0.0
        print("[Init] Lüfter aus.")
    # Zero INA226 with heater off so current/power read ~0 when idle
    ctrl.calibrate_ina_zero(settle_sec=2.0, samples=10)
    ctrl.setup_signals()

    if ctrl.logic_cfg.sensor_only:
        print("[Heater+] Mode: Sensors only (sensor_only=true). Press Ctrl+C to exit.\n")
        ctrl.loop()
    else:
        ctrl.setup_pid()
        ctrl.influxdb_connect()
        ctrl.loop()
