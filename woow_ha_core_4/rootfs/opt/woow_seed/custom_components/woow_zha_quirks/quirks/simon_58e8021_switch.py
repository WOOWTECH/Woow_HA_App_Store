"""ZHA quirk for Simon 7-58E8021 — Tuya TS0034 6-button scene panel.

Device:
  - Catalog:      7-58E8021 (Simon-home "六位智能场景开关" — 6-position scene switch)
  - Manufacturer: _TZ3000_hebcnahz
  - Model:        TS0034
  - IEEE:         7c:31:fa:ff:fe:3d:ea:0a

Used here as a plain 6-gang on/off switch. This is a standard ZCL device
(genOnOff 0x0006 on EP1-6; on/off works natively), NOT a Tuya MCU (TS0601)
device. device_type is already 0x0004 (On/Off Switch), so ZHA renders six
switch entities natively — no device_type override needed.

This quirk:
  1. Replaces OnOff on EP1-6 with TuyaZBOnOffAttributeCluster (a superset of
     OnOff; switching is unaffected) to surface the Tuya backlight_mode (0x8001).
  2. Exposes a single device-global "Indicator Mode" select on EP1. Labels match
     the Tuya DP37 light_mode (none / relay / pos), i.e. this device's actual
     0x8001 raw values: 0 = Close, 1 = Switch Status, 2 = Switch Position.
  3. Suppresses the six native StartUpOnOff "power-on behavior" selects (0x4003).
     This device has no Tuya power-on datapoint and ignores the attribute, so
     those selects do nothing.
  4. Collapses the six duplicate firmware/OTA update entities to one. The OTA
     cluster (0x0019) is an output cluster on every endpoint, so stock ZHA makes
     one update entity per gang; EP2-6's are suppressed (EP1's is kept).

Out of scope (per project decision — used as plain switches): the per-button
scene/press event layer. The sibling 4-58E8017 knob quirk shows that pattern
(event-firing client OnOff cluster + switch_mode=Event), but it requires a
delete + re-pair to apply. The 0xE001 / 0xEF00 manufacturer clusters are left
untouched (harmless).

ZHA renders an enum-select option from the member name (underscores shown as
spaces), so member names use underscores for the spaces in the displayed labels.
"""

import logging

import zigpy.types as t
from zigpy.quirks import CustomCluster
from zigpy.quirks.v2 import EntityType, QuirkBuilder
from zigpy.zcl import ClusterType
from zigpy.zcl.clusters.general import OnOff, Ota

from zhaquirks.tuya import TuyaZBOnOffAttributeCluster

_LOGGER = logging.getLogger(__name__)

ONOFF = TuyaZBOnOffAttributeCluster.cluster_id  # 0x0006
OTA = Ota.cluster_id  # 0x0019 (25)
TUYA_PRESS_CMD = 0xFB  # Tuya "button pressed" command on OnOff, unicast to the coordinator


class ScenePressOnOffCluster(CustomCluster, OnOff):
    """OnOff OUTPUT (client) cluster: turn a physical gang press into an HA switch toggle.

    Once a gang is "activated" (a scene stored in group 0x270f + its output OnOff bound to the
    coordinator — see ``scene_activate.py``), a physical press makes the device
    emit ``OnOff cmd 0xFB`` **from that gang's endpoint, unicast to the coordinator** (verified
    on the Tuya gateway and on ZHA — see ``docs/7-12-gateway-full-sniff-findings.md``). We catch
    it here and toggle this endpoint's **server** OnOff (send On/Off); the device honours it
    (relay engages, backlight steady) and reports ``on_off`` back, so the switch entity follows.
    Source endpoint = gang, so each button drives its own switch.
    """

    def handle_cluster_request(self, hdr, args, *, dst_addressing=None):
        if hdr.command_id == TUYA_PRESS_CMD:
            self.create_catching_task(self._toggle())
        return super().handle_cluster_request(hdr, args, dst_addressing=dst_addressing)

    async def _toggle(self):
        server = self.endpoint.in_clusters.get(ONOFF)
        if server is None:
            return
        target_on = not bool(server.get("on_off"))
        _LOGGER.debug(
            "58E8021 press EP%s -> %s", self.endpoint.endpoint_id, "On" if target_on else "Off"
        )
        await server.command(0x01 if target_on else 0x00, expect_reply=False)


class WoowSceneIndicatorMode(t.enum8):
    """Indicator LED mode (0x8001) — labels match Tuya DP37 light_mode.

    Integer values match the device attribute 0x8001:
      0 = none  (Close)            – indicator off
      1 = relay (Switch Status)    – LED tracks the gang's on/off state
      2 = pos   (Switch Position)  – LED used as a locator / find-in-dark
    """

    Close = 0x00
    Switch_Status = 0x01
    Switch_Position = 0x02


(
    QuirkBuilder("_TZ3000_hebcnahz", "TS0034")
    # ── EP1-6: replace OnOff server → Tuya OnOff (adds backlight_mode; switching native) ──
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=1)
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=2)
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=3)
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=4)
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=5)
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=6)
    # ── EP1-6: replace OnOff OUTPUT (client) → catch the press cmd 0xFB → toggle the switch ──
    .replaces(ScenePressOnOffCluster, cluster_id=ONOFF, cluster_type=ClusterType.Client, endpoint_id=1)
    .replaces(ScenePressOnOffCluster, cluster_id=ONOFF, cluster_type=ClusterType.Client, endpoint_id=2)
    .replaces(ScenePressOnOffCluster, cluster_id=ONOFF, cluster_type=ClusterType.Client, endpoint_id=3)
    .replaces(ScenePressOnOffCluster, cluster_id=ONOFF, cluster_type=ClusterType.Client, endpoint_id=4)
    .replaces(ScenePressOnOffCluster, cluster_id=ONOFF, cluster_type=ClusterType.Client, endpoint_id=5)
    .replaces(ScenePressOnOffCluster, cluster_id=ONOFF, cluster_type=ClusterType.Client, endpoint_id=6)
    # ── Suppress the six dead StartUpOnOff "power-on behavior" selects (EP1-6) ──
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=ONOFF, unique_id_suffix="StartUpOnOff"
    )
    .prevent_default_entity_creation(
        endpoint_id=2, cluster_id=ONOFF, unique_id_suffix="StartUpOnOff"
    )
    .prevent_default_entity_creation(
        endpoint_id=3, cluster_id=ONOFF, unique_id_suffix="StartUpOnOff"
    )
    .prevent_default_entity_creation(
        endpoint_id=4, cluster_id=ONOFF, unique_id_suffix="StartUpOnOff"
    )
    .prevent_default_entity_creation(
        endpoint_id=5, cluster_id=ONOFF, unique_id_suffix="StartUpOnOff"
    )
    .prevent_default_entity_creation(
        endpoint_id=6, cluster_id=ONOFF, unique_id_suffix="StartUpOnOff"
    )
    # ── Suppress ALL firmware/OTA update entities (EP1-6) ──
    # No ZHA-distributable OTA image for this Tuya device; one rule drops every gang.
    .prevent_default_entity_creation(unique_id_suffix="firmware_update")
    # ── Indicator (backlight) LED mode select on EP1, Tuya-app labels ──
    .enum(
        TuyaZBOnOffAttributeCluster.AttributeDefs.backlight_mode.name,
        WoowSceneIndicatorMode,
        ONOFF,
        endpoint_id=1,
        entity_type=EntityType.CONFIG,
        translation_key="backlight_mode",
        fallback_name="Indicator Mode",
    )
    .add_to_registry()
)
