#!/usr/bin/env python3
import time
import traceback

import board
import busio
from gpiozero import PWMOutputDevice, Button
from tcs3448 import TCS3448

# BME280
from adafruit_bme280 import basic as adafruit_bme280

# TSL2591
import adafruit_tsl2591

# INA226 (pi_ina226)
from ina226 import INA226

# AS3935 (RaspberryPi-AS3935)
from RPi_AS3935.RPi_AS3935 import RPi_AS3935





# ----------------- Addresses and pins -----------------
ADDR_BME_DOME = 0x77
ADDR_BME_HOUSING = 0x76
ADDR_TSL2591 = 0x29
ADDR_TCS3448 = 0x59
ADDR_AS3935 = 0x03

# Adjust to i2cdetect output if needed: 0x40/0x41/0x44/0x45
ADDR_INA226 = 0x40

AS3935_IRQ_PIN = 22      # BCM
HEATER_PWM_PIN = 18      # BCM

INA226_SHUNT_OHMS = 0.025  # 25 mOhm shunt


def main():
    i2c = busio.I2C(board.SCL, board.SDA)

    bme_dome = None
    bme_housing = None
    tsl = None
    tcs = None
    ina = None
    as3935 = None
    as_irq_button = None
    heater = None

    print("=== Initializing I2C sensors and heater ===")

    # BME280 Dome
    try:
        bme_dome = adafruit_bme280.Adafruit_BME280_I2C(i2c, address=ADDR_BME_DOME)
        bme_dome.sea_level_pressure = 1013.25
        print("[OK] BME280 Dome @ 0x{:02X}".format(ADDR_BME_DOME))
    except Exception as e:
        print("[ERR] BME280 Dome:", e)
        print(traceback.format_exc())

    # BME280 Housing
    try:
        bme_housing = adafruit_bme280.Adafruit_BME280_I2C(i2c, address=ADDR_BME_HOUSING)
        bme_housing.sea_level_pressure = 1013.25
        print("[OK] BME280 Housing @ 0x{:02X}".format(ADDR_BME_HOUSING))
    except Exception as e:
        print("[ERR] BME280 Housing:", e)
        print(traceback.format_exc())

    # TSL2591
    try:
        tsl = adafruit_tsl2591.TSL2591(i2c)
        print("[OK] TSL2591 @ 0x{:02X}".format(ADDR_TSL2591))
    except Exception as e:
        print("[ERR] TSL2591:", e)
        print(traceback.format_exc())

    # INA226
    try:
        ina = INA226(
            address=ADDR_INA226,
            shunt_ohms=INA226_SHUNT_OHMS,
            max_expected_amps=1.0,   # Headroom over ~0.5 A heater current
            busnum=1,
        )
        ina.configure()
        print("[OK] INA226 @ 0x{:02X}, Shunt={:.3f} ohm".format(ADDR_INA226, INA226_SHUNT_OHMS))
    except Exception as e:
        print("[ERR] INA226:", e)
        print(traceback.format_exc())

    # AS3935 + IRQ
    try:
        as3935 = RPi_AS3935(address=ADDR_AS3935, bus=1)
        as3935.set_indoors(True)
        as3935.set_noise_floor(0)
        as3935.set_min_strikes(1)
        as3935.calibrate()
        as_irq_button = Button(AS3935_IRQ_PIN, pull_up=False)


        def as_irq_handler():
            print("interrupt")
            try:
                reason = as3935.get_interrupt()
                if reason == 0x01:
                    print("[AS3935] Noise level too high")
                elif reason == 0x04:
                    print("[AS3935] Disturber detected")
                elif reason == 0x08:
                    dist = as3935.get_distance()
                    print(f"[AS3935] Lightning detected! Distance: {dist} km")
                else:
                    print(f"[AS3935] Unknown interrupt: 0x{reason:02X}")
            except Exception as ex:
                print("[AS3935] IRQ error:", ex)
                print(traceback.format_exc())

        as_irq_button.when_pressed = as_irq_handler
        print("[OK] AS3935 @ 0x{:02X}, IRQ Pin BCM {}".format(ADDR_AS3935, AS3935_IRQ_PIN))
    except Exception as e:
        print("[ERR] AS3935:", e)
        print(traceback.format_exc())

    # TCS3448
    try:
        tcs = TCS3448(
            i2c,
            address=0x59,
            atime_steps=29,  # ~50 ms at ASTEP=599
            astep=599,
            gain_index=8,    # ~128x gain
        )
        print("[OK] TCS3448 @ 0x59")
    except Exception as e:
        print("[ERR] TCS3448:", e)
        print(traceback.format_exc())
        tcs = None


    # Heater PWM on GPIO18
    try:
        heater = PWMOutputDevice(HEATER_PWM_PIN, frequency=10000, initial_value=0.0)
        print("[OK] Heater PWM on GPIO{}".format(HEATER_PWM_PIN))
    except Exception as e:
        print("[ERR] Heater PWM:", e)
        print(traceback.format_exc())

    print("\n=== Heater ramp-up test (0% -> 100%) ===")
    print("Each step: 5 s, measurements during. Press Ctrl+C to abort.\n")

    try:
        for step in range(0, 11):
            duty = step / 10.0  # 0.0, 0.1, ..., 1.0
            if heater:
                heater.value = duty

            print("----")
            print(f"Heater Duty: {duty*100:4.0f} %")

            # Short measurement loop per step
            for _ in range(5):
                # BME Dome
                if bme_dome:
                    try:
                        t = bme_dome.temperature
                        h = bme_dome.humidity
                        p = bme_dome.pressure
                        print(f"  BME Dome:     {t:5.1f} °C, {h:5.1f} %, {p:7.1f} hPa")
                    except Exception as e:
                        print("  [ERR] Read BME Dome:", e)

                # BME Housing
                if bme_housing:
                    try:
                        t = bme_housing.temperature
                        h = bme_housing.humidity
                        p = bme_housing.pressure
                        print(f"  BME Housing:  {t:5.1f} °C, {h:5.1f} %, {p:7.1f} hPa")
                    except Exception as e:
                        print("  [ERR] Read BME Housing:", e)

                # TSL2591
                if tsl:
                    try:
                        lux = tsl.lux
                        ir = tsl.infrared
                        fs = tsl.full_spectrum
                        vis = tsl.visible
                        print(f"  TSL2591:      lux={lux:8.1f}, IR={ir:8.1f}, FS={fs:8.1f}, VIS={vis:8.1f}")
                    except Exception as e:
                        print("  [ERR] Read TSL2591:", e)

                # INA226
                if ina:
                    try:
                        v = ina.voltage()
                        i = ina.current() / 1000
                        pwr = ina.power() / 1000
                        print(f"  INA226:       Vbus={v:6.3f} V, I={i:6.3f} A, P={pwr:6.3f} W")
                    except Exception as e:
                        print("  [ERR] Read INA226:", e)

                # TCS3448 (raw channels)
                if tcs:
                    try:
                        ch_dict = tcs.read_channels_dict()
                        tcs_str = ", ".join(f"{name}={val:5d}" for name, val in ch_dict.items())
                    except Exception as e:
                        tcs_str = f"ERR: {e}"
                else:
                    tcs_str = "n/a"

                print(f"  TCS3448:      {tcs_str}")


                print("  (AS3935 interrupts are asynchronous when they occur)")
                time.sleep(1.0)

        print("\nRamp-up complete. Heater switched off.")
    except KeyboardInterrupt:
        print("\nAborted by user.")
    finally:
        if heater:
            heater.value = 0.0
        print("Test script finished.")

if __name__ == "__main__":
    main()
