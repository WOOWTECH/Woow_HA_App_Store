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
     this variant DOES honour standard move_to_level* commands (it presented as a
     working standard dimmer before this quirk), so we must NOT route writes
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
  2. Min / Max brightness config numbers (0xFC03 / 0xFC04), shown as 1..100 %
     sliders. The raw 1..255 value is converted to percent in the cluster's
     get()/write_attributes() and rounded to the nearest integer % (ZHA's number
     `multiplier` would leave an unrounded float like 52.94117647 % in the state).
  3. Indicator (backlight) LED mode select (OnOff 0x8001) — labels mapped to the
     app's DP102 (none / enable_white / enable_yellow).
  4. Suppress the useless default LevelControl config entities and the raw
     manufacturer-attribute auto-entities.
  5. Remove both power-on selects (standard StartUpOnOff + Tuya power_on_state).

NOTE: the real bulb-type attribute (0xFC01 vs 0xFC02) is unresolved — 0xFC02
reads as unsupported on this variant, so bulb/dimming-mode attrs are declared
but not exposed.
"""

import logging
from typing import Final

import zigpy.types as t
from zigpy.quirks import CustomCluster
from zigpy.quirks.v2 import EntityType, QuirkBuilder
from zigpy.zcl.clusters.general import LevelControl
from zigpy.zcl.foundation import ZCLAttributeDef

from zhaquirks.tuya import TuyaZBOnOffAttributeCluster
from zhaquirks.tuya.ts110e import TuyaBulbType

_LOGGER = logging.getLogger(__name__)

ONOFF = TuyaZBOnOffAttributeCluster.cluster_id  # 0x0006
LEVEL = LevelControl.cluster_id  # 0x0008

# Tuya private LevelControl attribute IDs
TUYA_LEVEL = 0xF000  # brightness report (same 0..254 domain as current_level)
TUYA_DIMMING_MODE = 0xFC01  # cached value 2 — role unconfirmed (curve?)
TUYA_BULB_TYPE = 0xFC02  # LED / INCANDESCENT / HALOGEN
TUYA_MIN_LEVEL = 0xFC03  # min brightness (cached 77)
TUYA_MAX_LEVEL = 0xFC04  # max brightness (cached 255)

# Min/Max brightness are stored raw 1..255 on the device but shown as 1..100 %.
# The percent is computed in the cluster (get/write_attributes) rather than via
# the ZHA number `multiplier`, so the entity state is rounded to 2 dp (ZHA does
# not round the multiplier result, which would show e.g. 28.6274509803922 %).


class TS110DLevelControl(CustomCluster, LevelControl):
    """Plain LevelControl + Tuya manufacturer attributes.

    Standard move_to_level* is left intact (this variant honours it), so zha's
    light.async_turn_on receives a proper command result. We only:
      - declare the Tuya manufacturer attributes so they can back config entities
      - mirror 0xF000 brightness reports (10..1000) onto current_level (0..254)
        so brightness changed at the wall is reflected in Home Assistant.
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
        percent (with the number's multiplier left at 1) makes the entity
        *state* a whole number, instead of the long float produced by
        raw * (100/255). round() with no ndigits returns an int.
        """
        if key in self._PCT_ATTRS:
            raw = super().get(key, None)
            return default if raw is None else round(raw * 100 / 255)
        return super().get(key, default)

    async def write_attributes(self, attributes, manufacturer=None, **kwargs):
        """Convert percent writes back to the device's raw 1..255 domain."""
        out = {}
        for attr, val in attributes.items():
            if attr in self._PCT_ATTRS:
                out[attr] = max(1, min(255, round(float(val) * 255 / 100)))
            else:
                out[attr] = val
        return await super().write_attributes(
            out, manufacturer=manufacturer, **kwargs
        )


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
    # ── Min brightness (0xFC03), shown as 1..100 % slider (2 dp via cluster) ──
    .number(
        TS110DLevelControl.AttributeDefs.manufacturer_min_level.name,
        LEVEL,
        endpoint_id=1,
        min_value=1,
        max_value=100,
        step=1,
        unit="%",
        mode="slider",
        entity_type=EntityType.CONFIG,
        translation_key="min_brightness",
        fallback_name="Min Brightness",
    )
    # ── Max brightness (0xFC04), shown as 1..100 % slider (2 dp via cluster) ──
    .number(
        TS110DLevelControl.AttributeDefs.manufacturer_max_level.name,
        LEVEL,
        endpoint_id=1,
        min_value=1,
        max_value=100,
        step=1,
        unit="%",
        mode="slider",
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
