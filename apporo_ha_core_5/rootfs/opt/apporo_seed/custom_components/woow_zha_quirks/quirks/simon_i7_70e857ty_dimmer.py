"""ZHA Quirk (v3) for the Simon i7 0-10V Smart Dimming Remote Switch.

渥屋 catalog: "17-70E857TY"
Manufacturer: _TZ3000_qe3d5gga
Model:        TS1002
IEEE (test rig): e0:79:8d:ff:fe:b2:d0:42

What the device is
------------------
Per the product manual (Simon i7 "Smart Dimming Remote Switch, ZigBee to 0-10V
set"), this is a *wall controller* that pairs with a separate Simon 0-10V
converter module ("N65E0-0017 wireless converter 0-10V with on-off relay" +
"N6524-0412 ZigBee control module") which performs the actual 0-10V dimming.
The wall unit sends on/off + slide-to-dim signals and carries an indicator /
status LED.  The paired unit here has two gangs (endpoints 1 and 2).

Real signature (mains powered, ZigBee Router)
---------------------------------------------
  Endpoint 1 & 2 (identical):
    profile 0x0104, device_type 0x0104 (DIMMER_SWITCH)
    input  (server): 0x0000 Basic, 0x0003 Identify, 0x0004 Groups,
                     0x0006 OnOff, 0x0008 LevelControl, 0xE002 (Tuya mfg)
    output (client): 0x0003, 0x0006, 0x0008, 0x0019 OTA, 0x0300 Color
  Endpoint 242: Green Power proxy (ZHA skips it)

Stock ZHA behaviour vs. what we want
------------------------------------
Stock ZHA exposes the device as a generic 2-endpoint device: 2 OnOff switches
plus an Identify button and two per-endpoint firmware/OTA "update" entities,
with NO control for the indicator / status LED.

This quirk (modelled on the sibling ``simon_i7_s2100.py``) replaces the stock
OnOff with ``TuyaZBOnOffAttributeCluster`` on each gang.  That:
  * carries the gang ``on_off`` state (exposed as a read-only binary_sensor, see
    the control note below), and
  * surfaces the Tuya indicator-LED attribute ``backlight_mode`` (0x8001),
    which we expose as a single device-global "Status Light" select on EP1.

It trims the device to the desired set (2 binary_sensors + 1 select):
  * suppress the control-less default Switch on each gang (replaced by a
    binary_sensor — see the control note),
  * suppress the native StartUpOnOff "power-on behaviour" select on both gangs
    (this device has no Tuya power-on datapoint; the attribute does nothing),
  * suppress the Identify button, and
  * collapse the duplicate per-endpoint firmware/OTA "update" entities.

Status-light values are operator-verified live (see ``WoowStatusLight``).

Control note (operator-verified)
--------------------------------
This is a *remote* — its server OnOff cluster rejects ``on``/``off`` with
``UNSUP_CLUSTER_COMMAND`` (the real 0-10V load is driven by the separate Simon
converter module, not present in ZHA), so a ``switch`` entity could never
control it.  Each gang only *reports* its ``on_off`` state when physically
tapped, so we model the two gangs as read-only **binary_sensor** entities
(Gang 1 / Gang 2) that mirror the physical state.
"""

import enum
import logging

from zigpy.quirks.v2 import EntityType, QuirkBuilder
from zigpy.zcl.clusters.general import Identify, OnOff, Ota

from zhaquirks.tuya import TuyaZBOnOffAttributeCluster

_LOGGER = logging.getLogger(__name__)

ONOFF = TuyaZBOnOffAttributeCluster.cluster_id  # 0x0006
IDENTIFY = Identify.cluster_id  # 0x0003
OTA = Ota.cluster_id  # 0x0019

_ENDPOINTS = (1, 2)  # the two gangs


# Status-light (indicator LED) mode — backlight_mode attr 0x8001 on OnOff.
# Raw values + behaviour confirmed live on this device (operator-verified):
#   0 = LED always off
#   1 = LED lit when the gang is ON   (status indicator)
#   2 = LED lit when the gang is OFF  (locator / find-in-dark)
# Labels match the 渥屋/Tuya app and the sibling "3-70E8304" device
# (see WoowIndicatorMode in simon_i7_s2100.py). ZHA renders select options as
# `name.replace("_", " ")`, so member names use underscores for spaces.
class WoowStatusLight(enum.IntEnum):
    Close = 0            # LED never lit (indicator disabled)
    Switch_Status = 1    # LED lit when gang is ON
    Switch_Position = 2  # LED lit when gang is OFF (locator)


def _is_button(e) -> bool:
    """True for ZHA button entities (used to drop the Identify button)."""
    return getattr(e, "PLATFORM", "") == "button"


def _is_switch(e) -> bool:
    """True for ZHA switch entities (used to drop the control-less default switch)."""
    return getattr(e, "PLATFORM", "") == "switch"


_builder = QuirkBuilder("_TZ3000_qe3d5gga", "TS1002")

# ── EP1/EP2: OnOff → Tuya OnOff superset (carries on_off + backlight_mode 0x8001).
#    The device rejects on/off (it's a remote), so the default Switch can't control
#    anything — suppress it and expose the gang state as a read-only binary_sensor.
#    Also suppress the dead StartUpOnOff "power-on behaviour" select. ──
for _ep in _ENDPOINTS:
    _builder = (
        _builder.replaces(TuyaZBOnOffAttributeCluster, endpoint_id=_ep)
        .prevent_default_entity_creation(
            endpoint_id=_ep, cluster_id=ONOFF, function=_is_switch
        )
        .prevent_default_entity_creation(
            endpoint_id=_ep, cluster_id=ONOFF, unique_id_suffix="StartUpOnOff"
        )
        .binary_sensor(
            OnOff.AttributeDefs.on_off.name,  # "on_off" (0x0000)
            ONOFF,
            endpoint_id=_ep,
            entity_type=EntityType.STANDARD,
            translation_key=f"gang_{_ep}",
            fallback_name=f"Gang {_ep}",
        )
    )

# ── Drop the Identify button (both EPs each carry an Identify cluster) ──
for _ep in _ENDPOINTS:
    _builder = _builder.prevent_default_entity_creation(
        endpoint_id=_ep, cluster_id=IDENTIFY, function=_is_button
    )

# ── Collapse the duplicate firmware/OTA "update" entities (both EPs) ──
for _ep in _ENDPOINTS:
    _builder = _builder.prevent_default_entity_creation(
        endpoint_id=_ep, cluster_id=OTA, unique_id_suffix="firmware_update"
    )

# ── EP1: single device-global Status-Light (indicator LED) mode select (0x8001) ──
# 0x8001 is mirrored across both gangs; the select is hosted on EP1.
(
    _builder.enum(
        TuyaZBOnOffAttributeCluster.AttributeDefs.backlight_mode.name,
        WoowStatusLight,
        ONOFF,
        endpoint_id=1,
        entity_type=EntityType.CONFIG,
        translation_key="status_light",
        fallback_name="Status Light",
    ).add_to_registry()
)
