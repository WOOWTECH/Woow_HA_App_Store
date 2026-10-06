"""ZHA Quirk for Simon 241E8016TY 2-Gang Smart Dimmer (TS0052 / _TZ3002_cqpubrcz).

Device info:
  - Model:            TS0052
  - Manufacturer:     _TZ3002_cqpubrcz
  - IEEE:             8c:8b:48:ff:fe:51:96:85
  - WOOW/Tuya name:   241E8016TY — 2-channel dimmer
  - HA name_by_user:  241E8016TY

ZHA signature (paired to the ZHA coordinator, EFR32/EZSP):
  EP1 profile 0x0104 device_type 0x0101 (DIMMABLE_LIGHT)
    in : 0x0000 Basic, 0x0003 Identify, 0x0004 Groups, 0x0005 Scenes,
         0x0006 OnOff, 0x0008 LevelControl
    out: 0x0019 OTA
  EP2 profile 0x0104 device_type 0x0101 (DIMMABLE_LIGHT)
    in : 0x0000, 0x0003, 0x0004, 0x0005, 0x0006, 0x0008
    out: 0x0019 OTA

This is a plain standard-ZCL 2-gang dimmer (NOT a Tuya MCU / 0xEF00 / TS0601
device): both endpoints are real physical gangs and both honour standard
move_to_level* commands, so it already worked as two `light` entities before
this quirk.

Capabilities verified on the live device (ZHA read/write + Tuya-gateway sniff,
2026-07-24):
  OnOff 0x0006:
    0x0000 on_off                          -> light on/off        (writable)
    0x8001 backlight_mode = Mode_0         -> indicator LED mode   (writable ✓)
    0x4003 StartUpOnOff                     -> power-on behaviour: write is ACKed
        and reads back the written value, but the firmware never applies it at
        power-up (user-confirmed non-functional). ENTITY REMOVED — see below.
    0x8000 child_lock / 0x8002 power_on_state  supported but read None (not exposed)
  LevelControl 0x0008:
    0x0000 current_level                   -> light brightness     (writable ✓)
    0x0002 min_level = 77  (~30 %)         -> min brightness  READ-ONLY (0x88)
    0x0003 max_level = 254 (100 %)         -> max brightness  READ-ONLY (0x88)
    0x4000 StartUpCurrentLevel             -> power-on level: writable/persists but
        not applied at power-up (same as StartUpOnOff). ENTITY REMOVED.
    0x0010/0x0011/0x0014                   -> transition/on-level/move-rate (noise)

Min / Max brightness — WHY they are read-only (PROVEN by sniffer):
  The Tuya app shows a per-gang min/max dimming slider, but it does NOT actually
  work on this firmware. An nRF52840 capture of the Tuya gateway (PAN 0x5d4b,
  ch 20) driving a 2nd identical unit while the app changed min/max shows the
  gateway writing the STANDARD ZCL MinLevel (0x0002) / MaxLevel (0x0003) with the
  exact values entered (min 10 %->27, 50 %->128; max 60 %->154, 90 %->229 on the
  0..254 scale) — and the device rejecting EVERY write with ZCL Status.READ_ONLY
  (0x88) (writersp 880200 / 880300; 30/30 rejected, zero successes). There is no
  manufacturer-specific write and no 0xEF00 DP on this device. So MinLevel/MaxLevel
  are read-only at the firmware level for ALL controllers — the Tuya gateway is
  rejected identically to ZHA. They are exposed here as read-only diagnostic
  sensors (percent) so the configured range stays visible; there is no writable
  path to implement.

Power-on behaviour / level — WHY they are removed:
  The Tuya app exposes no power-on setting for this SKU, and the standard ZCL
  StartUpOnOff (0x4003) / StartUpCurrentLevel (0x4000) are ACKed and stored but
  not applied by the firmware at power-up (user-confirmed non-functional). Rather
  than ship dead controls, both are suppressed (cf. ts0001_switch_TZ3000_2xmrrjir,
  which omits the same ACK-but-ignored attributes).

Quirk summary:
  - Keeps the two dimmable lights (on/off + brightness).
  - Adds an Indicator (backlight) LED mode select on EP1 (OnOff 0x8001), reusing
    the upstream TuyaZBOnOffAttributeCluster. Labels follow the Simon SM0502
    sibling dimmer.
  - Exposes Min / Max brightness (standard MinLevel/MaxLevel) as read-only
    diagnostic sensors in percent (raw 0..254 -> whole %).
  - Suppresses noise + dead controls: default_move_rate / on_level /
    on_off_transition_time numbers, the non-functional power-on select
    (StartUpOnOff) and power-on level number (StartUpCurrentLevel), the duplicate
    Tuya power_on_state / child_lock selects, and per-endpoint firmware/OTA.
"""

import logging

import zigpy.types as t
from zigpy.quirks import CustomCluster
from zigpy.quirks.v2 import EntityType, QuirkBuilder
from zigpy.zcl.clusters.general import LevelControl

from zhaquirks.tuya import TuyaZBOnOffAttributeCluster

_LOGGER = logging.getLogger(__name__)

ONOFF = TuyaZBOnOffAttributeCluster.cluster_id  # 0x0006
LEVEL = LevelControl.cluster_id  # 0x0008

# Standard ZCL LevelControl attribute IDs used for the min/max brightness read-out.
MIN_LEVEL = LevelControl.AttributeDefs.min_level.id  # 0x0002
MAX_LEVEL = LevelControl.AttributeDefs.max_level.id  # 0x0003

# LevelControl current_level tops out at 254 (255 = "unchanged"); use it as the
# 100 % reference so the min/max brightness percent lines up with brightness.
_FULL = 254


class SimonDimmerLevelControl(CustomCluster, LevelControl):
    """Standard LevelControl that presents MinLevel/MaxLevel as a percent.

    The device stores the min/max dimming range in the standard MinLevel
    (0x0002) / MaxLevel (0x0003) attributes as a raw 0..254 level, and reports
    them READ-ONLY (a write returns Status.READ_ONLY 0x88 — see the module
    docstring). get() converts the raw level to a nearest-integer percent so the
    read-only diagnostic sensors read cleanly (e.g. 77 -> 30 %); returning a
    pre-rounded int keeps the sensor state a whole number instead of the long
    float raw * (100 / 254) would give.

    move_to_level* command handling is left untouched — this variant is a working
    standard dimmer.
    """

    _PCT_ATTRS = frozenset({MIN_LEVEL, MAX_LEVEL, "min_level", "max_level"})

    def get(self, key, default=None):
        """Show raw 0..254 min/max brightness as a nearest-integer percent."""
        if key in self._PCT_ATTRS:
            raw = super().get(key, None)
            return default if raw is None else round(raw * 100 / _FULL)
        return super().get(key, default)


class SimonDimmerBacklightMode(t.enum8):
    """Indicator / backlight LED mode (OnOff 0x8001).

    Labels follow the Simon SM0502 sibling dimmer: ZHA renders a select option
    as ``member_name.replace("_", " ")``, so these display as "Switch Status" /
    "Close" / "Switch Position". Integer values match the OnOff 0x8001 attribute
    (verified writable on hardware; cached value 0 = Switch_Status).
    """

    Switch_Status = 0x00
    Close = 0x01
    Switch_Position = 0x02


# ────────────────────────────────────────────────────────────────
# TS0052 — 241E8016TY 2-gang dimmer (_TZ3002_cqpubrcz)
# ────────────────────────────────────────────────────────────────
(
    QuirkBuilder("_TZ3002_cqpubrcz", "TS0052")
    # ── EP1 / EP2: OnOff with Tuya backlight_mode / power_on_state ──
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=1)
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=2)
    # ── EP1 / EP2: LevelControl (standard writes) + percent min/max read-out ──
    .replaces(SimonDimmerLevelControl, endpoint_id=1)
    .replaces(SimonDimmerLevelControl, endpoint_id=2)
    # ── Suppress useless default LevelControl config entities (both gangs) ──
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=LEVEL, unique_id_suffix="on_off_transition_time"
    )
    .prevent_default_entity_creation(
        endpoint_id=2, cluster_id=LEVEL, unique_id_suffix="on_off_transition_time"
    )
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=LEVEL, unique_id_suffix="on_level"
    )
    .prevent_default_entity_creation(
        endpoint_id=2, cluster_id=LEVEL, unique_id_suffix="on_level"
    )
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=LEVEL, unique_id_suffix="default_move_rate"
    )
    .prevent_default_entity_creation(
        endpoint_id=2, cluster_id=LEVEL, unique_id_suffix="default_move_rate"
    )
    # ── Suppress the duplicate Tuya power-on / child-lock selects from
    #    TuyaZBOnOffAttributeCluster (we keep the standard StartUpOnOff select) ──
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=ONOFF, unique_id_suffix="power_on_state"
    )
    .prevent_default_entity_creation(
        endpoint_id=2, cluster_id=ONOFF, unique_id_suffix="power_on_state"
    )
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=ONOFF, unique_id_suffix="child_lock"
    )
    .prevent_default_entity_creation(
        endpoint_id=2, cluster_id=ONOFF, unique_id_suffix="child_lock"
    )
    # ── Remove the non-functional power-on controls (both gangs): the Tuya app
    #    has no power-on setting for this SKU and the firmware ACKs but never
    #    applies StartUpOnOff (0x4003) / StartUpCurrentLevel (0x4000) at power-up
    #    (user-confirmed) — so they are dead controls, not exposed. ──
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=ONOFF, unique_id_suffix="StartUpOnOff"
    )
    .prevent_default_entity_creation(
        endpoint_id=2, cluster_id=ONOFF, unique_id_suffix="StartUpOnOff"
    )
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=LEVEL, unique_id_suffix="start_up_current_level"
    )
    .prevent_default_entity_creation(
        endpoint_id=2, cluster_id=LEVEL, unique_id_suffix="start_up_current_level"
    )
    # ── Min brightness (standard 0x0002) — READ-ONLY diagnostic sensor, percent ──
    .sensor(
        SimonDimmerLevelControl.AttributeDefs.min_level.name,
        LEVEL,
        endpoint_id=1,
        unit="%",
        entity_type=EntityType.DIAGNOSTIC,
        translation_key="min_brightness_1",
        fallback_name="Min Brightness 1",
    )
    .sensor(
        SimonDimmerLevelControl.AttributeDefs.min_level.name,
        LEVEL,
        endpoint_id=2,
        unit="%",
        entity_type=EntityType.DIAGNOSTIC,
        translation_key="min_brightness_2",
        fallback_name="Min Brightness 2",
    )
    # ── Max brightness (standard 0x0003) — READ-ONLY diagnostic sensor, percent ──
    .sensor(
        SimonDimmerLevelControl.AttributeDefs.max_level.name,
        LEVEL,
        endpoint_id=1,
        unit="%",
        entity_type=EntityType.DIAGNOSTIC,
        translation_key="max_brightness_1",
        fallback_name="Max Brightness 1",
    )
    .sensor(
        SimonDimmerLevelControl.AttributeDefs.max_level.name,
        LEVEL,
        endpoint_id=2,
        unit="%",
        entity_type=EntityType.DIAGNOSTIC,
        translation_key="max_brightness_2",
        fallback_name="Max Brightness 2",
    )
    # ── Indicator (backlight) LED mode select (device-global, EP1 only) ──
    .enum(
        TuyaZBOnOffAttributeCluster.AttributeDefs.backlight_mode.name,
        SimonDimmerBacklightMode,
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
