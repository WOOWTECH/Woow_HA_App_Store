"""ZHA quirk for Simon 4-58E8017 rotary CCT knob (Tuya TS0034 / _TZ3000_ocqo8iwd).

This is a Tuya rotary knob **controller** (no DPs). It always sits in command
mode and transmits standard Zigbee commands to whatever it is bound to. How it
*actually* behaves was established by sniffing the Simon/渥屋 (Tuya) gateway
traffic on channel 20 (2026-06-29, see ``docs/4-58E8017-sniff-findings.md``):
the knob (ep1) multicasts to a group, and every gesture is a clean command —

  * **Short-press** → standard ZCL OnOff ``on`` (0x01) / ``off`` (0x00).  (stateful)
  * **Rotate (brightness mode)** → standard ZCL LevelControl ``step`` (0x02);
    ``step_mode`` 0x00 = up / 0x01 = down, ``step_size`` ∝ rotation speed.
  * **Long-press** → *local* toggle to colour-temp mode (no Zigbee frame).
  * **Rotate (colour mode)** → **Tuya manufacturer command 0xE0 on the Color
    cluster**, payload ``uint16 LE`` = ``temp_value`` (0..1000) — the same custom
    command the SP9-200-10 CCT light obeys (``ts0502b_cct_TZ3000_yeygk4hw.py``).

This **overturns** the earlier "no events / Not Supported" verdict, which came
from never sniffing the device and from the wrong assumption that it needed a
Tuya event-mode (``switch_mode``) write (that write returned ``None`` because the
knob does not use event mode — it already emits the commands above).

What the quirk does:
  1. Replaces the EP1 **Color output (client)** cluster (``KnobColorCluster``) so
     ZHA decodes the colour-rotate Tuya ``0xE0`` into a clean ``zha_event``
     (``command: tuya_set_color_temp``, ``args: [temp_value]``) AND mirrors the
     value into a read-only attribute.  Replaces the EP1 **Level output (client)**
     cluster (``KnobLevelCluster``) to accumulate relative ``step`` into a synthetic
     0..254 brightness.  OnOff is left standard (ZHA tracks ``on_off`` natively).
  2. Exposes 3 read-only **entities** reflecting the knob's actions (it is an input
     device — these mirror state/last value, they cannot control the knob):
     ``binary_sensor`` On/Off, ``sensor`` Colour Temperature (0..100 %, from the
     absolute ``0xE0`` value; 0 % = warm), ``sensor`` Brightness (0..100 %, approx;
     accumulated from relative steps — may drift).  These update only while
     group-bound (below) and coexist with the ``zha_event`` triggers.  The On/Off
     binary_sensor is a *synthesized* state: it tracks the physical press AND flips
     ON when the user rotates (brightness or colour changes) and OFF when brightness
     reaches 0 — matching the habit that rotating the knob drives the bound light.
  3. Drops the useless stock entities (Identify ``button``, firmware ``update``).
  4. Names the gestures as device-automation triggers for the HA UI.

After installing, the knob must be **re-paired to ZHA**.  IMPORTANT (verified
2026-06-29): ZHA's standard *bind-to-coordinator* (a unicast bind) is **ignored**
by this Tuya firmware — the knob only emits control commands to a multicast
**group**.  So the working setup is a **group bind** (mirroring how the Tuya
gateway provisioned it):

  1. Create a ZHA group whose id = the knob's group ``0x2760`` and add the
     **coordinator** as a member (so its radio receives the multicast).
  2. ZDO group-bind ep1 OnOff(0x0006)/LevelControl(0x0008)/ColorControl(0x0300)
     -> that group  (WS ``zha/groups/bind``).
  3. Restart HA once so the radio's multicast table is programmed.

Then every gesture fires a ``zha_event`` (press -> cluster 6 on/off; rotate ->
cluster 8 ``step``; colour rotate -> cluster 768 ``tuya_set_color_temp``), which
an automation maps onto any HA ``light``.  Full procedure + examples:
``docs/4-58E8017-sniff-findings.md``.  Device: IEEE 7c:c6:b6:ff:fe:d8:a3:7c.
"""

import logging
from typing import Final

import zigpy.types as t
from zigpy.quirks import CustomCluster
from zigpy.quirks.v2 import EntityType, QuirkBuilder
from zigpy.zcl import ClusterType
from zigpy.zcl.clusters.general import Identify, LevelControl, OnOff, Ota
from zigpy.zcl.clusters.lighting import Color
from zigpy.zcl.foundation import ZCLAttributeDef, ZCLCommandDef

from zhaquirks.const import (
    CLUSTER_ID,
    COMMAND,
    ENDPOINT_ID,
    LEFT,
    PARAMS,
    RIGHT,
    ROTATED,
    SHORT_PRESS,
)

_LOGGER = logging.getLogger(__name__)

ONOFF = OnOff.cluster_id  # 0x0006
LEVEL = LevelControl.cluster_id  # 0x0008
COLOR = Color.cluster_id  # 0x0300
IDENTIFY = Identify.cluster_id  # 0x0003
OTA = Ota.cluster_id  # 0x0019

# Tuya manufacturer command on the Color cluster (cluster-specific, NO mfg code).
# Captured live: cmd 0xE0, payload uint16 LE temp_value 0..1000 (e803=1000, 0000=0).
TUYA_SET_COLOR_TEMP = 0xE0
LEVEL_STEP = 0x02            # LevelControl.step
LEVEL_STEP_ON_OFF = 0x06     # LevelControl.step_with_on_off

# Synthetic attribute ids (manufacturer-specific) the quirk maintains so the knob's
# stateless actions can back read-only entities.
KNOB_COLOR_TEMP_ATTR = 0xF000   # on Color cluster: last temp_value (0..1000)
KNOB_LEVEL_ATTR = 0xF000        # on Level cluster: accumulated 0..254 brightness

# Initial values seeded at cluster __init__ so the %-sensors show a neutral 50 % on a
# FIRST pair instead of "Unknown" (they are command-driven and otherwise have no value
# until the first rotate). Both map to ~50 % via the converters below.
KNOB_COLOR_TEMP_DEFAULT = 500   # _temp_value_to_pct(500) = 50 %
KNOB_LEVEL_DEFAULT = 127        # _level_to_pct(127) ≈ 50 % (matches the step fallback)

ON_OFF_ATTR = OnOff.AttributeDefs.on_off.id   # 0x0000 (on the OnOff client cluster)
LEVEL_FULL_SCALE = 254          # ZCL current_level full scale for the % conversion

# "spell": reading these Basic attributes unlocks Tuya manufacturer behaviour.
_SPELL_ATTRS = [4, 0, 1, 5, 7, 0xFFFE]


def _temp_value_to_pct(value):
    """Tuya temp_value 0..1000 (0 = warm) → 0..100 %. None-safe for the UI."""
    try:
        v = max(0, min(1000, int(value)))
    except (TypeError, ValueError):
        return None
    return round(v / 10)


def _level_to_pct(value):
    """Accumulated level 0..254 → 0..100 %. None-safe for the UI."""
    try:
        v = max(0, min(LEVEL_FULL_SCALE, int(value)))
    except (TypeError, ValueError):
        return None
    return round(v / LEVEL_FULL_SCALE * 100)


def _is_button(e) -> bool:
    """True for ZHA button entities (used to drop the Identify button)."""
    return getattr(e, "PLATFORM", "") == "button"


def _reflect_onoff(endpoint, on: bool) -> None:
    """Drive the OnOff *client* cluster's ``on_off`` (what the On/Off binary_sensor
    reads) to an **absolute** value, so rotation activity reflects the bound light's
    on/off state (rotate-to-0 → off; rotate-up / colour → on).

    OnOff is an *output* (client) cluster on this device → ``endpoint.out_clusters``.
    Goes through ``KnobOnOffCluster.set_state`` so the press-toggle logic is bypassed
    (these are absolute reflections, not presses).
    """
    try:
        onoff = endpoint.out_clusters.get(ONOFF)
        if onoff is None:
            return
        if hasattr(onoff, "set_state"):
            onoff.set_state(on)
        else:  # fallback if the custom cluster isn't applied for some reason
            onoff._update_attribute(ON_OFF_ATTR, t.Bool(bool(on)))
    except Exception as exc:  # noqa: BLE001
        _LOGGER.debug("4-58E8017 on_off reflect failed: %s", exc)


class KnobOnOffCluster(CustomCluster, OnOff):
    """OnOff OUTPUT (client) cluster that makes each physical short-press **toggle** the
    synthesized ``on_off`` (what the binary_sensor reads), instead of following the
    knob's stateful on/off payload.

    Why: the knob is a *stateful* controller — a press sends standard ZCL ``On``/``Off``
    based on its own internal state, alternating on→off→on…  When a brightness rotate
    drives the level to 0, ``KnobLevelCluster`` forces ``on_off`` off, but the knob still
    thinks it is "on", so its next press sends ``off`` — which payload-mapping would render
    as a no-op (the user must press twice).  Toggling on each *distinct* press makes a
    single press always flip the displayed state, so press-after-dim-to-0 turns it back on.

    ZHA's ``OnOffClientClusterHandler.cluster_command`` maps the received on/off command to
    ``on_off`` via ``cluster.update_attribute()`` → ``_update_attribute()`` (and runs *after*
    ``handle_cluster_request``, so it would clobber a value set there).  We therefore
    intercept ``_update_attribute``: a press (on/off payload) toggles the cached state;
    rotate-driven absolute writes (via ``set_state``) pass through unchanged.  Edge
    detection on the payload makes it robust to the knob's command bursts — it repeats each
    press several times, and distinct presses strictly alternate on/off, so each real press
    flips exactly once and repeats are ignored.  ``super().handle_cluster_request`` /
    ZHA's event path are untouched, so the ``cluster_id 6 command on/off`` ``zha_event``
    still fires for automations.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_press_payload: bool | None = None
        self._absolute = False

    def set_state(self, on: bool) -> None:
        """Set ``on_off`` to an absolute value (rotate reflections), bypassing toggle."""
        self._absolute = True
        try:
            self._update_attribute(ON_OFF_ATTR, t.Bool(bool(on)))
        finally:
            self._absolute = False

    def _update_attribute(self, attrid, value):
        # Only press-driven on_off writes get the toggle treatment; absolute reflections
        # and every other attribute pass straight through.
        if attrid != ON_OFF_ATTR or self._absolute:
            return super()._update_attribute(attrid, value)

        payload = bool(value)
        # Ignore burst repeats of the same press (knob repeats each command several times).
        if payload == self._last_press_payload:
            return
        self._last_press_payload = payload
        # New distinct press → toggle the currently displayed state.
        new = not bool(self.get(ON_OFF_ATTR))
        return super()._update_attribute(ON_OFF_ATTR, t.Bool(new))


class KnobColorCluster(CustomCluster, Color):
    """Color OUTPUT (client) cluster declaring the knob's Tuya 0xE0 colour command.

    Declaring the command's schema lets ZHA decode the colour-mode rotation into a
    clean ``zha_event`` with a named ``temp_value`` arg, rather than choking on an
    unknown command id.  The knob is the *client* here, so the command it emits is a
    client→server command and belongs in ``ServerCommandDefs`` (same as the SP9
    light's quirk).
    """

    class ServerCommandDefs(Color.ServerCommandDefs):
        """Add the Tuya colour-temp command (0xE0)."""

        tuya_set_color_temp: Final = ZCLCommandDef(
            id=TUYA_SET_COLOR_TEMP,
            schema={"temp_value": t.uint16_t},
        )

    class AttributeDefs(Color.AttributeDefs):
        """Synthetic attribute holding the knob's last colour-temp value (0..1000)."""

        knob_color_temp: Final = ZCLAttributeDef(
            id=KNOB_COLOR_TEMP_ATTR,
            type=t.uint16_t,
            access="rp",
            is_manufacturer_specific=True,
        )

    def __init__(self, *args, **kwargs):
        """Seed a neutral colour-temp so the sensor shows 50 % (not "Unknown") on a
        first pair. Guarded so a value restored from the ZHA DB on a normal restart is
        kept (the cache is only empty on a genuine fresh pair)."""
        super().__init__(*args, **kwargs)
        if self.get(KNOB_COLOR_TEMP_ATTR) is None:
            self._update_attribute(KNOB_COLOR_TEMP_ATTR, KNOB_COLOR_TEMP_DEFAULT)

    def handle_cluster_request(self, hdr, args, *, dst_addressing=None):
        """Mirror the received Tuya 0xE0 colour value into a read-only attribute.

        Still calls super() so the existing ``zha_event`` is unaffected.
        """
        if hdr.command_id == TUYA_SET_COLOR_TEMP and args:
            try:
                self._update_attribute(KNOB_COLOR_TEMP_ATTR, int(args[0]))
                # Colour change implies the bound light is on → reflect it.
                _reflect_onoff(self.endpoint, True)
            except Exception as exc:  # noqa: BLE001
                _LOGGER.debug("4-58E8017 colour-temp attr update failed: %s", exc)
        return super().handle_cluster_request(hdr, args, dst_addressing=dst_addressing)

    async def bind(self):
        """On bind, cast the Tuya 'spell' (best-effort) so the knob stays awake.

        We intentionally do NOT write ``switch_mode`` — the knob is not an
        event-mode device; it already emits standard OnOff/Level + Tuya 0xE0.
        """
        result = await super().bind()
        try:
            basic = self.endpoint.in_clusters.get(0x0000)
            if basic is not None:
                await basic.read_attributes(_SPELL_ATTRS)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("4-58E8017 Tuya spell read failed: %s", exc)
        return result


class KnobLevelCluster(CustomCluster, LevelControl):
    """LevelControl OUTPUT (client) cluster that accumulates the knob's relative
    ``step`` commands into a synthetic 0..254 brightness, so a sensor can show an
    APPROXIMATE level.

    The knob only sends relative steps (up/down) — there is no absolute level — so
    this accumulator is best-effort and may drift from any real light.  super() is
    still called so the standard ``step`` ``zha_event`` is unaffected.
    """

    class AttributeDefs(LevelControl.AttributeDefs):
        """Synthetic attribute holding the accumulated 0..254 brightness."""

        knob_level: Final = ZCLAttributeDef(
            id=KNOB_LEVEL_ATTR,
            type=t.uint8_t,
            access="rp",
            is_manufacturer_specific=True,
        )

    def __init__(self, *args, **kwargs):
        """Seed a neutral 50 % brightness so the sensor isn't "Unknown" on a first pair.
        Guarded so a value restored from the ZHA DB on a normal restart is kept."""
        super().__init__(*args, **kwargs)
        if self.get(KNOB_LEVEL_ATTR) is None:
            self._update_attribute(KNOB_LEVEL_ATTR, KNOB_LEVEL_DEFAULT)

    def handle_cluster_request(self, hdr, args, *, dst_addressing=None):
        """Accumulate step(up/down) into the synthetic level attribute."""
        if hdr.command_id in (LEVEL_STEP, LEVEL_STEP_ON_OFF) and len(args) >= 2:
            try:
                cur = self.get(KNOB_LEVEL_ATTR)
                if cur is None:
                    cur = 127
                step_mode, step_size = int(args[0]), int(args[1])
                new = max(0, min(254, cur + (step_size if step_mode == 0 else -step_size)))
                self._update_attribute(KNOB_LEVEL_ATTR, new)
                # Brightness change → on; brightness reaching 0 → off.
                _reflect_onoff(self.endpoint, new > 0)
            except Exception as exc:  # noqa: BLE001
                _LOGGER.debug("4-58E8017 brightness accumulate failed: %s", exc)
        return super().handle_cluster_request(hdr, args, dst_addressing=dst_addressing)


(
    QuirkBuilder("_TZ3000_ocqo8iwd", "TS0034")
    # Replace the EP1 OnOff *output* (client) cluster so a short-press TOGGLES the On/Off
    # binary_sensor (the stateful knob would otherwise need two presses after dim-to-0).
    .replaces(
        KnobOnOffCluster,
        cluster_id=ONOFF,
        cluster_type=ClusterType.Client,
        endpoint_id=1,
    )
    # Replace the EP1 Color *output* (client) cluster: decode the Tuya 0xE0 colour
    # command into a clean zha_event AND mirror its value to a read-only attribute.
    .replaces(
        KnobColorCluster,
        cluster_id=COLOR,
        cluster_type=ClusterType.Client,
        endpoint_id=1,
    )
    # Replace the EP1 Level *output* (client) cluster to accumulate step → brightness.
    .replaces(
        KnobLevelCluster,
        cluster_id=LEVEL,
        cluster_type=ClusterType.Client,
        endpoint_id=1,
    )
    # ── Read-only entities reflecting the knob's actions (it is an input device,
    #    so these mirror state/last-value; they cannot control the knob). ──
    .binary_sensor(
        OnOff.AttributeDefs.on_off.name,  # "on_off" on the OnOff client cluster
        ONOFF,
        cluster_type=ClusterType.Client,
        endpoint_id=1,
        entity_type=EntityType.STANDARD,
        translation_key="knob_state",
        fallback_name="On/Off",
    )
    .sensor(
        KnobColorCluster.AttributeDefs.knob_color_temp.name,
        COLOR,
        cluster_type=ClusterType.Client,
        endpoint_id=1,
        entity_type=EntityType.STANDARD,
        unit="%",
        suggested_display_precision=0,
        attribute_converter=_temp_value_to_pct,  # temp_value 0..1000 → 0..100 % (0 = warm)
        translation_key="knob_color_temp",
        fallback_name="Colour Temperature",
    )
    .sensor(
        KnobLevelCluster.AttributeDefs.knob_level.name,
        LEVEL,
        cluster_type=ClusterType.Client,
        endpoint_id=1,
        entity_type=EntityType.STANDARD,
        unit="%",
        suggested_display_precision=0,
        attribute_converter=_level_to_pct,  # accumulated 0..254 → 0..100 %
        translation_key="knob_brightness",
        fallback_name="Brightness",
    )
    # ── Drop the useless stock entities: Identify button + firmware/OTA update ──
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=IDENTIFY, function=_is_button
    )
    .prevent_default_entity_creation(unique_id_suffix="firmware_update")
    # Named triggers for the automation UI, matching the real captured commands.
    .device_automation_triggers(
        {
            (SHORT_PRESS, "on"): {
                COMMAND: "on", CLUSTER_ID: ONOFF, ENDPOINT_ID: 1,
            },
            (SHORT_PRESS, "off"): {
                COMMAND: "off", CLUSTER_ID: ONOFF, ENDPOINT_ID: 1,
            },
            (ROTATED, RIGHT): {  # rotate brighten — Level step up
                COMMAND: "step", CLUSTER_ID: LEVEL, ENDPOINT_ID: 1,
                PARAMS: {"step_mode": 0},
            },
            (ROTATED, LEFT): {  # rotate dim — Level step down
                COMMAND: "step", CLUSTER_ID: LEVEL, ENDPOINT_ID: 1,
                PARAMS: {"step_mode": 1},
            },
            (ROTATED, "color"): {  # colour-mode rotate — Tuya 0xE0
                COMMAND: "tuya_set_color_temp", CLUSTER_ID: COLOR, ENDPOINT_ID: 1,
            },
        }
    )
    .add_to_registry()
)
