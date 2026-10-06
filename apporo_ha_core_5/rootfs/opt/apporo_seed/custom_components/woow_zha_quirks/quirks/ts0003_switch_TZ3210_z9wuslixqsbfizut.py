"""ZHA Quirk for Simon "6-66E8003" — Tuya TS0003 3-Gang Switch.

Device info:
  - Model:        TS0003
  - Manufacturer: _TZ3210_z9wuslixqsbfizut
  - Firmware:     0x00000087
  - IEEE:         7c:31:fa:ff:fe:b4:e6:b0
  - Tuya product: z9wuslixqsbfizut  (Simon-home device "6-66E8003")

This is a standard ZCL 3-gang switch (on/off via cluster 0x0006 per endpoint),
NOT a Tuya MCU (TS0601) device.  The device advertises NINE endpoints (1-9) but
only endpoints 1, 2 and 3 are real physical gangs; endpoints 4-9 are phantom and
otherwise flood Home Assistant with duplicate switch / power-on / firmware
entities.

This quirk:
  1. Replaces OnOff on EP1-3 with TuyaZBOnOffAttributeCluster
     (adds the Tuya attrs: backlight_mode, power_on_state).
  2. Removes phantom endpoints 4-9  → a clean 3-gang device.
  3. Exposes an Indicator (backlight) LED mode select on EP1, with labels that
     match the Tuya app:
        Close                 (0)
        Off white, On orange  (1)
        Off orange, On white  (2)
  4. Suppresses the native "Power-on behavior" (StartUpOnOff 0x4003) selects on
     EP1-3.  Those are a generic ZCL artifact — this device has no Tuya power-on
     datapoint and ignores the attribute, so the selects do nothing.

ZHA renders enum-select options as `member_name.replace("_", " ")` and maps a
chosen label back with `replace(" ", "_")`, so the WoowBacklightMode member names
use underscores for spaces (commas pass through unchanged).  `enum.IntEnum` is
used because zigpy's `enum8` blocks the functional API; the ZCL write is coerced
to the attribute's real type (SwitchBackLight) by zigpy.

Out of scope (Tuya-cloud / 0xEF00 DP features, not reliable as Zigbee attrs):
  backlight brightness (`backlight_num`) and per-gang countdown — see
  tuya_export/DP_REFERENCE.md.  An "all on/off" control is best created with a
  native Home Assistant switch group / helper.
"""

import enum
import logging

from zigpy.quirks.v2 import EntityType, QuirkBuilder

from zhaquirks.tuya import TuyaZBOnOffAttributeCluster

_LOGGER = logging.getLogger(__name__)

ONOFF = TuyaZBOnOffAttributeCluster.cluster_id  # 0x0006


# Indicator/backlight LED mode, labelled to match the Tuya app.
# Member names use underscores where the displayed label has spaces — ZHA renders
# select options as `name.replace("_", " ")` — while commas pass through verbatim.
# Built with the IntEnum functional API because (a) class syntax can't express
# member names containing commas, and (b) zigpy's enum8 blocks the functional API.
WoowBacklightMode = enum.IntEnum(
    "WoowBacklightMode",
    {
        "Close": 0,
        "Off_white,_On_orange": 1,
        "Off_orange,_On_white": 2,
    },
)


# ────────────────────────────────────────────────────────────────
# TS0003 — 3-gang switch (_TZ3210_z9wuslixqsbfizut)
# ────────────────────────────────────────────────────────────────
(
    QuirkBuilder("_TZ3210_z9wuslixqsbfizut", "TS0003")
    # ── EP1-3: real gangs → Tuya OnOff (adds backlight_mode / power_on_state) ──
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=1)
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=2)
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=3)
    # ── Remove phantom endpoints 4-9 ──
    .removes_endpoint(endpoint_id=4)
    .removes_endpoint(endpoint_id=5)
    .removes_endpoint(endpoint_id=6)
    .removes_endpoint(endpoint_id=7)
    .removes_endpoint(endpoint_id=8)
    .removes_endpoint(endpoint_id=9)
    # ── Suppress the native StartUpOnOff "power-on behavior" selects (EP1-3) ──
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=ONOFF, unique_id_suffix="StartUpOnOff"
    )
    .prevent_default_entity_creation(
        endpoint_id=2, cluster_id=ONOFF, unique_id_suffix="StartUpOnOff"
    )
    .prevent_default_entity_creation(
        endpoint_id=3, cluster_id=ONOFF, unique_id_suffix="StartUpOnOff"
    )
    # ── Indicator (backlight) LED mode select on EP1, Tuya-app labels ──
    .enum(
        TuyaZBOnOffAttributeCluster.AttributeDefs.backlight_mode.name,
        WoowBacklightMode,
        ONOFF,
        endpoint_id=1,
        entity_type=EntityType.CONFIG,
        translation_key="backlight_mode",
        fallback_name="Indicator Mode",
    )
    # Suppress redundant per-endpoint firmware/OTA update entities (all gangs).
    # OTA cluster (0x0019) is mirrored on every endpoint and has no ZHA OTA image,
    # so each firmware entity sits permanently "unknown". One rule, all endpoints.
    .prevent_default_entity_creation(unique_id_suffix="firmware_update")
    .add_to_registry()
)
