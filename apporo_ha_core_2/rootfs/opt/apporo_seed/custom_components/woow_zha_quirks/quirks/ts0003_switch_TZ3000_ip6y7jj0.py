"""ZHA Quirk for WOOW 3-Gang Switches — Tuya TS0003 / TS0013.

Device info:
  - Model:        TS0003
  - Manufacturer: _TZ3000_ip6y7jj0
  - IEEE:         a4:c1:38:cd:6c:88:fd:bc
  - WOOW product: 新版零火智能開關-3開 (3-gang, neutral / zero-fire wall switch)

Also covers the single-live-wire (單火) twin at the bottom of this file:
  - Model:        TS0013
  - Manufacturer: _TZ3000_dqf2oiyz
  - IEEE:         0c:2a:6f:ff:fe:df:18:06
  - WOOW product: 新版單火智能開關-3開 (3-gang, single-live-wire wall switch)
  Same light→switch + gang-independence fix; its 0x8001/0x8002 selects are omitted
  because the single-fire firmware ignores ZCL writes to them (see that block).

The 3-gang sibling of the 2開 (`_TZ3000_vnzfigh4`, ts0002_switch_TZ3000_denobasq.py)
and the 1開 (`_TZ3000_6m2xazd1`, ts0001_switch_TZ3000_tqlv4ug4.py). Standard ZCL
(on/off via cluster 0x0006 per endpoint), NOT a Tuya MCU (TS0601) device.
Endpoints 1/2/3 are the three physical gangs; endpoint 242 is Green Power.

Out of the box, stock ZHA (upstream `Switch_3G_GPP`) exposes each gang as a
`light` (all three EPs advertise device_type 0x0100 = On/Off Light) and leaves a
permanently-unavailable firmware/OTA `update` orphan.

This quirk:
  1. Overrides each gang's device_type ON_OFF_LIGHT (0x0100) → ON_OFF_SWITCH
     (0x0004) so HA exposes proper `switch` entities AND keeps the gangs
     independent. (ON_OFF_OUTPUT made ZHA drive all gangs off a single shared
     on/off state — toggling one toggled the others; ON_OFF_SWITCH fixes it,
     matching the sibling Simon TS0003 quirk wt4t1anwyef42zv4.)
  2. Replaces OnOff on EP1-3 with TuyaZBOnOffAttributeCluster (adds the Tuya attrs
     backlight_mode / power_on_state); on/off switching is unaffected.
  3. Exposes a single device-global Indicator (backlight) LED mode select on EP1
     with WoowIndicatorMode labels (Off / Switch Status / Switch Position).
  4. Exposes a single **global** Power On State select on EP1. Although the Tuya
     app can set the restart status per gang (the cloud thing-model exposes
     relay_status_1/2/3), that is a Tuya-MCU DP feature handled through the Tuya
     gateway — this standard-ZCL device only implements power_on_state (0x8002)
     on EP1. Verified live on ZHA: an EP2/EP3 0x8002 write returns
     UNSUPPORTED_ATTRIBUTE while EP1 accepts it, so per-gang selects would only
     error on write.
  5. Suppresses the redundant per-endpoint firmware/OTA update entities.
"""

import zigpy.types as t
from zigpy.profiles import zha
from zigpy.quirks.v2 import CustomDeviceV2, EntityType, QuirkBuilder

from zhaquirks.tuya import (
    BaseEnchantedDevice,
    PowerOnState,
    TuyaZBOnOffAttributeCluster,
)

ONOFF = TuyaZBOnOffAttributeCluster.cluster_id  # 0x0006


class EnchantedDeviceV2(CustomDeviceV2, BaseEnchantedDevice):
    """v2 device class that casts the Tuya 'spell' on join.

    Without the spell this TS0003 echoes a state report from EVERY endpoint
    whenever ANY endpoint receives an on/off command, so HA sees all gangs toggle
    together. The upstream `zhaquirks.tuya.ts000x.Switch_3G_GPP` inherits
    `EnchantedDevice` for this reason; our v2 quirk replaced it, so it must
    re-cast the spell to keep the gangs INDEPENDENT. See zha-device-handlers
    #1580 / #1613.
    """


class WoowIndicatorMode(t.enum8):
    """Backlight / indicator LED mode (OnOff 0x8001), raw 0/1/2 for this device.

    Member names render with underscores→spaces:
    "Off" / "Switch Status" / "Switch Position".
      0 = Off             – indicator never lit
      1 = Switch_Status   – LED lit when the relay is ON
      2 = Switch_Position – LED lit when the relay is OFF (locator / find-in-dark)
    """

    Off = 0x00
    Switch_Status = 0x01
    Switch_Position = 0x02


(
    QuirkBuilder("_TZ3000_ip6y7jj0", "TS0003")
    # ── Cast the Tuya spell on join so the gangs stay INDEPENDENT (else the
    #    device echoes a report from every endpoint on any on/off command). ──
    .device_class(EnchantedDeviceV2)
    # ── device_type per gang → ON_OFF_SWITCH (0x0004): switch, not light. ──
    .replaces_endpoint(endpoint_id=1, device_type=zha.DeviceType.ON_OFF_SWITCH)
    .replaces_endpoint(endpoint_id=2, device_type=zha.DeviceType.ON_OFF_SWITCH)
    .replaces_endpoint(endpoint_id=3, device_type=zha.DeviceType.ON_OFF_SWITCH)
    # ── EP1-3: real gangs → Tuya OnOff (adds backlight_mode / power_on_state) ──
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=1)
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=2)
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=3)
    # ── EP1: indicator LED mode (global) ──
    .enum(
        TuyaZBOnOffAttributeCluster.AttributeDefs.backlight_mode.name,
        WoowIndicatorMode,
        ONOFF,
        endpoint_id=1,
        entity_type=EntityType.CONFIG,
        translation_key="backlight_mode",
        fallback_name="Indicator Mode",
    )
    # ── EP1: power-on state (global; EP2/EP3 0x8002 is UNSUPPORTED over ZHA) ──
    .enum(
        TuyaZBOnOffAttributeCluster.AttributeDefs.power_on_state.name,
        PowerOnState,
        ONOFF,
        endpoint_id=1,
        entity_type=EntityType.CONFIG,
        translation_key="power_on_state",
        fallback_name="Power On State",
    )
    # ── Redundant firmware/OTA update entity (no ZHA-distributable image) ──
    .prevent_default_entity_creation(unique_id_suffix="firmware_update")
    .add_to_registry()
)


# ────────────────────────────────────────────────────────────────
# _TZ3000_dqf2oiyz  TS0013  (WOOW "新版單火智能開關-3開", single-live-wire)
#
# Single-live-wire (單火) twin of the zero-fire 3開 _TZ3000_ip6y7jj0 above — same
# standard-ZCL 3-gang shape (EP1/2/3 device_type 0x0100 ON_OFF_LIGHT, OnOff 0x0006
# per gang; no 0xEF00). IEEE 0c:2a:6f:ff:fe:df:18:06. Fixes the same two problems:
#   1. light → switch  (device_type per gang → ON_OFF_SWITCH 0x0004)
#   2. gang linkage    (re-cast the Tuya spell via EnchantedDeviceV2 so the device
#                       stops echoing a report from every endpoint; casts on
#                       pairing/RECONFIGURE, not on a plain restart).
#
# The indicator-mode (0x8001) and power-on-state (0x8002) selects are INTENTIONALLY
# NOT exposed: this single-fire firmware ACKs standard-ZCL writes to those attributes
# but does not apply them (proven on the 1開 sibling _TZ3000_2xmrrjir), and there is
# no 0xEF00 Tuya-DP channel over ZHA to configure them — they would be misleading
# non-functional controls. countdown_1 is likewise Tuya-DP only.
# ────────────────────────────────────────────────────────────────
(
    QuirkBuilder("_TZ3000_dqf2oiyz", "TS0013")
    # ── Cast the Tuya spell on join so the gangs stay INDEPENDENT. ──
    .device_class(EnchantedDeviceV2)
    # ── device_type per gang → ON_OFF_SWITCH (0x0004): switch, not light. ──
    .replaces_endpoint(endpoint_id=1, device_type=zha.DeviceType.ON_OFF_SWITCH)
    .replaces_endpoint(endpoint_id=2, device_type=zha.DeviceType.ON_OFF_SWITCH)
    .replaces_endpoint(endpoint_id=3, device_type=zha.DeviceType.ON_OFF_SWITCH)
    # ── EP1-3: real gangs → Tuya OnOff (same proven on/off path as ip6y7jj0). ──
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=1)
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=2)
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=3)
    # 0x8001 backlight_mode / 0x8002 power_on_state selects intentionally OMITTED —
    # single-fire firmware ACKs but ignores those ZCL writes; no 0xEF00 DP channel.
    # ── Redundant firmware/OTA update entity (no ZHA-distributable image) ──
    .prevent_default_entity_creation(unique_id_suffix="firmware_update")
    .add_to_registry()
)
