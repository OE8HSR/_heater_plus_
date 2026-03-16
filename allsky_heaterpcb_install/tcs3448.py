"""
TCS3448 14-Channel Multi-Spectral Sensor (ams-OSRAM)
===================================================

Full-featured driver for the TCS3448. Datasheet DS001121 v1-01.

Implements all chip capabilities:
- ALS (Ambient Light Sensing): PON, ALS_EN, ATIME, ASTEP, AGAIN, auto_SMUX
- Wait time (WTIME) between measurements
- Interrupt system: ALS thresholds, persistence, INT pin
- Flicker detection (FD): FDEN, FD_STATUS, FDATA
- GPIO: sync/trigger input/output
- LED driver (LDR): LED_ACT, LED_DRIVE
- AGC (on-chip automatic gain control)
- Sleep after interrupt (SAI)
- Device identification (AUXID, REVID, ID)

Integration time: tint = (ATIME+1)*(ASTEP+1)*2.78 µs (Equation 1, datasheet)
Read ASTATUS (0x94) first to latch all 36 ALS bytes, then ADATA 0x95..0xB8.

Usage (basic ALS):
    from tcs3448 import TCS3448
    import busio, board
    i2c = busio.I2C(board.SCL, board.SDA)
    tcs = TCS3448(i2c, atime_steps=29, astep=599, gain_index=8)
    ch = tcs.read_channels_dict()
    if tcs.last_asat:
        tcs.set_gain(tcs.get_gain_index() - 1)  # Reduce on saturation
    tcs.power_down()

Usage (with wait time for low power):
    tcs = TCS3448(i2c, wtime=128, wait_enable=True)

Usage (flicker detection):
    tcs = TCS3448(i2c, flicker_enable=True)
    fd = tcs.read_fd_status()
"""

import time


class TCS3448:
    """Driver for ams-OSRAM TCS3448 14-channel multi-spectral sensor."""

    DEFAULT_I2C_ADDR = 0x59

    # -------------------------------------------------------------------------
    # Register addresses (datasheet Table 10)
    # -------------------------------------------------------------------------
    # Bank 0 (REG_BANK=0) - default
    REG_ENABLE = 0x80
    REG_ATIME = 0x81
    REG_WTIME = 0x83
    REG_ASTATUS = 0x94  # Read first to latch ALS data; contains ASAT_STATUS, AGAIN_STATUS
    REG_STATUS2 = 0x90
    REG_STATUS3 = 0x91
    REG_STATUS = 0x93  # STATUS: ASAT, AINT, FINT, SINT
    REG_CFG0 = 0xBF
    REG_CFG1 = 0xC6  # AGAIN[4:0]
    REG_CFG3 = 0xC7  # SAI (Sleep After Interrupt)
    REG_CFG20 = 0xD6  # FD_FIFO_8b, auto_SMUX
    REG_ASTEPS_L = 0xD4
    REG_ASTEPS_H = 0xD5
    REG_GPIO = 0x6B
    REG_LED = 0xCD
    REG_AGC_GAIN_MAX = 0xD7
    REG_AZ_CONFIG = 0xDE
    REG_FD_CFG0 = 0xDF
    REG_FD_TIME_1 = 0xE0
    REG_FD_TIME_2 = 0xE2
    REG_FD_STATUS = 0xE3
    REG_INTENAB = 0xF9
    REG_CONTROL = 0xFA
    REG_FIFO_MAP = 0xFC
    REG_FIFO_LVL = 0xFD
    REG_FDATA_L = 0xFE
    REG_FDATA_H = 0xFF

    # 16-bit registers (low byte, high byte)
    REG_ALS_TH_L_L = 0x84
    REG_ALS_TH_L_H = 0x85
    REG_ALS_TH_H_L = 0x86
    REG_ALS_TH_H_H = 0x87

    REG_ADATA0_L = 0x95
    REG_ADATA_COUNT = 18

    # Bank 1 (REG_BANK=1 in CFG0) - for 0x58..0x66
    REG_AUXID = 0x58
    REG_REVID = 0x59
    REG_ID = 0x5A
    REG_CFG12 = 0x66  # ALS_TH_CH
    REG_CFG10 = 0x65  # FD_PERS
    REG_CFG8 = 0xC9   # FIFO_TH
    REG_CFG9 = 0xCA   # SIEN_FD, SIEN_SMUX
    REG_PERS = 0xCF
    REG_STATUS4 = 0xBC
    REG_STATUS5 = 0xBB

    # -------------------------------------------------------------------------
    # ENABLE (0x80) bits
    # -------------------------------------------------------------------------
    ENABLE_PON = 0x01      # Power on
    ENABLE_ALS_EN = 0x02   # ALS enable
    ENABLE_WEN = 0x08      # Wait enable (WTIME between measurements)
    ENABLE_SMUXEN = 0x10   # SMUX enable (required for multi-channel)
    ENABLE_FDEN = 0x20     # Flicker detection enable

    # -------------------------------------------------------------------------
    # STATUS2 (0x90) bits
    # -------------------------------------------------------------------------
    STATUS2_AVALID = 0x40    # Bit 6: ALS data valid
    STATUS2_ASAT_DIG = 0x20  # Digital saturation
    STATUS2_ASAT_ANA = 0x10  # Analog saturation (ALS)
    STATUS2_FDSAT_ANA = 0x08
    STATUS2_FDSAT_DIG = 0x04

    # -------------------------------------------------------------------------
    # ASTATUS (0x94) bits - read when latching ADATA
    # -------------------------------------------------------------------------
    ASTATUS_ASAT = 0x80  # Bit 7: Analog saturation flag
    ASTATUS_AGAIN_MASK = 0x0F  # Bits [3:0]: AGAIN_STATUS

    # -------------------------------------------------------------------------
    # STATUS (0x93) bits
    # -------------------------------------------------------------------------
    STATUS_ASAT = 0x80
    STATUS_AINT = 0x40  # ALS interrupt
    STATUS_FINT = 0x20  # Flicker interrupt
    STATUS_SINT = 0x10  # System interrupt

    # -------------------------------------------------------------------------
    # FD_STATUS (0xE3) bits
    # -------------------------------------------------------------------------
    FD_STATUS_VALID = 0x80
    FD_STATUS_SAT = 0x40
    FD_STATUS_120_VALID = 0x20
    FD_STATUS_100_VALID = 0x10
    FD_STATUS_120HZ = 0x04
    FD_STATUS_100HZ = 0x01

    # -------------------------------------------------------------------------
    # CFG0 (0xBF) bits
    # -------------------------------------------------------------------------
    CFG0_REG_BANK = 0x20   # 1 = access 0x58..0x66
    CFG0_LOW_POWER = 0x10
    CFG0_WLONG = 0x02     # 2.78 ms vs 2.78 ms * 12 for wait

    # -------------------------------------------------------------------------
    # INTENAB (0xF9) bits
    # -------------------------------------------------------------------------
    INTENAB_ASIEN = 0x80   # ALS saturation interrupt
    INTENAB_ALS_IEN = 0x40 # ALS threshold interrupt
    INTENAB_FIEN = 0x20   # Flicker interrupt
    INTENAB_SIEN = 0x10   # System interrupt

    # -------------------------------------------------------------------------
    # CONTROL (0xFA) bits - write to clear/trigger
    # -------------------------------------------------------------------------
    CONTROL_SW_RESET = 0x80
    CONTROL_ALS_MAN_AZ = 0x40  # Manual auto-zero
    CONTROL_FIFO_CLR = 0x20
    CONTROL_CLEAR_SAI_ACT = 0x08

    # -------------------------------------------------------------------------
    # GPIO (0x6B) bits
    # -------------------------------------------------------------------------
    GPIO_INV = 0x80
    GPIO_IN_EN = 0x40
    GPIO_OUT = 0x20
    GPIO_IN = 0x10  # read: current input state

    # -------------------------------------------------------------------------
    # LED (0xCD) bits
    # -------------------------------------------------------------------------
    LED_ACT = 0x80   # LED driver active
    LED_DRIVE_MASK = 0x7F  # LED_DRIVE[6:0]

    # -------------------------------------------------------------------------
    # ADATA channel map (auto_SMUX mode 3, datasheet Table 46)
    # -------------------------------------------------------------------------
    ADATA_MAP = {
        0: "FZ", 1: "FY", 2: "FXL", 3: "NIR", 4: "VIS", 5: "FD",
        6: "F2", 7: "F3", 8: "F4", 9: "F6", 10: "VIS2", 11: "FD2",
        12: "F1", 13: "F7", 14: "F8", 15: "F5", 16: "VIS3", 17: "FD3",
    }

    def __init__(
        self,
        i2c,
        address=DEFAULT_I2C_ADDR,
        atime_steps=29,
        astep=599,
        gain_index=8,
        wtime=0,
        wait_enable=False,
        flicker_enable=False,
        auto_smux=3,
    ):
        """
        Initialize TCS3448.

        Args:
            i2c: busio.I2C object
            address: I2C address (default 0x59)
            atime_steps: ATIME 0..255 (integration steps)
            astep: ASTEP 0..65535 (step size 2.78 µs)
            gain_index: AGAIN 0..12 (0.5x..2048x)
            wtime: WTIME 0..255 (wait time multiplier, 0=disabled)
            wait_enable: Enable WEN for low-power wait between measurements
            flicker_enable: Enable FDEN for flicker detection
            auto_smux: 0=6ch, 2=12ch, 3=18ch (default 3)

        Integration: tint = (ATIME+1)*(ASTEP+1)*2.78 µs
        """
        self.i2c = i2c
        self.address = address
        self._reg_bank = 0

        # Power off first
        self._write_u8(self.REG_ENABLE, 0x00)

        self.set_integration_time(atime_steps, astep)
        self.set_gain(gain_index)
        self.set_auto_smux(auto_smux)
        self.set_wait_time(wtime, wait_enable)

        # Power on, ALS, SMUX (required for multi-channel), and optionally FD
        en = self.ENABLE_PON | self.ENABLE_ALS_EN | self.ENABLE_SMUXEN
        if flicker_enable:
            en |= self.ENABLE_FDEN
        self._write_u8(self.REG_ENABLE, en)

        time.sleep(0.01)
        self._last_astatus = 0

    # =========================================================================
    # Low-level I2C
    # =========================================================================

    def _write_u8(self, reg: int, value: int) -> None:
        """Write 8-bit value to register."""
        buf = bytes([reg & 0xFF, value & 0xFF])
        while not self.i2c.try_lock():
            pass
        try:
            self.i2c.writeto(self.address, buf)
        finally:
            self.i2c.unlock()

    def _read_u8(self, reg: int) -> int:
        """Read 8-bit value from register."""
        result = bytearray(1)
        while not self.i2c.try_lock():
            pass
        try:
            self.i2c.writeto(self.address, bytes([reg & 0xFF]))
            self.i2c.readfrom_into(self.address, result)
        finally:
            self.i2c.unlock()
        return result[0]

    def _write_u16_le(self, reg_low: int, value: int) -> None:
        """Write 16-bit value (low byte at reg_low, high at reg_low+1)."""
        value &= 0xFFFF
        self._write_u8(reg_low, value & 0xFF)
        self._write_u8(reg_low + 1, (value >> 8) & 0xFF)

    def _read_u16_le(self, reg: int) -> int:
        """Read 16-bit value (little-endian, low byte first)."""
        buf = bytearray(2)
        while not self.i2c.try_lock():
            pass
        try:
            self.i2c.writeto(self.address, bytes([reg & 0xFF]))
            self.i2c.readfrom_into(self.address, buf)
        finally:
            self.i2c.unlock()
        return buf[0] | (buf[1] << 8)

    def _set_reg_bank(self, bank: int) -> None:
        """Set REG_BANK (0 or 1) for accessing 0x58..0x66."""
        bank = 1 if bank else 0
        if self._reg_bank == bank:
            return
        cfg0 = self._read_u8(self.REG_CFG0)
        if bank:
            cfg0 |= self.CFG0_REG_BANK
        else:
            cfg0 &= ~self.CFG0_REG_BANK
        self._write_u8(self.REG_CFG0, cfg0)
        self._reg_bank = bank

    # =========================================================================
    # Device identification (requires REG_BANK=1)
    # =========================================================================

    def get_device_id(self) -> int:
        """Read ID register (0x5A). Expected 0x48 for TCS3448."""
        self._set_reg_bank(1)
        return self._read_u8(self.REG_ID)

    def get_revision(self) -> int:
        """Read REVID (0x59)."""
        self._set_reg_bank(1)
        return self._read_u8(self.REG_REVID) & 0x07

    def get_auxid(self) -> int:
        """Read AUXID (0x58)."""
        self._set_reg_bank(1)
        return self._read_u8(self.REG_AUXID) & 0x0F

    def verify_device(self) -> bool:
        """Return True if device ID matches TCS3448 (0x48)."""
        return self.get_device_id() == 0x48

    # =========================================================================
    # Power and enable
    # =========================================================================

    def power_down(self) -> None:
        """Power down (PON=0, ALS_EN=0)."""
        self._write_u8(self.REG_ENABLE, 0x00)

    def power_on(self, als=True, flicker=False, wait=False, smux=True) -> None:
        """Power on with optional ALS, FD, WEN, SMUX."""
        en = self.ENABLE_PON
        if als:
            en |= self.ENABLE_ALS_EN
        if flicker:
            en |= self.ENABLE_FDEN
        if wait:
            en |= self.ENABLE_WEN
        if smux:
            en |= self.ENABLE_SMUXEN
        self._write_u8(self.REG_ENABLE, en)

    # =========================================================================
    # Integration time and gain
    # =========================================================================

    def set_integration_time(self, atime_steps: int, astep: int) -> None:
        """
        Set integration time.

        tint = (ATIME + 1) * (ASTEP + 1) * 2.78 µs
        """
        atime_steps &= 0xFF
        astep &= 0xFFFF
        self._write_u8(self.REG_ASTEPS_L, astep & 0xFF)
        self._write_u8(self.REG_ASTEPS_H, (astep >> 8) & 0xFF)
        self._write_u8(self.REG_ATIME, atime_steps)

    def set_gain(self, again_index: int) -> None:
        """
        Set gain (AGAIN in CFG1). Value 0..12.

        0=0.5x, 1=1x, ..., 8=128x, ..., 12=2048x
        """
        again_index = max(0, min(12, int(again_index)))
        cfg1 = self._read_u8(self.REG_CFG1)
        cfg1 &= 0xE0
        cfg1 |= again_index
        self._write_u8(self.REG_CFG1, cfg1)

    def get_gain_index(self) -> int:
        """Read current AGAIN setting (0..12)."""
        return self._read_u8(self.REG_CFG1) & 0x1F

    # =========================================================================
    # Wait time
    # =========================================================================

    def set_wait_time(self, wtime: int, enable: bool = True) -> None:
        """
        Set wait time between ALS cycles. Reduces power when not measuring.

        wtime: 0..255. Wait = (256 - WTIME) * 2.78 ms (or * 12 with WLONG).
        enable: Set WEN in ENABLE to use wait.
        """
        wtime = max(0, min(255, int(wtime)))
        self._write_u8(self.REG_WTIME, wtime)
        if enable and wtime > 0:
            en = self._read_u8(self.REG_ENABLE)
            if en & self.ENABLE_PON:
                self._write_u8(self.REG_ENABLE, en | self.ENABLE_WEN)

    # =========================================================================
    # Auto SMUX
    # =========================================================================

    def set_auto_smux(self, mode: int) -> None:
        """
        Set auto_SMUX (CFG20 bits 6:5). 0=6ch, 2=12ch, 3=18ch.
        """
        mode &= 0x03
        cfg20 = self._read_u8(self.REG_CFG20)
        cfg20 &= ~(0b11 << 5)
        cfg20 |= (mode & 0b11) << 5
        self._write_u8(self.REG_CFG20, cfg20)

    # =========================================================================
    # ALS data
    # =========================================================================

    def data_ready(self) -> bool:
        """True if AVALID bit set (new ALS data available)."""
        return (self._read_u8(self.REG_STATUS2) & self.STATUS2_AVALID) != 0

    def wait_data_ready(self, timeout: float = 0.2) -> bool:
        """Block until AVALID or timeout (seconds)."""
        t0 = time.time()
        while not self.data_ready():
            if time.time() - t0 > timeout:
                return False
            time.sleep(0.005)
        return True

    def read_adata_raw(self) -> list:
        """
        Read ADATA0..ADATA17. Reads ASTATUS first to latch (updates _last_astatus).
        """
        self._last_astatus = self._read_u8(self.REG_ASTATUS)
        values = []
        for i in range(self.REG_ADATA_COUNT):
            reg = self.REG_ADATA0_L + 2 * i
            values.append(self._read_u16_le(reg))
        return values

    @property
    def last_asat(self) -> bool:
        """True if analog saturation in last ASTATUS read."""
        return (self._last_astatus & self.ASTATUS_ASAT) != 0

    @property
    def last_again_status(self) -> int:
        """AGAIN_STATUS[3:0] from last ASTATUS read."""
        return self._last_astatus & self.ASTATUS_AGAIN_MASK

    def read_channels_dict(self, wait: bool = True, timeout: float = 0.2) -> dict:
        """
        Read ALS data as {channel_name: value}. Optionally wait for AVALID.
        """
        if wait:
            self.wait_data_ready(timeout=timeout)
        raw = self.read_adata_raw()
        return {
            self.ADATA_MAP.get(i, f"ADATA{i}"): v
            for i, v in enumerate(raw)
        }

    # =========================================================================
    # Interrupts
    # =========================================================================

    def set_als_thresholds(self, low: int, high: int, channel: int = 0) -> None:
        """
        Set ALS interrupt thresholds. channel 0..7 selects ALS channel.
        """
        low &= 0xFFFF
        high &= 0xFFFF
        channel &= 0x07
        self._write_u16_le(self.REG_ALS_TH_L_L, low)
        self._write_u16_le(self.REG_ALS_TH_H_L, high)
        self._set_reg_bank(1)
        self._write_u8(self.REG_CFG12, channel)
        self._set_reg_bank(0)

    def set_als_persistence(self, apers: int) -> None:
        """Set ALS interrupt persistence (0..15). Consecutive exceedances needed."""
        apers = max(0, min(15, int(apers)))
        pers = self._read_u8(self.REG_PERS)
        pers &= 0xF0
        pers |= apers
        self._write_u8(self.REG_PERS, pers)

    def enable_interrupts(
        self,
        als: bool = False,
        flicker: bool = False,
        saturation: bool = False,
        system: bool = False,
    ) -> None:
        """Enable interrupt sources. INT pin asserts when condition met."""
        ien = self._read_u8(self.REG_INTENAB)
        ien = (ien | self.INTENAB_ALS_IEN) if als else (ien & ~self.INTENAB_ALS_IEN)
        ien = (ien | self.INTENAB_FIEN) if flicker else (ien & ~self.INTENAB_FIEN)
        ien = (ien | self.INTENAB_ASIEN) if saturation else (ien & ~self.INTENAB_ASIEN)
        ien = (ien | self.INTENAB_SIEN) if system else (ien & ~self.INTENAB_SIEN)
        self._write_u8(self.REG_INTENAB, ien)

    def read_interrupt_status(self) -> dict:
        """Read STATUS (0x93): AINT, FINT, SINT, ASAT."""
        s = self._read_u8(self.REG_STATUS)
        return {
            "asat": bool(s & self.STATUS_ASAT),
            "aint": bool(s & self.STATUS_AINT),
            "fint": bool(s & self.STATUS_FINT),
            "sint": bool(s & self.STATUS_SINT),
        }

    def clear_interrupts(self, sai_act: bool = False) -> None:
        """Clear interrupt flags. sai_act: clear SAI_ACT to exit sleep."""
        ctrl = self.CONTROL_CLEAR_SAI_ACT if sai_act else 0
        self._write_u8(self.REG_CONTROL, ctrl)

    # =========================================================================
    # Sleep after interrupt (SAI)
    # =========================================================================

    def set_sleep_after_interrupt(self, enable: bool) -> None:
        """Enable SAI: enter SLEEP on interrupt, clear via CONTROL."""
        cfg3 = self._read_u8(self.REG_CFG3)
        if enable:
            cfg3 |= 0x01  # SAI
        else:
            cfg3 &= ~0x01
        self._write_u8(self.REG_CFG3, cfg3)

    # =========================================================================
    # Flicker detection
    # =========================================================================

    def read_fd_status(self) -> dict:
        """Read FD_STATUS: valid, sat, 100/120 Hz detection."""
        s = self._read_u8(self.REG_FD_STATUS)
        return {
            "valid": bool(s & self.FD_STATUS_VALID),
            "sat": bool(s & self.FD_STATUS_SAT),
            "120hz_valid": bool(s & self.FD_STATUS_120_VALID),
            "100hz_valid": bool(s & self.FD_STATUS_100_VALID),
            "120hz": bool(s & self.FD_STATUS_120HZ),
            "100hz": bool(s & self.FD_STATUS_100HZ),
        }

    def read_fdata(self) -> int:
        """Read 16-bit flicker data from FDATA."""
        return self._read_u16_le(self.REG_FDATA_L)

    def set_fd_config(
        self,
        fd_time: int = 0,
        fd_gain: int = 0,
        fifo_write_fd: bool = False,
    ) -> None:
        """
        Configure flicker detection. fd_time/gain per datasheet.
        Enable FD via flicker_enable=True in __init__ or ENABLE FDEN.
        """
        self._write_u8(self.REG_FD_TIME_1, fd_time & 0xFF)
        ft2 = self._read_u8(self.REG_FD_TIME_2)
        ft2 &= 0x1F
        ft2 |= (fd_gain & 0x1F) << 3
        self._write_u8(self.REG_FD_TIME_2, ft2)
        df = self._read_u8(self.REG_FD_CFG0)
        if fifo_write_fd:
            df |= 0x01
        else:
            df &= ~0x01
        self._write_u8(self.REG_FD_CFG0, df)

    # =========================================================================
    # GPIO
    # =========================================================================

    def gpio_read(self) -> bool:
        """Read GPIO input state."""
        return (self._read_u8(self.REG_GPIO) & self.GPIO_IN) != 0

    def gpio_write(self, level: bool) -> None:
        """Set GPIO output level (when configured as output)."""
        g = self._read_u8(self.REG_GPIO)
        if level:
            g |= self.GPIO_OUT
        else:
            g &= ~self.GPIO_OUT
        self._write_u8(self.REG_GPIO, g)

    def gpio_config(self, as_input: bool = False, invert: bool = False) -> None:
        """Configure GPIO as input or output. Default is output."""
        g = self._read_u8(self.REG_GPIO)
        g = (g | self.GPIO_IN_EN) if as_input else (g & ~self.GPIO_IN_EN)
        g = (g | self.GPIO_INV) if invert else (g & ~self.GPIO_INV)
        self._write_u8(self.REG_GPIO, g)

    # =========================================================================
    # LED driver (LDR)
    # =========================================================================

    def set_led(self, active: bool, drive: int = 0) -> None:
        """
        Configure LED driver. drive 0..127 (current step).
        active: enable LED driver.
        """
        drive = max(0, min(127, int(drive)))
        val = (self.LED_ACT if active else 0) | (drive & self.LED_DRIVE_MASK)
        self._write_u8(self.REG_LED, val)

    # =========================================================================
    # AGC (on-chip automatic gain)
    # =========================================================================

    def set_agc(self, gain_max: int, fd_gain_max: int = 0) -> None:
        """
        Configure on-chip AGC. gain_max 0..15, fd_gain_max 0..15.
        Disables manual gain control when active.
        """
        gain_max = max(0, min(15, int(gain_max)))
        fd_gain_max = max(0, min(15, int(fd_gain_max)))
        val = (fd_gain_max << 4) | gain_max
        self._write_u8(self.REG_AGC_GAIN_MAX, val)

    def set_az_config(self, at_nth: int) -> None:
        """AZ_CONFIG: AT_NTH_ITERATION for AGC."""
        self._write_u8(self.REG_AZ_CONFIG, at_nth & 0xFF)

    # =========================================================================
    # Status and control
    # =========================================================================

    def read_status2(self) -> dict:
        """Read STATUS2: AVALID, ASAT_DIG, ASAT_ANA, FDSAT."""
        s = self._read_u8(self.REG_STATUS2)
        return {
            "avalid": bool(s & self.STATUS2_AVALID),
            "asat_dig": bool(s & self.STATUS2_ASAT_DIG),
            "asat_ana": bool(s & self.STATUS2_ASAT_ANA),
            "fdsat_ana": bool(s & self.STATUS2_FDSAT_ANA),
            "fdsat_dig": bool(s & self.STATUS2_FDSAT_DIG),
        }

    def software_reset(self) -> None:
        """Software reset. Returns to default state."""
        self._write_u8(self.REG_CONTROL, self.CONTROL_SW_RESET)
        time.sleep(0.01)

    def clear_fifo(self) -> None:
        """Clear FIFO (flicker data)."""
        self._write_u8(self.REG_CONTROL, self.CONTROL_FIFO_CLR)
