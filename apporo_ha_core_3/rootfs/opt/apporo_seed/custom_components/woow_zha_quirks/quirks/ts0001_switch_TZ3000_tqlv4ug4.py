"""ZHA Quirk for Tuya TS0001 switches (light→switch fix).

Covers:
  - _TZ3000_tqlv4ug4  (switch module — has metering clusters to remove,
                        needs external_switch_type for wired switch config)
  - _TZ3000_tuucc0f5  (switch panel — no metering, no external_switch_type)
  - _TZ3000_voy7mbpw  (switch panel — same as tuucc0f5)
  - _TZ3000_6m2xazd1  (WOOW "新版零火智能開關-1開" — same as voy7mbpw)
  - _TZ3000_2xmrrjir  (WOOW "新版單火智能開關-1開" WO_50804_1S, model TS0011 —
                        single-live-wire sibling of 6m2xazd1; switch only, its
                        0x8001/0x8002 selects are omitted as the firmware ignores
                        ZCL writes to them — see the NOTE on that block)

These devices report as ON_OFF_LIGHT (0x0100), causing HA to create a light
entity instead of a switch.

This quirk:
  1. Changes device_type to ON_OFF_OUTPUT so HA shows a switch entity.
  2. Drops phantom metering clusters if present.
  3. Replaces OnOff with TuyaZBOnOffAttributeCluster to expose:
       - backlight_mode  (0x8001) — indicator LED mode
       - power_on_state  (0x8002) — relay status on power-up
  4. (_TZ3000_tqlv4ug4 only) Replaces 0xE001 with
     TuyaZBExternalSwitchTypeCluster to expose external_switch_type.
"""

import zigpy.types as t
from zigpy.profiles import zha
from zigpy.quirks.v2 import EntityType, QuirkBuilder

from zhaquirks.tuya import (
    ExternalSwitchType,
    PowerOnState,
    SwitchBackLight,
    TuyaZBExternalSwitchTypeCluster,
    TuyaZBOnOffAttributeCluster,
)

ONOFF = TuyaZBOnOffAttributeCluster.cluster_id          # 0x0006
EXT_SW = TuyaZBExternalSwitchTypeCluster.cluster_id     # 0xE001


class WoowIndicatorMode(t.enum8):
    """Backlight / indicator LED mode (OnOff 0x8001), raw 0/1/2 for this device.

    Replaces the upstream ``SwitchBackLight`` (generic Mode_0/1/2 labels) so the
    select shows meaningful labels. Member names render with underscores→spaces:
    "Off" / "Switch Status" / "Switch Position".
      0 = Off             – indicator never lit
      1 = Switch_Status   – LED lit when the relay is ON
      2 = Switch_Position – LED lit when the relay is OFF (locator / find-in-dark)
    """

    Off = 0x00
    Switch_Status = 0x01
    Switch_Position = 0x02

# ────────────────────────────────────────────────────────────────
# _TZ3000_tqlv4ug4  TS0001  (with metering clusters to remove)
# ────────────────────────────────────────────────────────────────
(
    QuirkBuilder("_TZ3000_tqlv4ug4", "TS0001")
    .replaces_endpoint(
        endpoint_id=1,
        device_type=zha.DeviceType.ON_OFF_OUTPUT,
    )
    .removes(cluster_id=0x0702, endpoint_id=1)       # Metering
    .removes(cluster_id=0x0B04, endpoint_id=1)       # Electrical Measurement
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=1)
    .replaces(TuyaZBExternalSwitchTypeCluster, endpoint_id=1)
    .enum(
        TuyaZBOnOffAttributeCluster.AttributeDefs.power_on_state.name,
        PowerOnState,
        ONOFF,
        endpoint_id=1,
        entity_type=EntityType.CONFIG,
        translation_key="power_on_state",
        fallback_name="Relay Status",
    )
    .enum(
        TuyaZBExternalSwitchTypeCluster.AttributeDefs.external_switch_type.name,
        ExternalSwitchType,
        EXT_SW,
        endpoint_id=1,
        entity_type=EntityType.CONFIG,
        translation_key="external_switch_type",
        fallback_name="Switch Type",
    )
    .add_to_registry()
)


# ────────────────────────────────────────────────────────────────
# _TZ3000_tuucc0f5  TS0001  (no metering clusters)
# ────────────────────────────────────────────────────────────────
(
    QuirkBuilder("_TZ3000_tuucc0f5", "TS0001")
    .replaces_endpoint(
        endpoint_id=1,
        device_type=zha.DeviceType.ON_OFF_OUTPUT,
    )
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=1)
    .enum(
        TuyaZBOnOffAttributeCluster.AttributeDefs.backlight_mode.name,
        SwitchBackLight,
        ONOFF,
        endpoint_id=1,
        entity_type=EntityType.CONFIG,
        translation_key="backlight_mode",
        fallback_name="Indicator Mode",
    )
    .enum(
        TuyaZBOnOffAttributeCluster.AttributeDefs.power_on_state.name,
        PowerOnState,
        ONOFF,
        endpoint_id=1,
        entity_type=EntityType.CONFIG,
        translation_key="power_on_state",
        fallback_name="Power On State",
    )
    .add_to_registry()
)


# ────────────────────────────────────────────────────────────────
# _TZ3000_voy7mbpw  TS0001  (switch panel, same pattern as tuucc0f5)
# ────────────────────────────────────────────────────────────────
(
    QuirkBuilder("_TZ3000_voy7mbpw", "TS0001")
    .replaces_endpoint(
        endpoint_id=1,
        device_type=zha.DeviceType.ON_OFF_OUTPUT,
    )
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=1)
    .enum(
        TuyaZBOnOffAttributeCluster.AttributeDefs.backlight_mode.name,
        WoowIndicatorMode,
        ONOFF,
        endpoint_id=1,
        entity_type=EntityType.CONFIG,
        translation_key="backlight_mode",
        fallback_name="Indicator Mode",
    )
    .enum(
        TuyaZBOnOffAttributeCluster.AttributeDefs.power_on_state.name,
        PowerOnState,
        ONOFF,
        endpoint_id=1,
        entity_type=EntityType.CONFIG,
        translation_key="power_on_state",
        fallback_name="Power On State",
    )
    # Redundant firmware/OTA update entity (no ZHA-distributable image for this Tuya device).
    .prevent_default_entity_creation(unique_id_suffix="firmware_update")
    .add_to_registry()
)


# ────────────────────────────────────────────────────────────────
# _TZ3000_6m2xazd1  TS0001  (WOOW "新版零火智能開關-1開", same pattern as voy7mbpw)
# ────────────────────────────────────────────────────────────────
(
    QuirkBuilder("_TZ3000_6m2xazd1", "TS0001")
    .replaces_endpoint(
        endpoint_id=1,
        device_type=zha.DeviceType.ON_OFF_OUTPUT,
    )
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=1)
    .enum(
        TuyaZBOnOffAttributeCluster.AttributeDefs.backlight_mode.name,
        WoowIndicatorMode,
        ONOFF,
        endpoint_id=1,
        entity_type=EntityType.CONFIG,
        translation_key="backlight_mode",
        fallback_name="Indicator Mode",
    )
    .enum(
        TuyaZBOnOffAttributeCluster.AttributeDefs.power_on_state.name,
        PowerOnState,
        ONOFF,
        endpoint_id=1,
        entity_type=EntityType.CONFIG,
        translation_key="power_on_state",
        fallback_name="Power On State",
    )
    # Redundant firmware/OTA update entity (no ZHA-distributable image for this Tuya device).
    .prevent_default_entity_creation(unique_id_suffix="firmware_update")
    .add_to_registry()
)


# ────────────────────────────────────────────────────────────────
# _TZ3000_2xmrrjir  TS0011  (WOOW "新版單火智能開關-1開", single-live-wire)
#
# Single-live-wire (單火) sibling of the zero-fire _TZ3000_6m2xazd1 above.
# Tuya cloud: product WO_50804_1S / product_id 2xmrrjir / IEEE
# a4:c1:38:3b:fb:3b:a1:70. Reports as ON_OFF_LIGHT (0x0100) → flipped to switch.
#
# NOTE: unlike 6m2xazd1, the indicator-mode (0x8001) and power-on-state (0x8002)
# selects are INTENTIONALLY NOT exposed. This firmware ACKs standard-ZCL writes to
# those attributes but does not apply them — verified live on 192.168.2.124: the
# device holds fixed 0x8001=0 / 0x8002=1 regardless of what is written (read != written,
# stable across reads). There is no 0xEF00 Tuya-DP cluster on this device (in-clusters
# {0,3,4,5,6}, out {10,25}), so ZHA has no channel to configure them — the settings are
# only honoured via the Tuya gateway's DP path. Exposing them would be misleading
# non-functional controls, so we ship just the relay switch. (countdown_1 is likewise
# Tuya-DP only.) std StartUpOnOff 0x4003 is UNSUPPORTED; OTA 0x0019 → firmware suppressed.
# ────────────────────────────────────────────────────────────────
(
    QuirkBuilder("_TZ3000_2xmrrjir", "TS0011")
    .replaces_endpoint(
        endpoint_id=1,
        device_type=zha.DeviceType.ON_OFF_OUTPUT,
    )
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=1)
    # 0x8001 backlight_mode & 0x8002 power_on_state intentionally NOT exposed — see NOTE above.
    # Redundant firmware/OTA update entity (no ZHA-distributable image for this Tuya device).
    .prevent_default_entity_creation(unique_id_suffix="firmware_update")
    .add_to_registry()
)
