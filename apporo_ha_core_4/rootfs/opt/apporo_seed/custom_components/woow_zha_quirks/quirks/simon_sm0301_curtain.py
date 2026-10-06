"""ZHA Quirk for Simon SM0301 Curtain Controller.

Device: SM0301 / _TYZB01_koulgwmy, Silicon Labs EFR32MG24, IEEE
18:69:0a:ff:fe:25:8a:95.  Standard ZCL Shade device (device_type 0x0200) with
OnOff (0x0006) + LevelControl (0x0008) + Shade Configuration (0x0100).  Drives a
200 W AC curtain motor (L1/L2 forward/reverse).  Only EP1 is real (EP2-4 phantom).

ZHA builds a "Shade" cover: open/close -> OnOff on/off, set_position ->
LevelControl move_to_level.  Live testing (192.168.2.6, camera rig) found these
firmware behaviours, worked around here:

  1. OnOff does NOT drive the motor (open/close did nothing) -> redirect on/off to
     LevelControl full moves (CurtainOnOff).
  2. move_to_level withholds its ZCL response until the move ends, so ZHA timed
     out with "device did not respond" -> sent fire-and-forget (expect_reply=False)
     and the command is acked immediately to ZHA.
  3. move_to_level positioning is LINEAR and accurate: level 128 lands ~50 %, level
     64 ~25 %, etc. (an earlier "nonlinear, 50 %->25 %" reading was an artifact of a
     mis-aimed test camera).  The motor runs continuously to the target and the
     device self-stops there — so a single move_to_level is all that's needed; no
     timed drive / explicit Stop (the continuous-Move command makes this firmware
     pulse the relay rapidly, so it is avoided).
  4. The closed end-stop reports a small residual current_level (~2-3, not 0 → ZHA
     shows 1 %, never "closed"); the open end reports 254.  CurtainLevelControl
     snaps a near-end reported level to the exact end (END_DEADBAND) so a full
     close/open reaches the closed/open state.
  5. ZHA derives the cover open/closed STATE from the OnOff on_off attr (not position),
     and a physical close doesn't drive on_off off → state stuck "open" at position 0.
     The quirk syncs on_off to the level (off only at level 0) so the state follows the
     position — CurtainLevelControl pushes it, CurtainOnOff re-derives it.

Travel Time (Shade closed_limit) sets the full open<->close time; the motor runs at a
constant rate, so a partial move's time is proportional to the distance.  CurtainShade
presents closed_limit to HA as real seconds (closed_limit / 100) so Travel Time is the
actual travel time, and move_to_level uses transition_time=0 so HA moves at the same
speed as a physical switch press — both Home Assistant and the real switch take the
Travel Time, and step-based position reporting after a physical move is correct.

Other cleanups: remove phantom EP2-4; suppress StartUpOnOff /
start_up_current_level / the redundant OnOff "opening" binary_sensor / the firmware
(OTA) update entity.
"""

import asyncio
import logging

from zigpy.quirks import CustomCluster
from zigpy.quirks.v2 import EntityType, QuirkBuilder
from zigpy.quirks.v2.homeassistant.number import NumberDeviceClass
from zigpy.zcl import foundation
from zigpy.zcl.clusters.closures import Shade
from zigpy.zcl.clusters.general import LevelControl, OnOff

_LOGGER = logging.getLogger(__name__)

ONOFF = 0x0006
LEVEL = 0x0008
SHADE = 0x0100
CLOSED_LIMIT = 0x0010
CURRENT_LEVEL = 0x0000      # LevelControl current_level
ON_OFF_ATTR = 0x0000        # OnOff on_off (drives ZHA's Shade cover open/closed state)

# The device maps ZCL level 0-254 to motor steps 0-closed_limit, so closed_limit
# sets the full-travel *time* (not the level->position mapping, which stays
# proportional).  The motor runs at a fixed ~STEPS_PER_SECOND steps/s, so real
# full-travel seconds = closed_limit / STEPS_PER_SECOND (live-measured, native
# move_to_level at transition_time=0).  CurtainShade presents closed_limit to HA as
# those real seconds, so the "Travel Time" entity is the actual open<->close time and
# partial moves take a proportional fraction of it — matching both Home Assistant
# commands and physical switch presses.
#
# move_to_level is sent with transition_time=0 (see CurtainLevelControl) so HA drives
# the motor at the same full speed as a physical button.  A non-zero transition made
# HA ~15 % slower than the button, which previously forced a ~9 s TRAVEL_OFFSET_S to
# mask it (and left the real curtain / physical-move position wrong); both removed.
STEPS_PER_SECOND = 100
TRAVEL_OFFSET_S = 0.0
MIN_TRAVEL_SECONDS = 5
MAX_TRAVEL_SECONDS = 180

# Travel Time is backed by the device's closed_limit; ZHA shows it as "Unknown" until
# that attribute has a value, and this encoder-less firmware usually has no stored
# closed_limit after a fresh ZHA pair (its time-based calibration is lost on re-pair).
# Seed a sensible default on init so the entity is never Unknown, then read the device's
# real value (if any) to replace it.
DEFAULT_TRAVEL_SECONDS = 30   # mid-range default until the device/user provides one
_INIT_READ_DELAY_S = 2        # let the device settle after pairing before the init read

_MOVE_CMDS = {0x00, 0x04}   # move_to_level, move_to_level_with_on_off

# The device's physical end-stops report a small residual current_level — the closed
# end reports ~2-3 (-> ZHA round(level*100/255) = 1 %, never the 0 % "closed" state),
# the open end reports 254 (= 100 %).  Snap a reported level within this many ZCL
# levels of an end to the exact end so a full close/open reaches closed/open.
END_DEADBAND = 5


def _steps_from_seconds(secs: float) -> int:
    return max(1, round((float(secs) - TRAVEL_OFFSET_S) * STEPS_PER_SECOND))


def _seconds_from_steps(steps: float) -> int:
    return max(1, round(float(steps) / STEPS_PER_SECOND + TRAVEL_OFFSET_S))


class CurtainLevelControl(CustomCluster, LevelControl):
    """Native move_to_level positioning (see module docstring).

    The device positions accurately and self-stops at the target level, so each
    set_position is a single fire-and-forget move_to_level.  The move's ZCL
    response is withheld until the move ends, so it is sent fire-and-forget and the
    command is acked to ZHA immediately; the displayed position is updated
    optimistically to the target (positioning is accurate)."""

    def command(self, command_id, *args, manufacturer=None, expect_reply=True,
                tsn=None, **kwargs):
        cid = int(command_id)
        if cid in _MOVE_CMDS:
            level = max(0, min(254, int(args[0]) if args else 0))
            self._task = asyncio.ensure_future(self._dev_move(level))
            self.update_attribute(CURRENT_LEVEL, level)   # accurate; reflect at once
            return self._ok(cid)
        return super().command(command_id, *args, manufacturer=manufacturer,
                               expect_reply=expect_reply, tsn=tsn, **kwargs)

    async def _ok(self, cid):
        return [cid, foundation.Status.SUCCESS]

    def _update_attribute(self, attrid, value):
        # Snap the device's near-end residual current_level to the exact ends so a
        # full close reaches the 0 % "closed" state (the closed end-stop reports ~2-3,
        # not 0) and a full open reaches 100 %.
        if int(attrid) == CURRENT_LEVEL and value is not None:
            raw = int(value)
            if raw <= END_DEADBAND:
                value = 0
            elif raw >= 254 - END_DEADBAND:
                value = 254
            super()._update_attribute(attrid, value)        # update level cache first
            # ZHA's Shade cover derives open/closed STATE from the OnOff on_off attr,
            # not position.  The device drives on_off only for move_to_level_with_on_off
            # commands, NOT physical button presses, so a physical close leaves on_off
            # "on" and the state stuck "open".  Sync on_off to the level here so the
            # state follows the position (off only at level 0 = fully closed).
            onoff = self.endpoint.in_clusters.get(ONOFF)
            if onoff is not None:
                onoff.update_attribute(ON_OFF_ATTR, 0 if value == 0 else 1)
            return
        super()._update_attribute(attrid, value)

    async def _dev_move(self, level):
        # fire-and-forget: the move's ZCL response is withheld until the move ends.
        # transition_time=0 -> the motor runs at full (physical-button) speed; a
        # non-zero transition makes this firmware drive ~15 % slower.
        try:
            await super().command(0x04, level, 0, expect_reply=False)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("SM0301 motor move failed: %s", exc)


class CurtainOnOff(CustomCluster, OnOff):
    """Redirect OnOff on/off to LevelControl full moves (this device's OnOff does
    not drive the motor; only LevelControl does)."""

    def command(self, command_id, *args, manufacturer=None, expect_reply=True,
                tsn=None, **kwargs):
        cid = int(command_id)
        if cid in (0x00, 0x01):  # off / on
            return self._drive(254 if cid == 0x01 else 0)
        return super().command(command_id, *args, manufacturer=manufacturer,
                               expect_reply=expect_reply, tsn=tsn, **kwargs)

    def _update_attribute(self, attrid, value):
        # The device's on_off doesn't track open/closed (it stays "on" after a
        # physical close), so derive it from the LevelControl position — on_off off
        # only at level 0 — so ZHA's cover state can't get stuck "open" at position 0.
        if int(attrid) == ON_OFF_ATTR:
            lvl = self.endpoint.in_clusters.get(LEVEL)
            cur = lvl.get(CURRENT_LEVEL) if lvl is not None else None
            if cur is not None:
                value = 0 if int(cur) == 0 else 1
        super()._update_attribute(attrid, value)

    async def _drive(self, level):
        try:
            lvl = self.endpoint.in_clusters[LEVEL]
            lvl.update_attribute(CURRENT_LEVEL, level)   # accurate; reflect at once
            await lvl._dev_move(level)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("SM0301 onoff->level redirect failed: %s", exc)
        return [0x01, foundation.Status.SUCCESS]


class CurtainShade(CustomCluster, Shade):
    """Present closed_limit (motor steps) to HA as real travel SECONDS so the
    Travel Time entity is the actual full open<->close time (see constants)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Seed a default so Travel Time is never "Unknown" on a fresh pair (the device
        # often has no stored closed_limit after re-pairing), then read the device's
        # real value to replace it.  A later read or a user write overwrites the default;
        # the `is None` guard keeps any value already restored from the zigpy DB.
        if self.get(CLOSED_LIMIT) is None:
            self._update_attribute(
                CLOSED_LIMIT, _steps_from_seconds(DEFAULT_TRAVEL_SECONDS)
            )
        try:
            self._init_read = asyncio.ensure_future(self._read_closed_limit())
        except Exception as exc:  # noqa: BLE001 — no running loop in some contexts
            _LOGGER.debug("SM0301 closed_limit init read not scheduled: %s", exc)

    async def _read_closed_limit(self):
        # .skip_configuration() means ZHA never binds/configures this cluster, so drive
        # the read here rather than from bind().  Best-effort: on failure / unsupported
        # the seeded default stays.
        try:
            await asyncio.sleep(_INIT_READ_DELAY_S)
            await self.read_attributes([CLOSED_LIMIT])
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("SM0301 closed_limit init read failed: %s", exc)

    def _update_attribute(self, attrid, value):
        if int(attrid) == CLOSED_LIMIT and value is not None:
            secs = _seconds_from_steps(value)
            # Ignore an unset / "wiped" device value (e.g. closed_limit 65534 ≈ 655 s):
            # outside the entity's 5-180 s range → keep the seeded/last good default.
            if not (MIN_TRAVEL_SECONDS <= secs <= MAX_TRAVEL_SECONDS):
                return
            value = secs
        super()._update_attribute(attrid, value)

    async def write_attributes(self, attributes, manufacturer=None, **kwargs):
        written_steps = None
        if attributes:
            attributes = dict(attributes)
            for key in (CLOSED_LIMIT, "closed_limit"):
                if key in attributes and attributes[key] is not None:
                    written_steps = _steps_from_seconds(attributes[key])
                    attributes[key] = written_steps
        result = await super().write_attributes(
            attributes, manufacturer=manufacturer, **kwargs)
        # zigpy caches the raw written steps on success; re-cache as seconds so the
        # Travel Time entity displays the real travel time (not motor steps).
        if written_steps is not None:
            self._update_attribute(CLOSED_LIMIT, written_steps)
        return result


# ────────────────────────────────────────────────────────────────
# SM0301 — 1-channel curtain controller (_TYZB01_koulgwmy)
# ────────────────────────────────────────────────────────────────
(
    QuirkBuilder("_TYZB01_koulgwmy", "SM0301")
    .replaces(CurtainOnOff, endpoint_id=1)
    .replaces(CurtainLevelControl, endpoint_id=1)
    .replaces(CurtainShade, endpoint_id=1)
    .removes_endpoint(2)
    .removes_endpoint(3)
    .removes_endpoint(4)
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=ONOFF, unique_id_suffix="StartUpOnOff",
    )
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=LEVEL, unique_id_suffix="start_up_current_level",
    )
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=ONOFF, unique_id_suffix="-1-6",
    )
    # Suppress the redundant firmware/OTA update entity (no ep/cluster → matches all
    # endpoints by uid suffix <ieee>-<ep>-25-firmware_update; here EP1 only).
    .prevent_default_entity_creation(unique_id_suffix="firmware_update")
    .number(
        attribute_name="closed_limit",
        cluster_id=SHADE,
        endpoint_id=1,
        min_value=MIN_TRAVEL_SECONDS,
        max_value=MAX_TRAVEL_SECONDS,
        step=1,
        unit="s",                      # CurtainShade presents closed_limit in seconds
        device_class=NumberDeviceClass.DURATION,
        entity_type=EntityType.CONFIG,
        translation_key="travel_time",
        fallback_name="Travel Time",
    )
    .skip_configuration()
    .add_to_registry()
)
