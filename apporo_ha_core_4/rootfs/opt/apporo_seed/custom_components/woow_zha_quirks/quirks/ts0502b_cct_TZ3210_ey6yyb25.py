"""ZHA quirk for the Simon SP9-200-14 tunable-white LED driver.

Device
------
  Manufacturer  _TZ3210_ey6yyb25        (NOT _TZ3000_ -- see below)
  Model         TS0502B
  app_version   101
  IEEE          e4:56:ac:ff:fe:72:de:4c  (the sample unit)
  Endpoint 1    profile 0x0104, device 0x010C
                in : 0x0000 0x0003 0x0004 0x0005 0x0006 0x1000 0x0008 0x0300 0xEF00
                out: 0x0019 0x000A
  Endpoint 0xF2 Green Power, not used

Everything below was established by sniffing the Tuya gateway on channel 20 and by driving the
device from the Tuya cloud one datapoint at a time, then confirmed against the device on ZHA.
See ``docs/simon-product/22-SP9-200-14-tuya-functions.md``.

Why this is a separate file from the SP9-200-10 quirk
----------------------------------------------------
SP9-200-10 is ``_TZ3000_yeygk4hw``; this is ``_TZ3210_ey6yyb25``. Same Simon product family, same
Tuya cloud datapoint numbers, **different chip family and different behaviour**:

  * SP9-200-10 ignores standard ``move_to_level`` and needs the Tuya 0xF0 command on the Level
    cluster. **This device obeys standard ``move_to_level``** (verified on the physical lamp), so
    LevelControl is left completely alone here. Copying SP9-200-10's LevelControl override would
    replace a working path with a private one for no gain.
  * SP9-200-10's quirk hardcodes a 153..400 mired range. **This device reports 153..500** -- the
    warm end reaches 2000 K, not 2500 K. The range is read from the device, not assumed.

What the device does *not* obey
-------------------------------
Colour temperature. Standard ``move_to_color_temperature`` (0x0A) has no physical effect. The
gateway drives it with a manufacturer command **0xE0 on the Color cluster**, payload ``uint16 LE``
= Tuya ``temp_value`` 0..1000, where **0 is the warmest end**.

Every colour-temperature write is preceded by **``Color 0xF0 = 0``** (set ``work_mode`` to white).
The gateway sends that even for a bare cloud command with no slider dragging, so it is part of the
write and not a UI artefact -- and this device reports ``color_mode = Hue_and_saturation`` out of
the box, so the mode really does need forcing.

Note ``0xF0`` and attribute ``0xF000`` mean three different things on three clusters:
work_mode on Color, brightness on Level, countdown on OnOff. Nothing here is global.

Not implemented, deliberately
-----------------------------
  * DP 30 ``rhythm_mode`` (cmd 0xF6, attr 0xF009, 59 bytes) and DP 7 ``countdown``
    (OnOff cmd 0xF0, attr 0xF000) -- Home Assistant automations do scheduling better. See
    ``docs/adr/0004-defer-on-device-scheduling-to-ha-automation.md``; this is a one-way door,
    because once the device is on ZHA the Tuya app can no longer reach those settings either.
  * DP 6 ``scene_data`` (cmd 0xF1, attr 0xF003) -- layout not worked out, low value.
  * DP 31 ``sleep_mode`` / DP 32 ``wakeup_mode`` -- present in Tuya's product model but **not
    implemented by this firmware**: no app UI, and the cloud values never left ``00 00``.
  * OnOff 0x4001 / 0x4002 / 0xFEFE -- the device answers UNSUPPORTED_ATTRIBUTE (0x86).

Known limitation
----------------
The packed settings are reported back by the device with ZCL type ``0x48`` carrying a **single**
length byte, which is not how the spec encodes an array, so zigpy cannot parse those reports. The
three settings below are therefore tracked optimistically: the value shown is the value last
written through Home Assistant, and it is not re-read from the device after a restart. Nothing
else can change them -- the Tuya app is gone once the device is on ZHA, and there is no physical
control for them -- so optimistic tracking is accurate in practice, just not authoritative.
"""

import logging
from typing import Final

import zigpy.types as t
from zigpy.quirks import CustomCluster
from zigpy.quirks.v2 import EntityType, QuirkBuilder
from zigpy.zcl.clusters.lighting import Color
from zigpy.zcl.foundation import ZCLAttributeDef, ZCLCommandDef, Status, WriteAttributesStatusRecord

try:  # zigpy re-exports this but warns; the ZHA path is the current home
    from zha.application.platforms.number.device_class import NumberMode
except ImportError:  # pragma: no cover - older installs
    from zigpy.quirks.v2.homeassistant.number import NumberMode

_LOGGER = logging.getLogger(__name__)

COLOR = Color.cluster_id  # 0x0300
COLOR_TEMP = Color.AttributeDefs.color_temperature.id  # 0x0007
COLOR_MODE = Color.AttributeDefs.color_mode.id  # 0x0008

MOVE_TO_COLOR_TEMP = 0x0A  # the standard command HA sends, which this device ignores

# Tuya manufacturer commands on the Color cluster (cluster-specific, no manufacturer code)
TUYA_SET_WORK_MODE: Final = 0xF0
TUYA_SET_COLOR_TEMP: Final = 0xE0
TUYA_SET_POWER_MEMORY: Final = 0xF9
TUYA_SET_DO_NOT_DISTURB: Final = 0xFA
TUYA_SET_GRADIENT: Final = 0xFB

WORK_MODE_WHITE = 0x00

# Tuya temp_value scale. 0 is the WARMEST end, which is the opposite of mireds.
TUYA_TEMP_MIN = 0
TUYA_TEMP_MAX = 1000

# Read from the device (Color 0x400B / 0x400C), not assumed:
#   153 mireds = 6535 K (coolest)   500 mireds = 2000 K (warmest)
PHYSICAL_MIN_MIREDS = 153
PHYSICAL_MAX_MIREDS = 500

# Factory defaults observed immediately after a reset, used as the initial optimistic state.
DEFAULT_POWER_MEMORY_MODE = 1  # Restore memory
DEFAULT_POWER_MEMORY_BRIGHT = 1000
DEFAULT_POWER_MEMORY_TEMP = 1000
DEFAULT_GRADIENT_MS = 800

GRADIENT_MIN_MS = 0
GRADIENT_MAX_MS = 10_000


class PowerMemoryMode(t.enum8):
    """Behaviour when mains power is restored (Tuya DP 33, byte 1)."""

    Initial_mode = 0x00
    Restore_memory = 0x01
    Customized = 0x02


def mireds_to_temp_value(mireds: int) -> int:
    """HA colour temperature (mireds) -> Tuya temp_value (0..1000, 0 = warmest)."""
    m = max(PHYSICAL_MIN_MIREDS, min(PHYSICAL_MAX_MIREDS, int(mireds)))
    span = PHYSICAL_MAX_MIREDS - PHYSICAL_MIN_MIREDS
    return round((PHYSICAL_MAX_MIREDS - m) / span * TUYA_TEMP_MAX)


def temp_value_to_mireds(temp_value: int) -> int:
    """Tuya temp_value (0..1000) -> HA colour temperature (mireds)."""
    tv = max(TUYA_TEMP_MIN, min(TUYA_TEMP_MAX, int(temp_value)))
    span = PHYSICAL_MAX_MIREDS - PHYSICAL_MIN_MIREDS
    return round(PHYSICAL_MAX_MIREDS - tv / TUYA_TEMP_MAX * span)


class TuyaCCTColorCluster(CustomCluster, Color):
    """Colour temperature via the Tuya 0xE0 command, plus the driver's private settings.

    The three settings (power memory, do-not-disturb, switch gradient) travel as packed byte
    structs in manufacturer commands, not as writable attributes. Home Assistant can only build
    entities on attributes, so each field is surfaced as a synthetic attribute in the 0xFF00 range
    which is intercepted in ``write_attributes``, re-encoded into the full struct and sent as the
    command the firmware expects. The synthetic ids are never put on the air.
    """

    class AttributeDefs(Color.AttributeDefs):
        """Real device attributes plus the synthetic ones backing the config entities."""

        # Real: the device reports these back after a command.
        tuya_temp_value = ZCLAttributeDef(id=0xE000, type=t.uint16_t, access="r")
        tuya_work_mode = ZCLAttributeDef(id=0xF000, type=t.uint8_t, access="r")
        tuya_do_not_disturb = ZCLAttributeDef(id=0xF00D, type=t.Bool, access="rw")

        # Synthetic: unpacked fields of the 0xF00C / 0xF00E structs. Never transmitted.
        power_memory_mode = ZCLAttributeDef(id=0xFF01, type=PowerMemoryMode, access="rw")
        power_memory_brightness = ZCLAttributeDef(id=0xFF02, type=t.uint16_t, access="rw")
        power_memory_color_temp = ZCLAttributeDef(id=0xFF03, type=t.uint16_t, access="rw")
        gradient_on_ms = ZCLAttributeDef(id=0xFF04, type=t.uint16_t, access="rw")
        gradient_off_ms = ZCLAttributeDef(id=0xFF05, type=t.uint16_t, access="rw")

    class ServerCommandDefs(Color.ServerCommandDefs):
        """Tuya manufacturer commands. Field layouts are byte-exact from the captures."""

        tuya_set_work_mode: Final = ZCLCommandDef(
            id=TUYA_SET_WORK_MODE,
            schema={"work_mode": t.uint8_t},
        )
        tuya_set_color_temp: Final = ZCLCommandDef(
            id=TUYA_SET_COLOR_TEMP,
            schema={"temp_value": t.uint16_t},
        )
        # 00 <mode> 00 00 00 00 00 00 <bright BE> <temp BE>
        tuya_set_power_memory: Final = ZCLCommandDef(
            id=TUYA_SET_POWER_MEMORY,
            schema={
                "prefix": t.uint8_t,
                "mode": t.uint8_t,
                "reserved_a": t.uint32_t,
                "reserved_b": t.uint16_t,
                "brightness": t.uint16_t_be,
                "color_temp": t.uint16_t_be,
            },
        )
        tuya_set_do_not_disturb: Final = ZCLCommandDef(
            id=TUYA_SET_DO_NOT_DISTURB,
            schema={"enabled": t.uint8_t},
        )
        # 00 00 <on ms BE> 00 <off ms BE>
        tuya_set_gradient: Final = ZCLCommandDef(
            id=TUYA_SET_GRADIENT,
            schema={
                "prefix": t.uint8_t,
                "on_high": t.uint8_t,
                "on_ms": t.uint16_t_be,
                "off_high": t.uint8_t,
                "off_ms": t.uint16_t_be,
            },
        )

    # The device advertises Hue_and_saturation, which makes Home Assistant refuse to show a
    # colour-temperature control at all. It is a tunable-white driver with no colour hardware.
    _CONSTANT_ATTRIBUTES = {COLOR_MODE: Color.ColorMode.Color_temperature}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Seed the optimistic settings state with the firmware's post-reset defaults so the
        # config entities have a value before anything is written. See "Known limitation".
        _LOGGER.debug("SP9-200-14 colour cluster __init__ on %s", self.endpoint)
        for attr_id, value in (
            (COLOR_TEMP, PHYSICAL_MIN_MIREDS),
            (self.AttributeDefs.tuya_do_not_disturb.id, False),
            (self.AttributeDefs.power_memory_mode.id, DEFAULT_POWER_MEMORY_MODE),
            (self.AttributeDefs.power_memory_brightness.id, DEFAULT_POWER_MEMORY_BRIGHT),
            (self.AttributeDefs.power_memory_color_temp.id, DEFAULT_POWER_MEMORY_TEMP),
            (self.AttributeDefs.gradient_on_ms.id, DEFAULT_GRADIENT_MS),
            (self.AttributeDefs.gradient_off_ms.id, DEFAULT_GRADIENT_MS),
        ):
            if self.get(attr_id) is None:
                self._update_attribute(attr_id, value)

    # ── colour temperature ────────────────────────────────────────────────

    async def command(self, command_id, *args, manufacturer=None, expect_reply=True,
                      tsn=None, **kwargs):
        if command_id == MOVE_TO_COLOR_TEMP:
            mireds = args[0] if args else kwargs.get("color_temp_mireds", PHYSICAL_MAX_MIREDS)
            temp_value = mireds_to_temp_value(mireds)
            _LOGGER.debug(
                "SP9-200-14 colour temp %s mireds -> work_mode=white + Tuya 0xE0 temp_value=%d",
                mireds, temp_value,
            )
            # The gateway always forces white mode first; the device ships in
            # Hue_and_saturation mode, so this is a precondition rather than a nicety.
            await super().command(TUYA_SET_WORK_MODE, WORK_MODE_WHITE, expect_reply=False)
            await super().command(TUYA_SET_COLOR_TEMP, temp_value, expect_reply=False)
            self._update_attribute(COLOR_TEMP, int(mireds))
            # Home Assistant inspects ``result[1] is not Status.SUCCESS`` after issuing a light
            # command. The device sends no Default Response to a Tuya command, so the
            # expect_reply=False call returns nothing of that shape -- returning it raised inside
            # ZHA *before* it wrote the new state. That single mistake produced both a 500 on
            # every colour-temperature call and a colour temperature frozen in the UI, while the
            # lamp itself obeyed perfectly. Hand back the shape ZHA expects.
            return [MOVE_TO_COLOR_TEMP, Status.SUCCESS]
        return await super().command(
            command_id, *args, manufacturer=manufacturer,
            expect_reply=expect_reply, tsn=tsn, **kwargs,
        )

    def _update_attribute(self, attrid: int, value) -> None:
        """Mirror the device's own Tuya-scale report onto the standard attribute.

        Without this, anything that changes the lamp outside Home Assistant -- the built-in
        circadian schedule, another controller -- would be invisible, because the device reports
        its colour temperature on 0xE000 and never on 0x0007.
        """
        super()._update_attribute(attrid, value)
        if attrid == self.AttributeDefs.tuya_temp_value.id and isinstance(value, int):
            mireds = temp_value_to_mireds(value)
            super()._update_attribute(COLOR_TEMP, mireds)
            _LOGGER.debug("SP9-200-14 0xE000=%s -> color_temperature=%s (cache now %s)",
                          value, mireds, self.get(COLOR_TEMP))
        elif attrid == COLOR_TEMP:
            _LOGGER.debug("SP9-200-14 color_temperature set to %s (cache now %s)",
                          value, self.get(COLOR_TEMP))

    # ── the three packed settings ─────────────────────────────────────────

    def _cached(self, attr_def, fallback):
        value = self.get(attr_def.id)
        return fallback if value is None else int(value)

    async def _send_power_memory(self) -> None:
        await super().command(
            TUYA_SET_POWER_MEMORY,
            0,
            self._cached(self.AttributeDefs.power_memory_mode, DEFAULT_POWER_MEMORY_MODE),
            0,
            0,
            self._cached(self.AttributeDefs.power_memory_brightness, DEFAULT_POWER_MEMORY_BRIGHT),
            self._cached(self.AttributeDefs.power_memory_color_temp, DEFAULT_POWER_MEMORY_TEMP),
            expect_reply=False,
        )

    async def _send_gradient(self) -> None:
        await super().command(
            TUYA_SET_GRADIENT,
            0,
            0,
            self._cached(self.AttributeDefs.gradient_on_ms, DEFAULT_GRADIENT_MS),
            0,
            self._cached(self.AttributeDefs.gradient_off_ms, DEFAULT_GRADIENT_MS),
            expect_reply=False,
        )

    def _cache_served_ids(self) -> set:
        """Attribute ids that must never be read from the device.

        The synthetic 0xFF0x ids do not exist on the device at all, and the firmware answers
        UNSUPPORTED_ATTRIBUTE (0x86) even for the real ``do_not_disturb`` at 0xF00D -- the join
        capture shows the Tuya gateway getting 0x86 for it too. Letting Home Assistant read any
        of them leaves the entity with no state at startup.
        """
        return {
            self.AttributeDefs.tuya_do_not_disturb.id,
            self.AttributeDefs.power_memory_mode.id,
            self.AttributeDefs.power_memory_brightness.id,
            self.AttributeDefs.power_memory_color_temp.id,
            self.AttributeDefs.gradient_on_ms.id,
            self.AttributeDefs.gradient_off_ms.id,
            # The device's own color_temperature never moves -- it sat at 153 through six
            # commands that the device demonstrably obeyed (0xE000 tracked every one, and the
            # lamp visibly changed colour). Reading it from the device would overwrite the
            # value derived from 0xE000 with a dead one.
            COLOR_TEMP,
        }

    async def read_attributes(self, attributes, allow_cache=False, only_cache=False,
                              manufacturer=None, **kwargs):
        """Serve the settings attributes from the local cache instead of the device."""
        cache_only = self._cache_served_ids()
        served, passthrough = {}, []
        for attr in attributes:
            attr_id = self.attributes_by_name[attr].id if isinstance(attr, str) else attr
            value = self.get(attr_id) if attr_id in cache_only else None
            if value is not None:
                # Callers disagree about how they index a read result: zigpy keys defined
                # attributes by NAME, while some websocket paths look them up by id. Serving
                # both costs nothing and stops a lookup silently finding nothing -- keying by
                # id alone was what turned a stale-but-present 0x0007 into no value at all.
                served[self.attributes[attr_id].name] = value
                served[attr_id] = value
            else:
                # Nothing cached yet: fall through to the device rather than dropping the
                # attribute, so the caller gets a real answer or a real failure.
                passthrough.append(attr)

        _LOGGER.debug("SP9-200-14 read_attributes %s -> served=%s passthrough=%s",
                      attributes, served, passthrough)

        if not passthrough:
            return served, {}

        success, failure = await super().read_attributes(
            passthrough, allow_cache=allow_cache, only_cache=only_cache,
            manufacturer=manufacturer, **kwargs,
        )
        success.update(served)
        return success, failure

    async def write_attributes(self, attributes, manufacturer=None, **kwargs):
        """Route writes of the synthetic attributes to the commands the firmware expects."""
        power_memory_ids = {
            self.AttributeDefs.power_memory_mode.id,
            self.AttributeDefs.power_memory_brightness.id,
            self.AttributeDefs.power_memory_color_temp.id,
        }
        gradient_ids = {
            self.AttributeDefs.gradient_on_ms.id,
            self.AttributeDefs.gradient_off_ms.id,
        }
        dnd_id = self.AttributeDefs.tuya_do_not_disturb.id

        remaining = {}
        touched_power_memory = False
        touched_gradient = False
        dnd_value = None

        for attr, value in attributes.items():
            attr_id = self.attributes_by_name[attr].id if isinstance(attr, str) else attr
            if attr_id in power_memory_ids:
                self._update_attribute(attr_id, int(value))
                touched_power_memory = True
            elif attr_id in gradient_ids:
                self._update_attribute(attr_id, int(value))
                touched_gradient = True
            elif attr_id == dnd_id:
                dnd_value = 1 if value else 0
            else:
                remaining[attr] = value

        if touched_power_memory:
            await self._send_power_memory()
        if touched_gradient:
            await self._send_gradient()
        if dnd_value is not None:
            await super().command(TUYA_SET_DO_NOT_DISTURB, dnd_value, expect_reply=False)
            self._update_attribute(dnd_id, bool(dnd_value))

        if remaining:
            return await super().write_attributes(remaining, manufacturer, **kwargs)
        return [[WriteAttributesStatusRecord(Status.SUCCESS)]]


(
    QuirkBuilder("_TZ3210_ey6yyb25", "TS0502B")
    # LevelControl and OnOff are deliberately untouched -- both obey standard ZCL here.
    .replaces(TuyaCCTColorCluster, endpoint_id=1)
    # ── Power-restore behaviour (Tuya DP 33) ──
    .enum(
        TuyaCCTColorCluster.AttributeDefs.power_memory_mode.name,
        PowerMemoryMode,
        COLOR,
        endpoint_id=1,
        entity_type=EntityType.CONFIG,
        translation_key="power_memory_mode",
        fallback_name="Power-On Behaviour",
    )
    .number(
        TuyaCCTColorCluster.AttributeDefs.power_memory_brightness.name,
        COLOR,
        endpoint_id=1,
        min_value=10,
        max_value=1000,
        step=1,
        # Home Assistant's AUTO mode falls back to a text box once the range is wide, and a
        # thousand-step range is wide. Force the slider: these are "roughly this bright" settings,
        # not values anyone types exactly.
        mode=NumberMode.SLIDER,
        entity_type=EntityType.CONFIG,
        translation_key="power_memory_brightness",
        fallback_name="Power-On Brightness",
    )
    .number(
        TuyaCCTColorCluster.AttributeDefs.power_memory_color_temp.name,
        COLOR,
        endpoint_id=1,
        min_value=0,
        max_value=1000,
        step=1,
        mode=NumberMode.SLIDER,
        entity_type=EntityType.CONFIG,
        translation_key="power_memory_color_temp",
        fallback_name="Power-On Colour Temperature",
    )
    # ── Fade times (Tuya DP 35) ──
    .number(
        TuyaCCTColorCluster.AttributeDefs.gradient_on_ms.name,
        COLOR,
        endpoint_id=1,
        min_value=GRADIENT_MIN_MS,
        max_value=GRADIENT_MAX_MS,
        step=100,
        unit="ms",
        entity_type=EntityType.CONFIG,
        translation_key="gradient_on_ms",
        fallback_name="Fade-On Time",
    )
    .number(
        TuyaCCTColorCluster.AttributeDefs.gradient_off_ms.name,
        COLOR,
        endpoint_id=1,
        min_value=GRADIENT_MIN_MS,
        max_value=GRADIENT_MAX_MS,
        step=100,
        unit="ms",
        entity_type=EntityType.CONFIG,
        translation_key="gradient_off_ms",
        fallback_name="Fade-Off Time",
    )
    # ── Do not disturb (Tuya DP 34): suppress the lamp coming back on after a power cut ──
    .switch(
        TuyaCCTColorCluster.AttributeDefs.tuya_do_not_disturb.name,
        COLOR,
        endpoint_id=1,
        entity_type=EntityType.CONFIG,
        translation_key="do_not_disturb",
        fallback_name="Do Not Disturb",
    )
    # ── The device's start-up colour temperature reads back as garbage (54176) ──
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=COLOR, unique_id_suffix="start_up_color_temperature",
    )
    .add_to_registry()
)
