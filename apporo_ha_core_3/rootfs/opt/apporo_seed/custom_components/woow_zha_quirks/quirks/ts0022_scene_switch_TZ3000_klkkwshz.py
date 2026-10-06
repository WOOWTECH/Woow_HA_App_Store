"""ZHA Quirk for Simon 12-70E8306 2-position scene switch.

Device:
  - Catalog:      12-70E8306 (Simon i7, gen 3 / S2100-E830-6TY)
  - Manufacturer: _TZ3000_klkkwshz
  - Model:        TS0022
  - IEEE:         6c:e4:a4:ff:fe:c4:c7:16

Standard ZCL 2-endpoint device (OnOff 0x0006 on EP1 & EP2; on/off works natively).
This quirk:
  1. Replaces OnOff on EP1 & EP2 with TuyaZBOnOffAttributeCluster (a superset of
     OnOff; switching is unaffected) to surface the Tuya backlight_mode (0x8001) —
     i.e. the Tuya-app "指示燈模式" / light_mode.
  2. Exposes one device-global "Indicator Mode" select on EP1 (0x8001). Labels
     match Tuya light_mode none/relay/pos: 0 = Close, 1 = Switch Status,
     2 = Switch Position (= 關閉 / 狀態 / 位置).
  3. Removes the two dead StartUpOnOff ("啟動時的通電行為") selects (0x4003) — the
     panel ignores that ZCL attribute. The two OnOff switches are left untouched.

ZHA renders an enum-select option from the member name (underscores shown as
spaces), so member names use underscores for the spaces in the displayed labels.
"""

import logging

import zigpy.types as t
from zigpy.quirks import CustomCluster
from zigpy.quirks.v2 import EntityType, QuirkBuilder
from zigpy.zcl import ClusterType
from zigpy.zcl.clusters.general import OnOff

from zhaquirks.tuya import TuyaZBOnOffAttributeCluster

_LOGGER = logging.getLogger(__name__)

ONOFF = TuyaZBOnOffAttributeCluster.cluster_id  # 0x0006
TUYA_PRESS_CMD = 0xFB  # Tuya "button pressed" command on OnOff, unicast to the coordinator


class ScenePressOnOffCluster(CustomCluster, OnOff):
    """OnOff OUTPUT (client) cluster: turn a physical gang press into an HA switch toggle.

    Once a gang is "activated" (a scene stored in group 0x270f + its output OnOff bound to the
    coordinator — see ``scene_activate.py``), a physical press makes the device
    emit ``OnOff cmd 0xFB`` **from that gang's endpoint, unicast to the coordinator** (verified
    on the Tuya gateway and on ZHA — see ``docs/7-12-gateway-full-sniff-findings.md``). We catch
    it here and toggle this endpoint's **server** OnOff (send On/Off); the device honours it
    (relay engages, backlight steady) and reports ``on_off`` back, so the switch entity follows.
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
            "TS0022 press EP%s -> %s", self.endpoint.endpoint_id, "On" if target_on else "Off"
        )
        await server.command(0x01 if target_on else 0x00, expect_reply=False)


class WoowSceneIndicatorMode(t.enum8):
    """Indicator LED mode (OnOff 0x8001) — labels match Tuya light_mode.

    Tuya range none/relay/pos; integer values match device attribute 0x8001:
      0 = none  (Close)           – indicator off
      1 = relay (Switch Status)   – LED tracks the gang's on/off state
      2 = pos   (Switch Position) – LED used as a locator
    """

    Close = 0x00
    Switch_Status = 0x01
    Switch_Position = 0x02


(
    QuirkBuilder("_TZ3000_klkkwshz", "TS0022")
    # ── Replace OnOff server on both gangs (superset of OnOff; switching unaffected) ──
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=1)
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=2)
    # ── Replace OnOff OUTPUT (client) → catch the press cmd 0xFB → toggle the switch ──
    .replaces(ScenePressOnOffCluster, cluster_id=ONOFF, cluster_type=ClusterType.Client, endpoint_id=1)
    .replaces(ScenePressOnOffCluster, cluster_id=ONOFF, cluster_type=ClusterType.Client, endpoint_id=2)
    # ── Remove the two dead StartUpOnOff ("啟動時的通電行為") selects ──
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=ONOFF, unique_id_suffix="StartUpOnOff",
    )
    .prevent_default_entity_creation(
        endpoint_id=2, cluster_id=ONOFF, unique_id_suffix="StartUpOnOff",
    )
    # ── Indicator (backlight) LED mode select on EP1 (0x8001), Tuya-app labels ──
    .enum(
        TuyaZBOnOffAttributeCluster.AttributeDefs.backlight_mode.name,
        WoowSceneIndicatorMode,
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
