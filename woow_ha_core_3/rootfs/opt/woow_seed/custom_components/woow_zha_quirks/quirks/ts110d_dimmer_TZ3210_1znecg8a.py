"""ZHA Quirk for Simon 1-Gang Smart Dimmer (TS110D / _TZ3210_1znecg8a).

Device info:
  - Model:        TS110D  (Tuya TS110E dimmer family)
  - Manufacturer: _TZ3210_1znecg8a
  - Chip:         Silicon Labs (Tuya Zigbee 3.0)
  - IEEE:         f0:82:c0:ff:fe:c9:24:97
  - WOOW/Tuya:    15-66E8015 — Simon M7 一位智能调光开关 (category tgkg)

This is a standard ZCL dimmer (device_type 0x0101 DIMMABLE_LIGHT) on a single
endpoint (EP1: OnOff 0x0006 + LevelControl 0x0008), but it belongs to the Tuya
TS110E firmware family, which has two quirks:

  1. Brightness is *also* reported on the manufacturer attribute 0xF000, but on
     this variant in the SAME 0..254 domain as current_level (verified on
     hardware: a 50% set reported 0xF000≈127). Unlike the older _TZ3210_ngqk6jia,
     this variant honours standard move_to_level* commands **while the lamp is
     already on** (it presented as a working standard dimmer before this quirk);
     while the lamp is off it answers SUCCESS and acts on neither the level nor
     the implicit on, which the quirk works around by sending On first — see
     "Level commands need the lamp already on" below. We must NOT route writes
     through the Tuya custom command 0x00F0 — the upstream
     F000LevelControlCluster.command() override returns None for that path and
     crashes zha's light.async_turn_on ("TypeError: 'NoneType' object is not
     subscriptable" at move_to_level_with_on_off). We therefore keep standard
     command handling and only mirror 0xF000 reports onto the standard
     current_level (0x0000), copied through directly (no rescaling), so
     brightness changed at the wall is reflected in Home Assistant.
  2. Several Tuya manufacturer attributes carry features the Tuya app exposes but
     ZHA hides without a quirk:
       LevelControl 0xFC03 — min brightness   (cached 77)
       LevelControl 0xFC04 — max brightness   (cached 255)
       LevelControl 0xFC01 — dimming mode / curve (cached 2, role unconfirmed)
       LevelControl 0xFC02 — bulb type (LED/INCANDESCENT/HALOGEN)
       OnOff        0x8001 — backlight / indicator LED mode (cached 1)

Tuya DP map (from the WOOW app, for reference):
  DP1  switch_led_1     bool     on/off
  DP2  bright_value_1   1..255   brightness
  DP3  brightness_min_1 1..255   -> 0xFC03
  DP5  brightness_max_1 1..255   -> 0xFC04
  DP6  countdown_1      0..86400 s
  DP26 switch_backlight bool
  DP102 light_mode_1    enum     none / enable_white / enable_yellow

We reuse TuyaZBOnOffAttributeCluster (provides backlight_mode + power_on_state)
and the TuyaBulbType enum from the upstream ts110e module, but use a plain
LevelControl subclass (NOT F000LevelControlCluster) for the reasons in (1) above.

Quirk adds / fixes:
  1. Reliable on/off + brightness via standard ZCL, with 0xF000->current_level
     read mirroring.
  2. Min / Max brightness (0xFC03 / 0xFC04) as writable config numbers in
     percent, always written as a pair — see "Min/max only commit when written
     as a pair" below — and refused if they would leave max at or below min
     (issue #5). The device accepts an inverted window silently, so that guard
     is ours, not the firmware's. The Tuya app's further "max - min >= 30 %"
     rule is deliberately NOT copied: it exists because the app's brightness
     slider is relative to the [min, max] window, so a narrow window destroys
     its resolution. Home Assistant's brightness is absolute, so the reason does
     not carry over, and enforcing it would only block legitimate narrow
     windows.
  3. Indicator (backlight) LED mode select (OnOff 0x8001) — labels mapped to the
     app's DP102 (none / enable_white / enable_yellow).
  4. Suppress the useless default LevelControl config entities and the raw
     manufacturer-attribute auto-entities.
  5. Remove both power-on selects (standard StartUpOnOff + Tuya power_on_state).

Min/max only commit when written as a pair (issue #3)
----------------------------------------------------
0xFC03 / 0xFC04 are ordinary writable uint16 attributes: every write is answered
SUCCESS, echoed back in an unsolicited report, read back correctly from the
device, and persisted across a mains power cycle. None of that means the
firmware is using the value. It keeps a separate *committed* window, and only
replaces it when it receives min and max close together. A lone write, or a
pair more than about a second apart, updates storage and leaves the committed
window untouched — the device goes on clamping to the previous one.

Measured directly, lamp on throughout, nothing else varied (2026-08-14):

    write 0xFC03=102 then 0xFC04=204, 2.5 s apart
        stored 102/204   commanded 40 -> 51, 254 -> 230   (previous window!)
    write 0xFC03=64  then 0xFC04=242, 0.1 s apart
        stored  64/242   commanded 40 -> 64, 254 -> 242   (committed)

This quirk therefore always sends both attributes in ONE frame, which is
strictly tighter than the ~100 ms pair the Tuya gateway sends and needs no
timing luck. Once committed the window survives an OnOff cycle and a 10 s mains
outage; a re-pair puts the device back on the factory 77/255.

That single rule explains the entire history of this bug. The Tuya app always
worked because the gateway writes the pair ~100 ms apart and repeats it three
times. Every ZHA test that ever "proved" the attributes were inert — including
the ones in issue #3 that led to demoting them to read-only sensors — wrote the
two attributes about 1.5 s apart.

Do not be fooled by a read-back: reading 0xFC03/0xFC04 from the device returns
the stored value, not the committed one, so the two can disagree indefinitely.
The only honest test is to command a level and see where it lands.

Level commands need the lamp already on (issue #4)
--------------------------------------------------
move_to_level_with_on_off (and its move/step siblings) is answered with a
SUCCESS default response while the lamp is off, after which the firmware acts
on neither the implicit "on" nor the level. Home Assistant's "turn on at
brightness X" is exactly that command, so the lamp stayed dark while HA
believed it was lit. Confirmed still present on 2026-08-14: with the lamp off,
light.turn_on brightness=200 left on_off false (the level was stored, and only
took effect the next time the lamp was switched on some other way).

TS110DLevelControl.command() therefore sends OnOff On first whenever the cached
on_off says the lamp is off. The Tuya gateway never hits this because it drives
level with the private 0x00F0 command and never uses move_to_level* at all;
routing through 0x00F0 was considered and rejected, because the upstream
F000LevelControlCluster.command() override returns None on that path and
crashes zha's light.async_turn_on (see (1) above).

Everything below was tested and is NOT the gate. Do not re-litigate without new
evidence; all of it is on the wire in captures/ts110d_mfgcode_ch25.pcap:

  - Tuya "attribute read" spell (BaseEnchantedDevice) — no effect.
  - The Tuya gateway's join handshake replayed frame for frame, on a fresh join
    (single-frame six-attribute spell, Basic 0xFFDE write, Basic cmd 0xF0, the
    0xFEFE-bearing cluster probes, the duplicated probe round, the trailing
    Basic 0x0001 read) — no effect.
  - The coordinator's ZDO manufacturer code. The device really does send
    Node_Desc_req to 0x0000 on every join, and the Tuya gateway answers 0x1049
    where zigpy answers 0xABCD — but making an EmberZNet NCP answer 0x1049
    (EZSP frame 0x15, confirmed on the wire) changed nothing, and the limits
    work with the stock 0xABCD.
  - The lamp being on or off at write time. It looked decisive for one round of
    testing and is not: a pair written 0.1 s apart commits with the lamp off,
    and a pair written 2.5 s apart fails to commit with the lamp on.
  - OnOff off->on cycle, ZHA restart, mains power cycle, factory reset — no
    effect. The Tuya gateway is equally factory-reset at pairing and its limits
    work, so the reset was never the difference either.
  - The Tuya 0xEF00 DP path — the device exposes 0xEF00 on EP1, but the gateway
    never used it for min/max; it wrote the same 0xFC03/0xFC04.

NOTE: the real bulb-type attribute (0xFC01 vs 0xFC02) is unresolved — 0xFC02
reads as unsupported on this variant, so bulb/dimming-mode attrs are declared
but not exposed.
"""

import asyncio
import logging
from typing import Final

import zigpy.types as t
from zigpy.exceptions import ZigbeeException
from zigpy.quirks import CustomCluster
from zigpy.quirks.v2 import EntityType, QuirkBuilder
from zigpy.zcl.clusters.general import LevelControl, OnOff
from zigpy.zcl.foundation import ZCLAttributeDef

from zhaquirks.tuya import TuyaZBOnOffAttributeCluster
from zhaquirks.tuya.ts110e import TuyaBulbType

_LOGGER = logging.getLogger(__name__)

ONOFF = TuyaZBOnOffAttributeCluster.cluster_id  # 0x0006
LEVEL = LevelControl.cluster_id  # 0x0008
ONOFF_ATTR_ON_OFF = OnOff.AttributeDefs.on_off.id  # 0x0000
ONOFF_CMD_ON = OnOff.ServerCommandDefs.on.id  # 0x01

# LevelControl commands that carry an implicit "turn on". This firmware answers
# all of them with a SUCCESS default response while the lamp is off and then
# acts on neither half -- see issue #4 -- so the On has to be sent separately.
WITH_ON_OFF_COMMANDS = frozenset(
    {
        LevelControl.ServerCommandDefs.move_to_level_with_on_off.id,  # 0x04
        LevelControl.ServerCommandDefs.move_with_on_off.id,  # 0x05
        LevelControl.ServerCommandDefs.step_with_on_off.id,  # 0x06
    }
)
# Time for the lamp to actually be running before it will accept a level.
ON_SETTLE_DELAY = 0.5

# Tuya private LevelControl attribute IDs
TUYA_LEVEL = 0xF000  # brightness report (same 0..254 domain as current_level)
TUYA_DIMMING_MODE = 0xFC01  # cached value 2 — role unconfirmed (curve?)
TUYA_BULB_TYPE = 0xFC02  # LED / INCANDESCENT / HALOGEN
TUYA_MIN_LEVEL = 0xFC03  # min brightness (cached 77)
TUYA_MAX_LEVEL = 0xFC04  # max brightness (cached 255)

# Min/Max brightness are stored raw 1..255 on the device but shown as 1..100 %.
# The percent is computed in the cluster's get() rather than via a ZHA
# `multiplier`, so the entity state is a whole number (ZHA does not round the
# multiplier result, which would show e.g. 28.6274509803922 %).


class TS110DLevelControl(CustomCluster, LevelControl):
    """Plain LevelControl + Tuya manufacturer attributes.

    Standard move_to_level* is left intact (this variant honours it while the
    light is ON — see issue #4 for the OFF-state defect), so zha's
    light.async_turn_on receives a proper command result. We only:
      - declare the Tuya manufacturer attributes so they can back entities
      - mirror 0xF000 brightness reports onto current_level (same 0..254
        domain, no rescale) so brightness changed at the wall is reflected in
        Home Assistant.
    """

    class AttributeDefs(LevelControl.AttributeDefs):
        """Extend with the Tuya manufacturer attributes."""

        manufacturer_current_level: Final = ZCLAttributeDef(
            id=TUYA_LEVEL, type=t.uint16_t
        )
        tuya_dimming_mode: Final = ZCLAttributeDef(
            id=TUYA_DIMMING_MODE, type=t.uint8_t
        )
        bulb_type: Final = ZCLAttributeDef(id=TUYA_BULB_TYPE, type=TuyaBulbType)
        manufacturer_min_level: Final = ZCLAttributeDef(
            id=TUYA_MIN_LEVEL, type=t.uint16_t
        )
        manufacturer_max_level: Final = ZCLAttributeDef(
            id=TUYA_MAX_LEVEL, type=t.uint16_t
        )

    # Min/Max brightness attributes exposed to HA as a percent (1..100 %).
    _PCT_ATTRS = frozenset(
        {TUYA_MIN_LEVEL, TUYA_MAX_LEVEL,
         "manufacturer_min_level", "manufacturer_max_level"}
    )


    def _update_attribute(self, attrid, value):
        """Mirror Tuya 0xF000 brightness reports onto standard current_level.

        On this variant 0xF000 is reported in the SAME 0..254 domain as
        current_level (NOT the 10..1000 domain the upstream TS110E quirk
        assumes), so we copy it through directly — no rescaling. This keeps
        Home Assistant's brightness in sync if the device only reports the
        change via 0xF000 (e.g. dimmed at the wall).
        """
        super()._update_attribute(attrid, value)
        if attrid == TUYA_LEVEL and isinstance(value, int):
            level = max(0, min(254, value))
            _LOGGER.debug("TS110D 0xF000=%d -> current_level=%d", value, level)
            super()._update_attribute(
                LevelControl.AttributeDefs.current_level.id, level
            )

    def get(self, key, default=None):
        """Show raw 1..255 min/max brightness as a nearest-integer percent.

        ZHA's number entity uses cluster.get(); returning a pre-rounded int
        percent makes the entity *state* a whole number instead of the long
        float produced by raw * (100/255). round() with no ndigits returns an
        int. write_attributes() converts the other way.
        """
        if key in self._PCT_ATTRS:
            raw = super().get(key, None)
            return default if raw is None else round(raw * 100 / 255)
        return super().get(key, default)

    def _resolve_command_id(self, command_id):
        """Accept an id, a name or a ZCLCommandDef and return the numeric id."""
        try:
            return self.server_commands[command_id].id
        except (KeyError, TypeError, AttributeError):
            return getattr(command_id, "id", command_id)

    def _lamp_is_on(self) -> bool:
        onoff = self.endpoint.in_clusters.get(ONOFF)
        if onoff is None:
            # Nothing we can do about it, so do not add a pointless frame.
            return True
        return bool(onoff.get(ONOFF_ATTR_ON_OFF, False))

    async def command(self, command_id, *args, **kwargs):
        """Send On before a *_with_on_off level command if the lamp is off.

        The firmware discards both halves of move_to_level_with_on_off while
        the lamp is off -- and answers SUCCESS, so nothing upstream notices.
        Home Assistant's "turn on at brightness X" is exactly that command, so
        without this the lamp stays dark while HA believes it is lit (#4).

        The On is skipped when the cached on_off already says the lamp is
        running, which is the common case for a brightness change and keeps
        slider drags to one frame each. That trusts the cache: this device
        reports on_off changes promptly, including presses at the wall, so a
        stale "on" is unlikely -- and its only cost is that one brightness
        command is dropped, exactly as it is today.
        """
        if (
            self._resolve_command_id(command_id) in WITH_ON_OFF_COMMANDS
            and not self._lamp_is_on()
        ):
            onoff = self.endpoint.in_clusters.get(ONOFF)
            try:
                await onoff.command(ONOFF_CMD_ON)
                await asyncio.sleep(ON_SETTLE_DELAY)
                self.debug("sent On before a level command; the lamp was off (#4)")
            except Exception as exc:  # noqa: BLE001 - still try the level command
                self.debug("could not send On before the level command (%s)", exc)
        return await super().command(command_id, *args, **kwargs)

    async def write_attributes(self, attributes, manufacturer=None, **kwargs):
        """Write min/max as a raw 1..255 PAIR, in one frame.

        Two things happen here:

          - percent -> raw, rounding half UP (int(v * 255 / 100 + 0.5)) rather
            than Python's round(), which is half-to-even and disagrees with the
            Tuya gateway on exact .5 values: 30 % is 77 on the gateway and 76
            under round().
          - min and max are always sent together. The firmware only *commits* a
            new window when it receives both close together; a lone write (or a
            pair spread more than about a second apart) is acknowledged, stored
            and read back correctly while the previously committed window stays
            in force. Measured directly -- see the module docstring. Putting
            both in a single frame makes the commit unconditional and is
            strictly tighter than the ~100 ms pair the Tuya gateway sends.

        The completed pair is then checked for min < max and the whole write is
        rejected if it is not -- see _reject_inverted_window.
        """
        converted = {}
        touches_limits = False
        for key, value in attributes.items():
            if key in self._PCT_ATTRS and isinstance(value, (int, float)):
                raw = int(value * 255 / 100 + 0.5)
                converted[key] = max(1, min(255, raw))
                touches_limits = True
            else:
                converted[key] = value

        if touches_limits:
            await self._complete_limit_pair(converted)
            self._reject_inverted_window(converted, set(attributes))

        return await super().write_attributes(converted, manufacturer, **kwargs)

    @staticmethod
    def _pct(raw: int) -> int:
        """Raw 1..255 as the percent the user sees on the entity."""
        return round(raw * 100 / 255)

    @staticmethod
    def _pick(converted: dict, attr_id: int, name: str):
        """Read a limit out of the write dict, whichever key form was used."""
        if attr_id in converted:
            return converted[attr_id]
        return converted.get(name)

    def _reject_inverted_window(self, converted: dict, requested: set) -> None:
        """Refuse a write that would leave max at or below min.

        The device accepts an inverted window without complaint -- measured:
        min 90 % / max 50 % is written, acknowledged and read back -- and then
        behaves in a way nobody asked for. So this is our rule, not the
        firmware's, and it is enforced here rather than through the entity
        bounds because ZHA takes a quirk's number min/max as static and cannot
        narrow one entity's range from the other's current value.

        Rejecting rather than silently adjusting the partner is deliberate. A
        value the user did not type is exactly the kind of quiet wrongness that
        made issue #3 take as long as it did; a refusal that names the value in
        the way is worse for one click and better forever after. The message
        says which entity to move first, because with two coupled numbers the
        legal path can depend on the order they are changed.

        A pair that cannot be completed (partner unknown and unreadable) is let
        through: the write itself is about to fail anyway on an unreachable
        device, and locking the control over an unverifiable rule is worse than
        the rule going unenforced for one write.
        """
        lo = self._pick(converted, TUYA_MIN_LEVEL, "manufacturer_min_level")
        hi = self._pick(converted, TUYA_MAX_LEVEL, "manufacturer_max_level")
        if lo is None or hi is None or lo < hi:
            return

        wants_min = bool(requested & {TUYA_MIN_LEVEL, "manufacturer_min_level"})
        wants_max = bool(requested & {TUYA_MAX_LEVEL, "manufacturer_max_level"})
        if wants_min and not wants_max:
            msg = (
                f"Max Brightness is {self._pct(hi)} %, so Min Brightness cannot be "
                f"set to {self._pct(lo)} %. Raise Max Brightness first."
            )
        elif wants_max and not wants_min:
            msg = (
                f"Min Brightness is {self._pct(lo)} %, so Max Brightness cannot be "
                f"set to {self._pct(hi)} %. Lower Min Brightness first."
            )
        else:
            msg = (
                f"Min Brightness {self._pct(lo)} % must be below Max Brightness "
                f"{self._pct(hi)} %."
            )
        self.debug("rejecting inverted brightness window: %s", msg)
        raise ZigbeeException(msg)

    async def _complete_limit_pair(self, converted: dict) -> None:
        """Add whichever of min/max is missing, so both go out in one frame."""
        for attr_id, name in (
            (TUYA_MIN_LEVEL, "manufacturer_min_level"),
            (TUYA_MAX_LEVEL, "manufacturer_max_level"),
        ):
            if attr_id in converted or name in converted:
                continue
            raw = self._attr_cache.get(attr_id)
            if raw is None:
                try:
                    success, _ = await super().read_attributes([attr_id])
                    raw = success.get(attr_id)
                except Exception as exc:  # noqa: BLE001 - degrade, do not fail the write
                    self.debug("could not read %#06x to pair the write (%s)", attr_id, exc)
            if raw is None:
                self.debug(
                    "writing %#06x alone: its partner is unknown, so the firmware "
                    "may store the value without committing it",
                    attr_id,
                )
                continue
            converted[name] = raw


class TS110DBacklightMode(t.enum8):
    """Indicator / backlight LED mode (OnOff 0x8001).

    Maps to the Tuya app's DP102 light_mode_1 (none / enable_white /
    enable_yellow). ZHA renders a select option as ``member_name.replace("_",
    " ")`` and cannot include commas, so the labels drop the requested commas:
        Light_Close          -> "Light Close"          (none)
        Off_white_On_orange  -> "Off white On orange"  (enable_white)
        Off_orange_On_white  -> "Off orange On white"  (enable_yellow)
    Integer values match the OnOff 0x8001 attribute (cached value 1).
    """

    Light_Close = 0x00
    Off_white_On_orange = 0x01
    Off_orange_On_white = 0x02


# ────────────────────────────────────────────────────────────────
# TS110D — 1-gang dimmer (_TZ3210_1znecg8a)
# ────────────────────────────────────────────────────────────────
(
    QuirkBuilder("_TZ3210_1znecg8a", "TS110D")
    # ── EP1: OnOff with Tuya backlight_mode / power_on_state ──
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=1)
    # ── EP1: LevelControl (standard writes) + Tuya min/max/bulb attrs ──
    .replaces(TS110DLevelControl, endpoint_id=1)
    # ── Suppress useless default LevelControl config entities ──
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=LEVEL, unique_id_suffix="on_off_transition_time"
    )
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=LEVEL, unique_id_suffix="on_level"
    )
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=LEVEL, unique_id_suffix="default_move_rate"
    )
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=LEVEL, unique_id_suffix="start_up_current_level"
    )
    # ── Suppress raw auto-entities for manufacturer attrs we don't expose (v1) ──
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=LEVEL, unique_id_suffix="manufacturer_current_level"
    )
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=LEVEL, unique_id_suffix="bulb_type"
    )
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=LEVEL, unique_id_suffix="tuya_dimming_mode"
    )
    # ── Remove both power-on selects: the standard StartUpOnOff and the
    #    duplicate Tuya power_on_state from TuyaZBOnOffAttributeCluster ──
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=ONOFF, unique_id_suffix="StartUpOnOff"
    )
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=ONOFF, unique_id_suffix="power_on_state"
    )
    # ── Indicator (backlight) LED mode select ──
    .enum(
        TuyaZBOnOffAttributeCluster.AttributeDefs.backlight_mode.name,
        TS110DBacklightMode,
        ONOFF,
        endpoint_id=1,
        entity_type=EntityType.CONFIG,
        translation_key="backlight_mode",
        fallback_name="Indicator Mode",
    )
    # ── Min brightness (0xFC03) — writable, percent. The device stores 1..255;
    #    TS110DLevelControl converts both ways and always sends min+max in one
    #    frame, because the firmware only commits a window it receives as a
    #    pair (issue #3). ──
    .number(
        TS110DLevelControl.AttributeDefs.manufacturer_min_level.name,
        LEVEL,
        endpoint_id=1,
        min_value=1,
        max_value=100,
        step=1,
        unit="%",
        entity_type=EntityType.CONFIG,
        translation_key="min_brightness",
        fallback_name="Min Brightness",
    )
    # ── Max brightness (0xFC04) — writable, percent ──
    .number(
        TS110DLevelControl.AttributeDefs.manufacturer_max_level.name,
        LEVEL,
        endpoint_id=1,
        min_value=1,
        max_value=100,
        step=1,
        unit="%",
        entity_type=EntityType.CONFIG,
        translation_key="max_brightness",
        fallback_name="Max Brightness",
    )
    # Suppress redundant per-endpoint firmware/OTA update entities (all gangs).
    # OTA cluster (0x0019) is mirrored on every endpoint and has no ZHA OTA image,
    # so each firmware entity sits permanently "unknown". One rule, all endpoints.
    .prevent_default_entity_creation(unique_id_suffix="firmware_update")
    .add_to_registry()
)
