"""ZHA Quirk for Tuya TS0002 2-gang switch modules (light→switch fix).

Covers:
  - _TZ3000_denobasq   TS0002  2-gang
  - _TZ3000_vnzfigh4   TS0002  2-gang  (WOOW "新版零火智能開關-2開")
  - _TZ3000_zbzxnuaq   TS0002  2-gang

All report both endpoints as ON_OFF_LIGHT (0x0100), so HA creates *light*
entities instead of switches, and expose the inert Tuya OTA cluster (0x0019)
that spawns a permanently-unavailable ``update`` entity.

This quirk (shared builder for every manufacturer above):
  1. Changes device_type on EP1+EP2 to ON_OFF_SWITCH (0x0004) → proper switch
     entities. (ON_OFF_OUTPUT made ZHA drive both gangs off a single shared
     state — toggling one gang toggled the other; ON_OFF_SWITCH keeps them
     independent, matching the sibling Simon TS0003 quirks.)
  2. Replaces OnOff on both endpoints with TuyaZBOnOffAttributeCluster to expose:
       - backlight_mode  (0x8001) — indicator LED mode (EP1, global)
       - power_on_state  (0x8002) — relay status on power-up (EP1, global; see below)
  3. Labels the indicator select with WoowIndicatorMode (Off / Switch Status /
     Switch Position) instead of the generic upstream Mode_0/1/2.
  4. Suppresses the redundant firmware/OTA update entity.
"""

import zigpy.types as t
from zigpy.profiles import zha
from zigpy.quirks.v2 import CustomDeviceV2, EntityType, QuirkBuilder

from zhaquirks.tuya import (
    BaseEnchantedDevice,
    PowerOnState,
    TuyaZBOnOffAttributeCluster,
)

ONOFF = TuyaZBOnOffAttributeCluster.cluster_id          # 0x0006


class EnchantedDeviceV2(CustomDeviceV2, BaseEnchantedDevice):
    """v2 device class that casts the Tuya 'spell' on join.

    Without the spell these TS0002 units echo a state report from EVERY endpoint
    whenever ANY endpoint receives an on/off command, so HA sees all gangs toggle
    together (a command to gang 1 makes the device report gang 2 changed too).
    The upstream `zhaquirks.tuya.ts000x.Switch_2G_GPP` inherits `EnchantedDevice`
    for exactly this reason; our v2 quirk replaced it, so it must re-cast the
    spell to keep the gangs INDEPENDENT. See zha-device-handlers #1580 / #1613.
    """


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


def _build_2gang(manufacturer: str) -> None:
    """Register the WOOW-standard 2-gang TS0002 switch quirk for one manufacturer.

    Power-on state is a **single global** setting over ZHA (EP1 only). Although
    the Tuya app can set the restart status *per gang* (the cloud thing-model
    exposes ``relay_status_1`` / ``relay_status_2``), that is a Tuya-MCU DP
    feature handled through the Tuya gateway — these standard-ZCL devices only
    implement ``power_on_state`` (0x8002) on EP1. Verified live on ZHA: an EP2
    ``0x8002`` write returns ``UNSUPPORTED_ATTRIBUTE`` while EP1 accepts it. So
    only one Power On State select is exposed (a per-gang EP2 select would just
    error on every write).
    """
    (
        QuirkBuilder(manufacturer, "TS0002")
        # ── Cast the Tuya spell on join so the gangs stay INDEPENDENT (else the
        #    device echoes a report from every endpoint on any on/off command). ──
        .device_class(EnchantedDeviceV2)
        # ── device_type per gang → ON_OFF_SWITCH (0x0004): switch, not light. ──
        .replaces_endpoint(endpoint_id=1, device_type=zha.DeviceType.ON_OFF_SWITCH)
        .replaces_endpoint(endpoint_id=2, device_type=zha.DeviceType.ON_OFF_SWITCH)
        # ── Replace OnOff on both endpoints ──
        .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=1)
        .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=2)
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
        # ── EP1: power-on state (global; EP2 0x8002 is UNSUPPORTED over ZHA) ──
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


for _mfr in ("_TZ3000_denobasq", "_TZ3000_vnzfigh4", "_TZ3000_zbzxnuaq"):
    _build_2gang(_mfr)
