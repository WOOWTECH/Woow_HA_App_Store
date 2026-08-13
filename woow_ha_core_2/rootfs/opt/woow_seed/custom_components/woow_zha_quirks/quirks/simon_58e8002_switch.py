"""ZHA Quirk for Simon 2-58E8002 2-gang relay switch.

Device:
  - Catalog:      2-58E8002 (Simon-home)
  - Manufacturer: _TZ2000_euqqstyrbiynph3m
  - Model:        S2100-1002
  - IEEE:         e4:56:ac:ff:fe:74:9a:af

Standard ZCL 2-gang switch (OnOff 0x0006 on EP1 & EP2; on/off works natively).
The Tuya manufacturer attribute backlight_mode (0x8001) on the OnOff cluster is
not surfaced by stock ZHA — this quirk replaces OnOff with
TuyaZBOnOffAttributeCluster and exposes it as an "Indicator Mode" select.
The two standard StartUpOnOff ("啟動時的通電行為") selects are removed.

Backlight mode (0x8001) labels match the Tuya app for this device:
  0 = Close, 1 = Switch Status, 2 = Switch Position
"""

import zigpy.types as t
from zigpy.quirks.v2 import EntityType, QuirkBuilder

from zhaquirks.tuya import TuyaZBOnOffAttributeCluster

ONOFF = TuyaZBOnOffAttributeCluster.cluster_id  # 0x0006


class SimonKgBacklightMode(t.enum8):
    """Indicator LED mode — labels match the Tuya app for 2-58E8002.

    ZHA renders an enum entity's state from the member name (underscores
    shown as spaces), so these display as "Close" / "Switch Status" /
    "Switch Position". Integer values match the device attribute 0x8001.
    """

    Close = 0x00
    Switch_Status = 0x01
    Switch_Position = 0x02


(
    QuirkBuilder("_TZ2000_euqqstyrbiynph3m", "S2100-1002")
    # ── Replace OnOff on both gangs (superset of OnOff; switching unaffected) ──
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=1)
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=2)
    # ── Remove the two standard StartUpOnOff ("啟動時的通電行為") selects ──
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=ONOFF, unique_id_suffix="StartUpOnOff",
    )
    .prevent_default_entity_creation(
        endpoint_id=2, cluster_id=ONOFF, unique_id_suffix="StartUpOnOff",
    )
    # ── Indicator/backlight mode (0x8001) — single device-global select on EP1 ──
    .enum(
        TuyaZBOnOffAttributeCluster.AttributeDefs.backlight_mode.name,
        SimonKgBacklightMode,
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
