#!/usr/bin/env python3
"""Simple test for AS3935 lightning sensor – checks I2C, interrupt register and disturber."""
import time

def main():
    print("AS3935 test – hold phone or electrical device near antenna for disturber test.\n")
    try:
        from RPi_AS3935.RPi_AS3935 import RPi_AS3935
    except ImportError as e:
        print("Error: RPi_AS3935 not installed:", e)
        return 1

    addr = 0x03  # Standard address, adjust from hp_settings.json if needed
    bus = 1

    try:
        s = RPi_AS3935(address=addr, bus=bus)
        s.set_indoors(True)
        s.set_min_strikes(1)
        s.set_mask_disturber(False)
        s.calibrate()
        print("AS3935 init OK, address", hex(addr))
    except Exception as e:
        print("AS3935 init error:", e)
        return 1

    nf = s.get_noise_floor()
    print("Noise Floor:", nf, "(0–7, lower = more sensitive)")
    if nf > 2:
        print("  → Sensor less sensitive; trying lower_noise_floor() …")
        try:
            s.lower_noise_floor()
            print("  → Noise Floor now:", s.get_noise_floor())
        except Exception as e:
            print("  → Error:", e)

    print("\n20 sec polling – phone/power supply near antenna, or piezo lighter/petri dish:")
    print("(reason=0x08 Lightning, 0x04 Disturber; status every 5s)\n")
    for i in range(20):
        try:
            reason = s.get_interrupt()
            dist = s.get_distance()
            energy = s.get_energy()
            if reason:
                evt = {0x08: "Lightning", 0x04: "Disturber"}.get(reason, f"0x{reason:02x}")
                print(f"  [{i+1:2d}s] *** {evt} *** dist={dist} km, energy={energy}")
            elif (i + 1) % 5 == 0:
                print(f"  [{i+1:2d}s] reason={reason} dist={dist} energy={energy} (no event)")
        except Exception as e:
            print(f"  [{i+1:2d}s] Error:", e)
        time.sleep(1)

    print("\nTest finished.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
