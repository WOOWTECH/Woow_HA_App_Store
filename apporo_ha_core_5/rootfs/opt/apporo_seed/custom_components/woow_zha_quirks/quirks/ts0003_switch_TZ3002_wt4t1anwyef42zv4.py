"""ZHA Quirk for Simon "11-241E8003TY" — Tuya TS0003 3-Gang Switch.

Device info:
  - Catalog:      11-241E8003TY  (Simon-home, category "kg")
  - Model:        TS0003
  - Manufacturer: _TZ3002_wt4t1anwyef42zv4
  - IEEE:         7c:c6:b6:ff:fe:82:f7:f2
  - Tuya product: wt4t1anwyef42zv4

This is a standard ZCL 3-gang switch (on/off via cluster 0x0006 per endpoint),
NOT a Tuya MCU (TS0601) device.  Endpoints 1, 2 and 3 are the three physical
gangs; endpoint 242 is Green Power.  There are no phantom endpoints.

Out of the box, stock ZHA presents this device awkwardly.  Its endpoints uniquely
advertise device_type 0x0100 (On/Off Light) — the sibling Simon switches
(_TZ2000_ S2100 / 2-58E8002) advertise 0x0004 (On/Off Switch) and behave well — so
ZHA:
  * exposes each gang as a `light` instead of a `switch`, and
  * adds a redundant "Opening" `binary_sensor` from the OnOff *client* cluster
    (suppressed for switch/controller device types, but not for On/Off Light).
In addition:
  * The native "Power-on behavior" (StartUpOnOff 0x4003) selects do nothing — this
    device has no power-on datapoint and ignores the attribute.
  * The Tuya indicator-LED mode (Tuya DP "light_mode", ZCL attr 0x8001) is not
    surfaced at all.

This quirk:
  1. Replaces OnOff on EP1-3 with TuyaZBOnOffAttributeCluster (adds the Tuya
     attrs backlight_mode / power_on_state); on/off switching is unaffected.
  2. Overrides each endpoint's device_type from On/Off Light (0x0100) to
     On/Off Switch (0x0004) — exactly what the sibling switches advertise.  This
     single change makes ZHA expose each gang as a `switch` (0x0004 is not in
     ZHA's LIGHT_PROFILE_DEVICE_TYPES) AND drops the redundant client-OnOff
     "Opening" binary_sensor (0x0004 is in that entity's not_profile_device_types).
  3. Suppresses the three non-functional StartUpOnOff "power-on behavior" selects.
  4. Exposes a single device-global Indicator (backlight) LED mode select on EP1,
     with labels that match the Tuya app:
        Close            (0 / "none")  – indicator off
        Switch Status    (1 / "relay") – LED on when relay closed
        Switch Position  (2 / "pos")   – LED on when relay open

Out of scope (Tuya-cloud / 0xEF00 DP features, not reliable as Zigbee attrs):
  per-gang countdown (DP 7/8/9) — see tuya_export/DP_REFERENCE.md.  Auto-off is
  best handled with a native Home Assistant automation / helper.
"""

import zigpy.types as t
from zigpy.profiles import zha
from zigpy.quirks.v2 import EntityType, QuirkBuilder

from zhaquirks.tuya import TuyaZBOnOffAttributeCluster

ONOFF = TuyaZBOnOffAttributeCluster.cluster_id  # 0x0006


class WoowKgIndicatorMode(t.enum8):
    """Indicator LED mode — labels match the Tuya app for 11-241E8003TY.

    ZHA renders an enum entity's state from the member name (underscores shown as
    spaces), so these display as "Close" / "Switch Status" / "Switch Position".
    Integer values match the device attribute 0x8001 (Tuya DP "light_mode":
    none / relay / pos).
    """

    Close = 0x00  # none – indicator off
    Switch_Status = 0x01  # relay – LED on when relay closed
    Switch_Position = 0x02  # pos – LED on when relay open


(
    QuirkBuilder("_TZ3002_wt4t1anwyef42zv4", "TS0003")
    # ── EP1-3: real gangs → Tuya OnOff (adds backlight_mode / power_on_state) ──
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=1)
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=2)
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=3)
    # ── device_type On/Off Light (0x0100) → On/Off Switch (0x0004) ──
    # Matches the sibling Simon switches: gangs become `switch` entities and the
    # redundant client-OnOff "Opening" binary_sensors are dropped.  Clusters are
    # preserved (replaces_endpoint only overrides profile_id / device_type).
    .replaces_endpoint(endpoint_id=1, device_type=zha.DeviceType.ON_OFF_SWITCH)
    .replaces_endpoint(endpoint_id=2, device_type=zha.DeviceType.ON_OFF_SWITCH)
    .replaces_endpoint(endpoint_id=3, device_type=zha.DeviceType.ON_OFF_SWITCH)
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
        WoowKgIndicatorMode,
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
