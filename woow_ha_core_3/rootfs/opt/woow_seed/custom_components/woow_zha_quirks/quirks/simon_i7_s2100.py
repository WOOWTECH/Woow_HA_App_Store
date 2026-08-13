"""ZHA Quirk (v3) for Simon i7 Smart Switches (S2100 series).

Covers five variants:
  - S2100-1001  1-gang  (_TZ2000_sayvzx8wgxqoxfuj)
  - S2100-1002  2-gang  (_TZ2000_vvxwtxzf96vvarzj)
  - S2100-1003  3-gang  (_TZ2000_bi57zocaqionffns)
  - S2100-1004  4-gang  (_TZ2000_o1yvtxphiwt5cwif)
  - S2100-1004  4-gang  (_TZ2000_kgwm3i4o4klbuaks)  — Simon-home device "3-70E8304"

These are standard ZCL switches (genOnOff on multiple endpoints),
NOT Tuya MCU (TS0601) devices.  Each endpoint has:
  Cluster 0x0006 OnOff  — standard on/off
  Cluster 0xFC56         — Tuya manufacturer cluster (unused)

Replacing OnOff with TuyaZBOnOffAttributeCluster adds:
  backlight_mode  (0x8001)  indicator LED mode
    (enum: Off / Switch Status / Switch Position — raw 0x8001 values 0/1/2)

The redundant per-endpoint firmware/OTA update entities are suppressed on
every variant (no ZHA-distributable OTA image exists for these Tuya devices,
so the entities sit permanently "unknown").

Multi-gang models (2/3/4-gang) get a virtual endpoint 200 with an
AllOnOff cluster that sends OnOff commands to every real endpoint,
providing a single "All On/Off" switch entity.

Note: Endpoint 242 cannot be used for the virtual endpoint because
the device already has a real endpoint 242 (Green Power, profile 0xA1E0)
which ZHA skips for cluster handler creation.

The "3-70E8304" variant (_TZ2000_kgwm3i4o4klbuaks) gets a dedicated builder
that differs from the generic S2100-1004 block:
  - Indicator LED-mode labels match the Tuya/渥屋 app and this device's actual
    0x8001 raw values: 0 = "Close", 1 = "Switch Status", 2 = "Switch Position"
    (NOT the generic SwitchBackLight Off/Normal/Inverted ordering).
  - The native StartUpOnOff "power-on behavior" selects (0x4003) are suppressed
    on every gang — this device ignores the attribute and has no Tuya power-on
    datapoint, so those selects do nothing.
  - The firmware-update (OTA) entities are suppressed. The device replicates the
    OTA cluster (0x0019) on all four gang endpoints, so ZHA would otherwise create
    four redundant "韌體/firmware" update entities. There is no ZHA-distributable
    OTA image for this Tuya device, so latest_version is always null and every one
    sits permanently in the "unknown" state — pure noise.
"""

import enum
import logging

from zigpy.quirks.v2 import EntityType, QuirkBuilder
from zigpy.zcl import foundation
from zigpy.zcl.clusters.general import OnOff

from zhaquirks import LocalDataCluster
from zhaquirks.tuya import TuyaZBOnOffAttributeCluster

_LOGGER = logging.getLogger(__name__)

ONOFF = TuyaZBOnOffAttributeCluster.cluster_id  # 0x0006
ALL_ONOFF_EP = 200  # virtual endpoint for All On/Off


# Indicator/backlight LED mode for the "3-70E8304" (_TZ2000_kgwm3i4o4klbuaks),
# labelled to match the Tuya/渥屋 app and this device's actual 0x8001 raw values.
# ZHA renders select options as `name.replace("_", " ")` and maps a chosen label
# back with `replace(" ", "_")`, so member names use underscores for spaces.
class WoowIndicatorMode(enum.IntEnum):
    Close = 0            # LED never lit  (no indicator)
    Switch_Status = 1    # LED lit when the gang is ON   (status indicator)
    Switch_Position = 2  # LED lit when the gang is OFF  (locator / find-in-dark)


# Indicator/backlight LED mode for the Simon i7 S2100-1001..1004 gangs
# ("simon i7 1/2/3/4 gang"). Labels requested by the user, matching the
# device's actual 0x8001 raw values: 0 = "Off", 1 = "Switch Status",
# 2 = "Switch Position". ZHA renders select options as name.replace("_", " ")
# (and maps a chosen label back with replace(" ", "_")), so member names use
# underscores for the spaces.
class SimonI7IndicatorMode(enum.IntEnum):
    Off = 0              # LED never lit  (no indicator)
    Switch_Status = 1    # LED lit when the gang is ON   (status indicator)
    Switch_Position = 2  # LED lit when the gang is OFF  (locator / find-in-dark)


class AllOnOffCluster(LocalDataCluster, OnOff):
    """Virtual OnOff cluster that controls all real endpoints simultaneously.

    Placed on virtual endpoint 200, this cluster intercepts on/off commands
    and fans them out to every real endpoint's OnOff cluster.

    ZHA auto-discovers a standard Switch entity for this cluster. The Switch
    entity calls OnOffClusterHandler.turn_on() → cluster.on() → command(0x01),
    which we intercept here to fan out.
    """

    cluster_id = OnOff.cluster_id  # 0x0006

    async def command(
        self,
        command_id: foundation.GeneralCommand | int,
        *args,
        manufacturer=None,
        expect_reply: bool = True,
        **kwargs,
    ):
        """Intercept on/off/toggle and send to all real endpoints."""
        if command_id not in (0x00, 0x01, 0x02):
            return foundation.GENERAL_COMMANDS[
                foundation.GeneralCommand.Default_Response
            ].schema(command_id=command_id, status=foundation.Status.SUCCESS)

        for ep_id, ep in sorted(self.endpoint.device.endpoints.items()):
            if ep_id in (0, ALL_ONOFF_EP, 242):
                continue
            onoff = ep.in_clusters.get(OnOff.cluster_id)
            if onoff is None:
                continue
            try:
                await onoff.command(command_id)
                _LOGGER.debug(
                    "AllOnOff EP%d cmd=0x%02x OK", ep_id, command_id,
                )
            except Exception:
                _LOGGER.warning(
                    "AllOnOff EP%d cmd=0x%02x failed",
                    ep_id, command_id, exc_info=True,
                )

        if command_id == 0x01:
            self._update_attribute(OnOff.AttributeDefs.on_off.id, True)
        elif command_id == 0x00:
            self._update_attribute(OnOff.AttributeDefs.on_off.id, False)

        return foundation.GENERAL_COMMANDS[
            foundation.GeneralCommand.Default_Response
        ].schema(command_id=command_id, status=foundation.Status.SUCCESS)


# ────────────────────────────────────────────────────────────────
# S2100-1001  —  1-gang  (_TZ2000_sayvzx8wgxqoxfuj)
# (no All On/Off — only 1 gang)
# ────────────────────────────────────────────────────────────────
(
    QuirkBuilder("_TZ2000_sayvzx8wgxqoxfuj", "S2100-1001")
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=1)
    # ── Suppress the redundant per-endpoint firmware/OTA update entities ──
    .prevent_default_entity_creation(unique_id_suffix="firmware_update")
    .enum(
        TuyaZBOnOffAttributeCluster.AttributeDefs.backlight_mode.name,
        SimonI7IndicatorMode,
        ONOFF,
        endpoint_id=1,
        entity_type=EntityType.CONFIG,
        translation_key="backlight_mode",
        fallback_name="Indicator Mode",
    )
    .add_to_registry()
)


# ────────────────────────────────────────────────────────────────
# S2100-1002  —  2-gang  (_TZ2000_vvxwtxzf96vvarzj)
# ────────────────────────────────────────────────────────────────
(
    QuirkBuilder("_TZ2000_vvxwtxzf96vvarzj", "S2100-1002")
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=1)
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=2)
    # ── Suppress the redundant per-endpoint firmware/OTA update entities ──
    .prevent_default_entity_creation(unique_id_suffix="firmware_update")
    .enum(
        TuyaZBOnOffAttributeCluster.AttributeDefs.backlight_mode.name,
        SimonI7IndicatorMode,
        ONOFF,
        endpoint_id=1,
        entity_type=EntityType.CONFIG,
        translation_key="backlight_mode",
        fallback_name="Indicator Mode",
    )
    .adds_endpoint(endpoint_id=ALL_ONOFF_EP)
    .adds(AllOnOffCluster, endpoint_id=ALL_ONOFF_EP)
    .add_to_registry()
)


# ────────────────────────────────────────────────────────────────
# S2100-1003  —  3-gang  (_TZ2000_bi57zocaqionffns)
# ────────────────────────────────────────────────────────────────
(
    QuirkBuilder("_TZ2000_bi57zocaqionffns", "S2100-1003")
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=1)
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=2)
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=3)
    # ── Suppress the redundant per-endpoint firmware/OTA update entities ──
    .prevent_default_entity_creation(unique_id_suffix="firmware_update")
    .enum(
        TuyaZBOnOffAttributeCluster.AttributeDefs.backlight_mode.name,
        SimonI7IndicatorMode,
        ONOFF,
        endpoint_id=1,
        entity_type=EntityType.CONFIG,
        translation_key="backlight_mode",
        fallback_name="Indicator Mode",
    )
    .adds_endpoint(endpoint_id=ALL_ONOFF_EP)
    .adds(AllOnOffCluster, endpoint_id=ALL_ONOFF_EP)
    .add_to_registry()
)


# ────────────────────────────────────────────────────────────────
# S2100-1004  —  4-gang  (_TZ2000_o1yvtxphiwt5cwif)
# ────────────────────────────────────────────────────────────────
(
    QuirkBuilder("_TZ2000_o1yvtxphiwt5cwif", "S2100-1004")
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=1)
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=2)
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=3)
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=4)
    # ── Suppress the redundant per-endpoint firmware/OTA update entities ──
    .prevent_default_entity_creation(unique_id_suffix="firmware_update")
    .enum(
        TuyaZBOnOffAttributeCluster.AttributeDefs.backlight_mode.name,
        SimonI7IndicatorMode,
        ONOFF,
        endpoint_id=1,
        entity_type=EntityType.CONFIG,
        translation_key="backlight_mode",
        fallback_name="Indicator Mode",
    )
    .adds_endpoint(endpoint_id=ALL_ONOFF_EP)
    .adds(AllOnOffCluster, endpoint_id=ALL_ONOFF_EP)
    .add_to_registry()
)


# ────────────────────────────────────────────────────────────────
# S2100-1004  —  4-gang  (_TZ2000_kgwm3i4o4klbuaks)  —  "3-70E8304"
#
# Same hardware as the block above, but with the Tuya-app indicator
# labels (Close / Switch Status / Switch Position) and the dead native
# StartUpOnOff "power-on behavior" selects suppressed on every gang.
# ────────────────────────────────────────────────────────────────
(
    QuirkBuilder("_TZ2000_kgwm3i4o4klbuaks", "S2100-1004")
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=1)
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=2)
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=3)
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=4)
    # ── Suppress the native StartUpOnOff "power-on behavior" selects (EP1-4) ──
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
    # ── Suppress the redundant per-endpoint firmware/OTA update entities ──
    # The OTA cluster (0x0019) is replicated on EP1-4, so ZHA creates four
    # "firmware" update entities, all permanently "unknown" (no OTA image
    # available for this Tuya device). Matched by unique_id suffix across
    # every endpoint in one rule.
    .prevent_default_entity_creation(unique_id_suffix="firmware_update")
    # ── Indicator (backlight) LED mode select on EP1, Tuya-app labels ──
    .enum(
        TuyaZBOnOffAttributeCluster.AttributeDefs.backlight_mode.name,
        WoowIndicatorMode,
        ONOFF,
        endpoint_id=1,
        entity_type=EntityType.CONFIG,
        translation_key="backlight_mode",
        fallback_name="Indicator Mode",
    )
    .adds_endpoint(endpoint_id=ALL_ONOFF_EP)
    .adds(AllOnOffCluster, endpoint_id=ALL_ONOFF_EP)
    .add_to_registry()
)
