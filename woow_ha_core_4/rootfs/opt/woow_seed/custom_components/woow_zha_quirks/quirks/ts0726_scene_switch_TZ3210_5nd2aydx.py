"""ZHA quirk for Simon "10-66E8025" — Tuya TS0726 8-gang scene+switch panel.

Device:
  - Catalog:      10-66E8025  (Simon-home "八位智能场景开关" — 8-position scene switch)
  - Manufacturer: _TZ3210_5nd2aydx
  - Model:        TS0726
  - IEEE:         34:25:b4:ff:fe:cf:bc:00
  - Tuya product: 5nd2aydx (category cjkg — scene / wall panel)

This is the 8-gang sibling of the 4-gang panel handled by
``ts0726_scene_switch_TZ3002_v0xabl0o.py`` (_TZ3002_v0xabl0o / TS0726). Same
cluster shape. It is a standard ZCL device (genOnOff 0x0006; on/off works
natively), NOT a Tuya MCU (TS0601) device. device_type is already 0x0004 (On/Off
Switch), so ZHA renders switch entities natively — no device_type override needed.

Real signature (EP1-9, profile 0x0104, device_type 0x0004):
  IN : 0x0000 Basic, 0x0003 Identify, 0x0004 Groups, 0x0005 Scenes,
       0x0006 OnOff, 0xE000, 0xE001, 0xEF00 (Tuya)
  OUT: 0x0005 Scenes, 0x0006 OnOff, 0x0019 OTA

ENDPOINTS: the device advertises NINE identical ZCL endpoints, but only 8 are
physical gangs. The true mapping is **EP_N -> physical switch N (1-8)**, and
**EP9 is the phantom** (no relay) — removed by the quirk. (An earlier revision
wrongly removed EP1 instead, inferring from the Tuya cloud labels ``switch_2..9``
that there was "no switch 1"; that left physical switch 1 — which lives on EP1 —
without an entity and stuck in scene mode. Confirmed live: toggling the EP9 entity
controls nothing, and physical switch 1 is on EP1. Lesson: do not infer the ZCL
endpoint->physical mapping from Tuya DP labels — confirm with a per-endpoint toggle.)

Mapping of the Tuya cloud DP model (tuya_export/DP_REFERENCE.md) onto Zigbee:
  - switch_* -> native OnOff (0x0006) on EP1-8 = physical switches 1-8 (works OOTB)
  - DP37  light_mode  -> OnOff attr 0x8001 backlight_mode (indicator LED mode)
  - mode_* -> 0xE001 attr 0xD020 (per-gang scene vs switch)

This file:
  1. Removes the phantom EP9, then replaces OnOff on EP1-8 with
     WoowForceSwitchOnOffCluster (a TuyaZBOnOffAttributeCluster that also forces the
     gang into Switch/relay mode — see below); on/off switching is unaffected.
  2. FORCES every gang into Switch (relay) mode. Each gang can be a relay
     (``switch``) or a scene trigger (``scene``); in scene mode the relay is
     disabled and the switch entity is inert. To guarantee every switch entity is a
     *regular switch*, the OnOff cluster writes 0xE001 ``gang_mode`` = Switch on the
     first frame after startup (retried until it lands). The device persists the
     setting, so this is permanent and self-heals after any drift/re-pair. The
     per-gang "Gang N Mode" select was removed at the user's request (changing it was
     unreliable, and scene mode is not wanted on this device).
  3. Exposes one device-global "Indicator Mode" select on EP1 (0x8001). cjkg DP37
     labels are none / enable_white / enable_yellow.
  4. Suppresses the dead StartUpOnOff "power-on behavior" selects (EP1-8).
  5. Collapses the duplicate firmware/OTA update entities to one (keep EP1).

Backlight on/off (DP36) and brightness (DP105) are NOT exposed — they were
removed at the user's request (the 0xEF00 DP layer that previously bridged them
created unwanted ``…_backlight`` / ``…_backlight_brightness`` entities).

The scene-press *event* layer (DP2-9) does not apply now that all gangs are forced
to Switch mode.

ZHA renders an enum-select option from the member name (underscores shown as
spaces), so member names use underscores for the spaces in the displayed labels.
"""

import asyncio
import logging
from typing import Final

import zigpy.types as t
from zigpy.quirks.v2 import EntityType, QuirkBuilder
from zigpy.zcl.clusters.general import Ota
from zigpy.zcl.foundation import ZCLAttributeDef

from zhaquirks.tuya import (
    TuyaZBExternalSwitchTypeCluster,
    TuyaZBOnOffAttributeCluster,
)

_LOGGER = logging.getLogger(__name__)

ONOFF = TuyaZBOnOffAttributeCluster.cluster_id  # 0x0006
OTA = Ota.cluster_id  # 0x0019 (25)
E001 = TuyaZBExternalSwitchTypeCluster.cluster_id  # 0xE001

# Physical gang endpoints. The device advertises 9 identical ZCL endpoints, but
# the true mapping is EP_N → physical switch N (1-8); EP9 is the phantom (no relay)
# and is removed below. The 8 real gangs are EP1-8.
_ENDPOINTS = (1, 2, 3, 4, 5, 6, 7, 8)


class WoowIndicatorMode(t.enum8):
    """Indicator LED mode (OnOff 0x8001) — labels match Tuya DP37 light_mode.

    cjkg light_mode for this panel is none / enable_white / enable_yellow.
    Integer values match device attribute 0x8001 (confirm value->LED live):
      0 = none   (Close)   – indicator off
      1 = White  (enable_white)
      2 = Yellow (enable_yellow)
    """

    Close = 0x00
    White = 0x01
    Yellow = 0x02


class WoowGangMode(t.enum8):
    """Per-gang relay vs scene-trigger mode (Tuya mode_2..9 / 0xE001 0xD020).

    NOTE: this _TZ3210_ panel's enum order is REVERSED vs the 4-gang _TZ3002_
    sibling. tuya_export/DP_REFERENCE.md lists mode_2..9 as ``scene_N / switch_N``
    (index 0 = scene, 1 = switch), whereas the 4-gang lists ``switch_N / scene_N``.
    Confirmed live: selecting "Switch" with the old 0=Switch mapping put the gang
    into scene behaviour. Correct mapping for this device:
      0 = Scene  – gang acts as a scene trigger (no local relay)
      1 = Switch – gang drives its local relay
    """

    Scene = 0x00
    Switch = 0x01


class WoowSceneSwitchE001Cluster(TuyaZBExternalSwitchTypeCluster):
    """Tuya 0xE001 cluster extended with the per-gang mode attribute 0xD020.

    Inherits ``external_switch_type`` (0xD030) from the zhaquirks base and adds
    ``gang_mode`` (0xD020) so it can be exposed as a per-endpoint select.
    """

    class AttributeDefs(TuyaZBExternalSwitchTypeCluster.AttributeDefs):
        """Attribute definitions (base + gang_mode)."""

        gang_mode: Final = ZCLAttributeDef(id=0xD020, type=WoowGangMode)


class WoowForceSwitchOnOffCluster(TuyaZBOnOffAttributeCluster):
    """OnOff server that forces this gang into Switch (relay) mode.

    A gang can be a relay (``switch``) or a scene trigger (``scene``); in scene
    mode the relay is disabled and the switch entity is inert. To guarantee every
    switch entity is a *regular switch*, on the first frame from the device we write
    the sibling 0xE001 ``gang_mode`` to Switch when it isn't already (retried on the
    next frame if the write fails). The device persists the value, so one success is
    permanent and this self-heals after any drift / re-pair. On/off switching is
    otherwise unaffected (this just augments the OnOff cluster's frame handler).
    """

    def __init__(self, *args, **kwargs):
        """Init the force-write guards."""
        super().__init__(*args, **kwargs)
        self._switch_forced = False  # set True only once Switch is *confirmed*
        self._write_in_flight = False

    def handle_cluster_general_request(self, hdr, args, *, dst_addressing=None):
        """Pass the frame through, then ensure this gang is in Switch mode."""
        super().handle_cluster_general_request(
            hdr, args, dst_addressing=dst_addressing
        )
        self._ensure_switch_mode()

    def _ensure_switch_mode(self) -> None:
        """Write gang_mode = Switch and verify; retry on a later frame if needed.

        The device can ACK a write without applying it (the unreliability the user
        hit), so we read the value back and only stop once Switch is confirmed. The
        device persists the value, so this normally lands once and then no-ops.
        """
        if self._switch_forced or self._write_in_flight:
            return
        e001 = self.endpoint.in_clusters.get(E001)
        if e001 is None:
            return
        name = WoowSceneSwitchE001Cluster.AttributeDefs.gang_mode.name
        cached = e001.get(name)
        if cached is not None and int(cached) == WoowGangMode.Switch:
            self._switch_forced = True  # already a regular switch
            return
        self._write_in_flight = True

        async def _write() -> None:
            try:
                await e001.write_attributes({name: WoowGangMode.Switch})
                await e001.read_attributes([name])  # refresh cache to verify
                val = e001.get(name)
                if val is not None and int(val) == WoowGangMode.Switch:
                    self._switch_forced = True
                    _LOGGER.debug(
                        "10-66E8025 EP%s forced to Switch mode",
                        self.endpoint.endpoint_id,
                    )
            except Exception:  # noqa: BLE001
                pass  # leave _switch_forced False → retry on the next frame
            finally:
                self._write_in_flight = False

        try:
            asyncio.ensure_future(_write())
        except Exception:  # noqa: BLE001
            self._write_in_flight = False


_builder = QuirkBuilder("_TZ3210_5nd2aydx", "TS0726")

# ── Drop the phantom EP9 (no physical relay; gangs are EP1-8 = physical sw 1-8) ──
_builder = _builder.removes_endpoint(endpoint_id=9)

# ── EP1-8: OnOff → force-Switch Tuya OnOff superset; 0xE001 cluster (gang_mode
#           attr, written to Switch by the OnOff hook); suppress the dead
#           StartUpOnOff "power-on behavior" select ──
for _ep in _ENDPOINTS:
    _builder = (
        _builder.replaces(WoowForceSwitchOnOffCluster, endpoint_id=_ep)
        .replaces(WoowSceneSwitchE001Cluster, endpoint_id=_ep)
        .prevent_default_entity_creation(
            endpoint_id=_ep, cluster_id=ONOFF, unique_id_suffix="StartUpOnOff"
        )
    )

# ── Suppress ALL firmware/OTA update entities (EP1-8) ──
# No ZHA-distributable OTA image for this Tuya device; one rule drops every gang.
_builder = _builder.prevent_default_entity_creation(unique_id_suffix="firmware_update")

# ── EP1: single device-global Indicator (backlight) LED mode select (0x8001) ──
# (0x8001 is mirrored on every endpoint; hosted on EP1, the primary gang.)
(
    _builder.enum(
        TuyaZBOnOffAttributeCluster.AttributeDefs.backlight_mode.name,
        WoowIndicatorMode,
        ONOFF,
        endpoint_id=1,
        entity_type=EntityType.CONFIG,
        translation_key="backlight_mode",
        fallback_name="Indicator Mode",
    ).add_to_registry()
)
