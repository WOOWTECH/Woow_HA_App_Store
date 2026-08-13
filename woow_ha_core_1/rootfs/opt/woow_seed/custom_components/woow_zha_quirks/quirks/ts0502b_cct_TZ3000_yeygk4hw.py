"""ZHA Quirk for Tuya TS0502B CCT (Color Temperature) LED Light.

Device info:
  - Model:        TS0502B
  - Manufacturer: _TZ3000_yeygk4hw
  - Chip:         Silicon Labs EFR32MG24
  - IEEE:         40:30:59:ff:fe:55:96:96
  - Type:         CCT light (warm↔cool) — on/off + dimming + colour temperature

Single endpoint (EP1: OnOff, LevelControl, Color).  How this device is *actually*
driven was established by sniffing the Tuya gateway → light Zigbee traffic on
channel 20 (2026-06-26, see ``docs/16-SP9-200-10-sniff-findings.md``):

  * On / Off  → **standard** ZCL OnOff ``on`` (0x01) / ``off`` (0x00).  Works.
  * Brightness → **Tuya manufacturer command 0xF0 on the Level cluster**, payload
    ``uint16 LE`` = Tuya ``bright_value`` (10..1000).  The gateway never uses the
    standard ``move_to_level`` / ``move_to_level_with_on_off`` commands.
  * Colour-temp → **Tuya manufacturer command 0xE0 on the Color cluster**, payload
    ``uint16 LE`` = Tuya ``temp_value`` (0..1000).  The gateway never uses the
    standard ``move_to_color_temperature`` (0x0A) — which is why HA's colour-temp
    slider previously had no physical effect.

So this quirk keeps OnOff standard and translates HA's LevelControl /
ColorControl commands into the Tuya 0xF0 / 0xE0 commands the hardware obeys.
The streaming 0xF2 "live preview" frames the app sends during a slider drag are
NOT replicated — a single 0xF0 / 0xE0 commit carries the final value (revisit if
hardware testing shows the commit alone is insufficient).

Known hardware limitation (NOT fixable in software): the LED driver intermittently
"latches" — the MCU accepts the command and reports the new on_off / level state,
but the physical LED output hangs (stays dark / unchanged) until it self-recovers.
The sniff proved every on command was ACKed with on_off=1 even when the bulb stayed
dark, so the fault is downstream of the Zigbee MCU and affects the app, the knob and
this quirk equally.
"""

import logging
from typing import Final

import zigpy.types as t
from zigpy.quirks import CustomCluster
from zigpy.quirks.v2 import QuirkBuilder
from zigpy.zcl.clusters.general import LevelControl, OnOff
from zigpy.zcl.clusters.lighting import Color
from zigpy.zcl.foundation import ZCLCommandDef

_LOGGER = logging.getLogger(__name__)

# Kelvin ↔ mireds conversion
MIREDS_FACTOR = 1_000_000

# Device's physical colour-temp range (Kelvin, as the device reports it)
DEVICE_MIN_KELVIN = 2500  # warm white
DEVICE_MAX_KELVIN = 6500  # cool white

# Converted to mireds (note: min K → max mireds, max K → min mireds)
PHYSICAL_MIN_MIREDS = MIREDS_FACTOR // DEVICE_MAX_KELVIN  # 153 (6500K, cool)
PHYSICAL_MAX_MIREDS = MIREDS_FACTOR // DEVICE_MIN_KELVIN  # 400 (2500K, warm)

# Color cluster attribute IDs
COLOR_TEMP = Color.AttributeDefs.color_temperature.id  # 0x0007
COLOR_CAPABILITIES = Color.AttributeDefs.color_capabilities.id  # 0x400A
COLOR_TEMP_MIN = Color.AttributeDefs.color_temp_physical_min.id  # 0x400B
COLOR_TEMP_MAX = Color.AttributeDefs.color_temp_physical_max.id  # 0x400C
STARTUP_COLOR_TEMP = Color.AttributeDefs.start_up_color_temperature.id  # 0x4010

# Attributes the device may report in Kelvin → convert to mireds on read
KELVIN_ATTR_IDS = {COLOR_TEMP, STARTUP_COLOR_TEMP}
KELVIN_ATTR_NAMES = {"color_temperature", "start_up_color_temperature"}

LEVEL = LevelControl.cluster_id  # 0x0008
CURRENT_LEVEL = LevelControl.AttributeDefs.current_level.id  # 0x0000

# Standard command ids HA sends
MOVE_TO_LEVEL = 0x00
MOVE_TO_LEVEL_WITH_ON_OFF = 0x04
MOVE_TO_COLOR_TEMP = 0x0A
# OnOff command ids
ONOFF_OFF = 0x00
ONOFF_ON = 0x01

# Tuya manufacturer command ids (cluster-specific, no manufacturer code)
TUYA_SET_BRIGHTNESS = 0xF0  # on LevelControl 0x0008, payload uint16 LE 10..1000
TUYA_SET_COLOR_TEMP = 0xE0  # on Color 0x0300,       payload uint16 LE 0..1000

# Tuya value ranges (from the cloud DP model + confirmed in the capture)
TUYA_BRIGHT_MIN = 10
TUYA_BRIGHT_MAX = 1000
TUYA_TEMP_MIN = 0
TUYA_TEMP_MAX = 1000

HA_LEVEL_MAX = 254  # ZCL current_level full scale


def _kelvin_to_mireds(kelvin: int) -> int:
    """Convert Kelvin to mireds, clamped to physical range."""
    if kelvin <= 0:
        return PHYSICAL_MAX_MIREDS
    mireds = MIREDS_FACTOR // kelvin
    return max(PHYSICAL_MIN_MIREDS, min(PHYSICAL_MAX_MIREDS, mireds))


def _level_to_bright_value(level: int) -> int:
    """HA current_level (0..254) → Tuya bright_value (10..1000)."""
    level = max(0, min(HA_LEVEL_MAX, int(level)))
    bv = round(level * TUYA_BRIGHT_MAX / HA_LEVEL_MAX)
    return max(TUYA_BRIGHT_MIN, min(TUYA_BRIGHT_MAX, bv))


def _mireds_to_temp_value(mireds: int) -> int:
    """HA colour temp (mireds) → Tuya temp_value (0..1000).

    Warm (max mireds / min Kelvin) → 0, cool (min mireds / max Kelvin) → 1000,
    matching the Tuya convention (temp_value 0 = warmest).
    """
    m = max(PHYSICAL_MIN_MIREDS, min(PHYSICAL_MAX_MIREDS, int(mireds)))
    span = PHYSICAL_MAX_MIREDS - PHYSICAL_MIN_MIREDS
    tv = round((PHYSICAL_MAX_MIREDS - m) / span * TUYA_TEMP_MAX)
    return max(TUYA_TEMP_MIN, min(TUYA_TEMP_MAX, tv))


class TuyaCCTColorCluster(CustomCluster, Color):
    """Color cluster driving colour temperature via the Tuya 0xE0 command.

    The device ignores standard ``move_to_color_temperature`` (0x0A) but obeys a
    manufacturer command 0xE0 carrying ``temp_value`` (0..1000).  We translate HA's
    mireds into that and optimistically reflect it back as ``color_temperature``.
    Also presents CCT-only capabilities + the correct mireds range, and converts
    any Kelvin-valued report to mireds for display.
    """

    _CONSTANT_ATTRIBUTES = {
        COLOR_CAPABILITIES: 0x10,  # CCT only (bit 4) — hide bogus xy/hs
        COLOR_TEMP_MIN: PHYSICAL_MIN_MIREDS,  # 153 mireds (6500K)
        COLOR_TEMP_MAX: PHYSICAL_MAX_MIREDS,  # 400 mireds (2500K)
    }

    class ServerCommandDefs(Color.ServerCommandDefs):
        """Add the Tuya colour-temp command (0xE0)."""

        tuya_set_color_temp: Final = ZCLCommandDef(
            id=TUYA_SET_COLOR_TEMP,
            schema={"temp_value": t.uint16_t},
        )

    async def command(
        self,
        command_id,
        *args,
        manufacturer=None,
        expect_reply=True,
        tsn=None,
        **kwargs,
    ):
        if command_id == MOVE_TO_COLOR_TEMP:
            mireds = args[0] if args else kwargs.get("color_temp_mireds", PHYSICAL_MAX_MIREDS)
            temp_value = _mireds_to_temp_value(mireds)
            _LOGGER.debug(
                "TS0502B colour-temp %s mireds -> Tuya 0xE0 temp_value=%d",
                mireds, temp_value,
            )
            # Device sends no Default Response for the Tuya command → don't wait.
            result = await super().command(
                TUYA_SET_COLOR_TEMP, temp_value, expect_reply=False
            )
            # Optimistically reflect the set value for the HA UI.
            self._update_attribute(COLOR_TEMP, int(mireds))
            return result
        return await super().command(
            command_id, *args, manufacturer=manufacturer,
            expect_reply=expect_reply, tsn=tsn, **kwargs,
        )

    def _update_attribute(self, attrid: int, value) -> None:
        """Convert Kelvin → mireds when the device reports colour temperature."""
        if attrid in KELVIN_ATTR_IDS and isinstance(value, int) and value > 1000:
            mireds = _kelvin_to_mireds(value)
            _LOGGER.debug("TS0502B 0x%04X report: Kelvin %d -> mireds %d", attrid, value, mireds)
            super()._update_attribute(attrid, mireds)
            return
        super()._update_attribute(attrid, value)

    def get(self, key, default=None):
        """Convert any cached Kelvin colour-temp value to mireds on read."""
        is_kelvin_attr = (
            (isinstance(key, int) and key in KELVIN_ATTR_IDS)
            or (isinstance(key, str) and key in KELVIN_ATTR_NAMES)
        )
        if is_kelvin_attr:
            val = super().get(key)
            if val is not None and isinstance(val, int) and val > 1000:
                return _kelvin_to_mireds(val)
            return val if val is not None else default
        return super().get(key, default)


class TuyaCCTLevelControl(CustomCluster, LevelControl):
    """LevelControl driving brightness via the Tuya 0xF0 command.

    The device ignores standard ``move_to_level`` / ``move_to_level_with_on_off``
    and obeys a manufacturer command 0xF0 carrying ``bright_value`` (10..1000).
    HA's level commands are translated into 0xF0; the with-on-off variant also
    issues the standard OnOff ``on``/``off`` (which the device honours) so the
    light turns on/off as expected.
    """

    class ServerCommandDefs(LevelControl.ServerCommandDefs):
        """Add the Tuya brightness command (0xF0)."""

        tuya_set_brightness: Final = ZCLCommandDef(
            id=TUYA_SET_BRIGHTNESS,
            schema={"bright_value": t.uint16_t},
        )

    async def _set_brightness(self, level: int) -> None:
        bright_value = _level_to_bright_value(level)
        _LOGGER.debug("TS0502B level=%s -> Tuya 0xF0 bright_value=%d", level, bright_value)
        await super().command(TUYA_SET_BRIGHTNESS, bright_value, expect_reply=False)
        self._update_attribute(CURRENT_LEVEL, max(1, min(HA_LEVEL_MAX, int(level))))

    async def command(
        self,
        command_id,
        *args,
        manufacturer=None,
        expect_reply=True,
        tsn=None,
        **kwargs,
    ):
        if command_id in (MOVE_TO_LEVEL, MOVE_TO_LEVEL_WITH_ON_OFF):
            level = args[0] if args else kwargs.get("level", 0)
            onoff = self.endpoint.in_clusters.get(OnOff.cluster_id)
            if command_id == MOVE_TO_LEVEL_WITH_ON_OFF and onoff is not None:
                if not level:
                    _LOGGER.debug("TS0502B move_to_level_with_on_off level=0 -> OnOff.off")
                    return await onoff.command(ONOFF_OFF, expect_reply=False)
                await onoff.command(ONOFF_ON, expect_reply=False)
            return await self._set_brightness(level)
        return await super().command(
            command_id, *args, manufacturer=manufacturer,
            expect_reply=expect_reply, tsn=tsn, **kwargs,
        )


# ────────────────────────────────────────────────────────────────
# TS0502B — CCT light (_TZ3000_yeygk4hw) — on/off + dimming + colour temp
# ────────────────────────────────────────────────────────────────
(
    QuirkBuilder("_TZ3000_yeygk4hw", "TS0502B")
    .replaces(TuyaCCTColorCluster, endpoint_id=1)
    .replaces(TuyaCCTLevelControl, endpoint_id=1)
    # ── Suppress useless default LevelControl config entities ──
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=LEVEL, unique_id_suffix="on_off_transition_time",
    )
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=LEVEL, unique_id_suffix="on_level",
    )
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=LEVEL, unique_id_suffix="default_move_rate",
    )
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=LEVEL, unique_id_suffix="start_up_current_level",
    )
    # ── Suppress Color cluster config entities ──
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=0x0300, unique_id_suffix="start_up_color_temperature",
    )
    .add_to_registry()
)
