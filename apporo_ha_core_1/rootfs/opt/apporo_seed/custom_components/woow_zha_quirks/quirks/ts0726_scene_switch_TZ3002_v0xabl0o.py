"""ZHA quirk for Simon "9-241E8008TY" — Tuya TS0726 4-gang scene+switch panel.

Device:
  - Catalog:      9-241E8008TY  (Simon-home "四位智能场景开关" — 4-position scene switch)
  - Manufacturer: _TZ3002_v0xabl0o
  - Model:        TS0726
  - IEEE:         7c:c6:b6:ff:fe:82:46:64
  - Tuya product: v0xabl0o (category cjkg — scene / wall panel)

This is a 4-gang *hybrid* panel: each gang can act as a relay (switch mode) or
as a scene trigger (scene mode), selectable per-gang. It is a standard ZCL
device (genOnOff 0x0006 on EP1-4; on/off works natively), NOT a Tuya MCU
(TS0601) device. device_type is already 0x0004 (On/Off Switch), so ZHA renders
four switch entities natively — no device_type override needed.

Real signature (EP1-4, profile 0x0104, device_type 0x0004):
  IN : 0x0000 Basic, 0x0003 Identify, 0x0004 Groups, 0x0005 Scenes,
       0x0006 OnOff, 0xE000, 0xE001, 0xEF00 (Tuya)
  OUT: 0x0005 Scenes, 0x0006 OnOff, 0x0019 OTA
  EP242 Green Power.

Mapping of the Tuya cloud DP model onto the Zigbee layer:
  - DP24-27 switch_1..4  -> native OnOff (0x0006) on EP1-4 (works out of the box)
  - DP37    light_mode   -> OnOff attr 0x8001 backlight_mode (relay/pos/none)
  - DP18-21 mode_1..4    -> 0xE001 attr 0xD020 (per-gang switch vs scene mode)
  - DP1-4   scene_1..4   -> scene-press *events* (see below)

How a press surfaces on Zigbee (captured live, debug log):
  EVERY physical press is an unsolicited OnOff *server* attribute report of
  on_off (0x0000) on that gang's endpoint — there is NO 0xEF00 DP report, NO
  Scenes command and NO client-side 0xFC/0xFD command (so the TS004x rotary-knob
  pattern does NOT apply here). For a switch-mode gang the value toggles
  true/false (real relay); for a scene-mode gang it reports false on every press
  (no state change, so nothing fires natively). The device sends each press
  TWICE (~0.3 s apart). These reports already reach the coordinator with no
  binding change, so NO delete/re-pair is required for this quirk.

This quirk:
  1. Replaces OnOff on EP1-4 with WoowSwitchModeOnOffCluster — a
     TuyaZBOnOffAttributeCluster (adds backlight_mode 0x8001 / switch_mode 0x8004;
     on/off switching unaffected) that also forces each gang into *Switch* mode
     (0xE001 gang_mode 0xD020 = 0) on startup. This is required for the indicator
     LED: the relay-based backlight only drives a gang's LED when that gang is in
     Switch mode; a gang left in Scene mode shows no indicator. There is no
     scene-mode pulse and no per-gang press event.
  2. Exposes one device-global "Indicator Mode" select on EP1 (0x8001), Tuya-app
     labels (Close / Switch Status / Switch Position), mirroring the sibling
     _TZ3002_ / TS0003 (11-241E8003TY) and TS0034 (7-58E8021) quirks.
  3. Suppresses the four dead StartUpOnOff "power-on behavior" selects.
  4. Collapses the four duplicate firmware/OTA update entities to one (keep EP1).

Notes:
  - On a cold HA *restart* the quirk can lose the load-order race against ZHA and
    not apply until the ZHA integration is reloaded once (a known limitation of
    import-time quirk registration). Reload ZHA after restarting if needed.

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


class WoowIndicatorMode(t.enum8):
    """Indicator LED mode (OnOff 0x8001) — labels match Tuya DP37 light_mode.

    Integer values match this device's attribute 0x8001 (confirmed live by LED
    behaviour). NOTE: this TS0726 labels the raw 0/1/2 values differently from
    the sibling _TZ3000_ panels (which are Close=0 / Switch_Status=1 / Switch_Position=2):
      0 = relay (Switch Status)    – LED tracks the gang's on/off state
      1 = pos   (Switch Position)  – LED used as a locator / find-in-dark
      2 = none  (Close)            – indicator off
    """

    Switch_Status = 0x00
    Switch_Position = 0x01
    Close = 0x02


class WoowGangMode(t.enum8):
    """Per-gang relay vs scene-trigger mode (0xE001 0xD020): 0=Switch, 1=Scene."""

    Switch = 0x00
    Scene = 0x01


class WoowSwitchModeE001Cluster(TuyaZBExternalSwitchTypeCluster):
    """0xE001 extended with gang_mode (0xD020) so the quirk can force Switch mode.

    Not exposed as an entity — it exists only so ``WoowSwitchModeOnOffCluster`` can
    write gang_mode. (The user-facing per-gang mode selects were intentionally removed.)
    """

    class AttributeDefs(TuyaZBExternalSwitchTypeCluster.AttributeDefs):
        """Base attributes + gang_mode."""

        gang_mode: Final = ZCLAttributeDef(id=0xD020, type=WoowGangMode)


class WoowSwitchModeOnOffCluster(TuyaZBOnOffAttributeCluster):
    """OnOff superset (backlight_mode 0x8001) that forces this gang into Switch mode.

    The relay-based Indicator Mode (backlight 0x8001) only drives a gang's LED when
    that gang is in *Switch* mode; a gang left in *Scene* mode shows no indicator
    (verified live — only the one switch-mode gang's LED responded). So on the first
    frame from the device (ZHA's startup on_off read response), we write
    gang_mode=Switch (0xE001/0xD020) on this endpoint, once per session. This is
    idempotent, needs no manufacturer code, and survives a re-pair without any
    user-facing entity.
    """

    def __init__(self, *args, **kwargs):
        """Init the one-shot guard."""
        super().__init__(*args, **kwargs)
        self._switch_mode_done = False

    def handle_cluster_general_request(self, hdr, args, *, dst_addressing=None):
        """Ensure Switch mode, then handle the frame normally."""
        self._ensure_switch_mode()
        super().handle_cluster_general_request(hdr, args, dst_addressing=dst_addressing)

    def _ensure_switch_mode(self) -> None:
        """Write gang_mode=Switch to this endpoint's 0xE001 once (kicked off a frame)."""
        if self._switch_mode_done:
            return
        e001 = self.endpoint.in_clusters.get(E001)
        if e001 is None:
            return
        self._switch_mode_done = True
        name = WoowSwitchModeE001Cluster.AttributeDefs.gang_mode.name

        async def _set() -> None:
            try:
                await e001.write_attributes({name: WoowGangMode.Switch})
            except Exception:  # noqa: BLE001
                self._switch_mode_done = False  # allow a retry on the next frame
                _LOGGER.debug("force Switch mode on EP%s failed", self.endpoint.endpoint_id)

        try:
            asyncio.ensure_future(_set())
        except Exception:  # noqa: BLE001
            self._switch_mode_done = False


_builder = QuirkBuilder("_TZ3002_v0xabl0o", "TS0726")

# ── EP1-4: OnOff → Tuya superset (backlight_mode 0x8001) + force Switch mode so the
#           indicator LED works on every gang; 0xE001 carries gang_mode; suppress the
#           dead StartUpOnOff select ──
for _ep in (1, 2, 3, 4):
    _builder = (
        _builder.replaces(WoowSwitchModeOnOffCluster, endpoint_id=_ep)
        .replaces(WoowSwitchModeE001Cluster, endpoint_id=_ep)
        .prevent_default_entity_creation(
            endpoint_id=_ep, cluster_id=ONOFF, unique_id_suffix="StartUpOnOff"
        )
    )

# ── Suppress ALL firmware/OTA update entities (EP1-4) ──
# No ZHA-distributable OTA image for this Tuya device; one rule drops every gang.
_builder = _builder.prevent_default_entity_creation(unique_id_suffix="firmware_update")

# ── Single device-global Indicator (backlight) LED mode select on EP1 ──
(
    _builder.enum(
        TuyaZBOnOffAttributeCluster.AttributeDefs.backlight_mode.name,
        WoowIndicatorMode,
        ONOFF,
        endpoint_id=1,
        entity_type=EntityType.CONFIG,
        translation_key="backlight_mode",
        fallback_name="Indicator Mode",
    )
    .add_to_registry()
)
