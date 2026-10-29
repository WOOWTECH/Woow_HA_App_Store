"""ZHA Quirk for Simon 241E8016TY 2-Gang Smart Dimmer (TS0052 / _TZ3002_cqpubrcz).

Device info:
  - Model:            TS0052
  - Manufacturer:     _TZ3002_cqpubrcz
  - WOOW/Tuya name:   241E8016TY — 2-channel dimmer
  - Bench units:      8c:8b:48:ff:fe:d9:c6:d6 (app_version 129)
                      7c:c6:b6:ff:fe:82:e3:7f (app_version 132)

ZHA signature (paired to the ZHA coordinator, EFR32/EZSP):
  EP1 profile 0x0104 device_type 0x0101 (DIMMABLE_LIGHT)
    in : 0x0000 Basic, 0x0003 Identify, 0x0004 Groups, 0x0005 Scenes,
         0x0006 OnOff, 0x0008 LevelControl
    out: 0x0019 OTA
  EP2 profile 0x0104 device_type 0x0101 (DIMMABLE_LIGHT)
    in : 0x0000, 0x0003, 0x0004, 0x0005, 0x0006, 0x0008
    out: 0x0019 OTA

This is a plain standard-ZCL 2-gang dimmer (NOT a Tuya MCU / 0xEF00 / TS0601
device): both endpoints are real physical gangs and both honour standard
move_to_level* commands, so it already worked as two `light` entities before
this quirk.

THIS SKU SHIPS IN TWO FIRMWARE REVISIONS THAT BEHAVE DIFFERENTLY
================================================================
Measured on two samples, 2026-08-18 (full evidence:
`sniffer-related/TS0052-FINDINGS.md`, "V1 vs V2 differential"; decision record:
`docs/adr/0003-firmware-divergence-within-one-quirk-registration.md`):

  Basic app_version 0x0001 | 129                    | 132
  -------------------------|-----------------------|--------------------------
  MinLevel/MaxLevel write  | READ_ONLY 0x88 (27/27 | SUCCESS (16/16), and the
                           | rejected, INCLUDING   | firmware enforces the
                           | writes from the Tuya  | window on HA commands AND
                           | gateway itself)       | on the physical wall button
  backlight_mode 0x8001    | accepts enum8 (0x30)  | rejects enum8 with
                           |                       | INVALID_DATA_TYPE 0x8D;
                           |                       | wants uint8 (0x20)

Everything else is identical between the two — manufacturer_name,
model_identifier, zcl/stack/hw version, date_code (2019.3.20) and sw_build_id
(empty) all match, so `QuirkBuilder` cannot tell them apart.

**This quirk is built to the app_version 132 standard**, in one registration.
The consequences on app_version 129 are deliberate and visible, not silent:

  - Min/Max Brightness writes fail with a real error in the UI. ZHA's number
    entity writes through `write_attributes_safe`, which raises on any
    non-SUCCESS status, so a fw-129 user sees
    "Failed to write attribute min_level=…: Status.READ_ONLY" rather than a
    control that quietly does nothing. (Only the
    `zha.set_zigbee_cluster_attribute` SERVICE path swallows the status —
    entities do not.)
  - Indicator Mode is written as uint8. Whether fw 129 accepts uint8 is
    recorded in TS0052-FINDINGS.md; targeting 132 was an explicit decision.

Registration-time firmware branching was considered and rejected:
`QuirkBuilder.firmware_version_filter()` reads the OTA cluster's
`current_file_version`, which ZHA only learns when the device itself sends a
`query_next_image` — measured at 1h14m and 1h40m after joining. At quirk-match
time it is None, so a filtered pair of registrations would always pick the wrong
branch on first pairing and only correct itself after a restart, stranding the
first branch's entities as orphans.

Capabilities verified on live devices (ZHA read/write + Tuya-gateway sniff):
  OnOff 0x0006:
    0x0000 on_off                          -> light on/off        (writable)
    0x8001 backlight_mode                  -> indicator LED mode  (see above)
    0x4003 StartUpOnOff                    -> ACKed and stored but never applied
        at power-up (user-confirmed non-functional). ENTITY REMOVED.
    0x8000 child_lock / 0x8002 power_on_state  supported but read None (not exposed)
  LevelControl 0x0008:
    0x0000 current_level                   -> light brightness    (writable)
    0x0002 min_level, 0x0003 max_level     -> min/max brightness  (see above)
    0x4000 StartUpCurrentLevel             -> writable/persists but not applied
        at power-up (same as StartUpOnOff). ENTITY REMOVED.
    0x0010/0x0011/0x0014                   -> transition/on-level/move-rate (noise)
  Tuya manufacturer attrs 0xFC01-0xFC04 / 0xF000-0xF002 read UNSUPPORTED on both
  revisions and on both endpoints — unlike the TS110D sibling, the min/max
  feature lives in the STANDARD attributes here, not the Tuya range.

Quirk summary:
  - Keeps the two dimmable lights (on/off + brightness).
  - Min / Max Brightness as four writable percent `number`s (one pair per gang).
  - Indicator (backlight) LED mode select on EP1, written as uint8.
  - Suppresses noise + dead controls: default_move_rate / on_level /
    on_off_transition_time numbers, the non-functional power-on select
    (StartUpOnOff) and power-on level number (StartUpCurrentLevel), the duplicate
    Tuya power_on_state / child_lock selects, and per-endpoint firmware/OTA.
"""

import logging
from typing import Final

import zigpy.types as t
from zigpy.exceptions import ZigbeeException
from zigpy.quirks import CustomCluster
from zigpy.quirks.v2 import EntityType, QuirkBuilder
from zigpy.zcl.clusters.general import LevelControl
from zigpy.zcl.foundation import ZCLAttributeDef

from zhaquirks.tuya import TuyaZBOnOffAttributeCluster

_LOGGER = logging.getLogger(__name__)

ONOFF = TuyaZBOnOffAttributeCluster.cluster_id  # 0x0006
LEVEL = LevelControl.cluster_id  # 0x0008

# Standard ZCL LevelControl attribute IDs carrying the min/max brightness window.
MIN_LEVEL = LevelControl.AttributeDefs.min_level.id  # 0x0002
MAX_LEVEL = LevelControl.AttributeDefs.max_level.id  # 0x0003

# LevelControl current_level tops out at 254 (255 = "unchanged"); use it as the
# 100 % reference so the min/max brightness percent lines up with brightness.
_FULL = 254

# The entities expose 1..100 %, never 0. Raw 0 has no useful meaning here and one
# corner of it is actively harmful: the device accepts max = 0 without complaint
# (measured — it validates nothing, 0..255 all stored), which leaves the gang
# pinned at the bottom of its range.
_PCT_MIN = 1
_PCT_MAX = 100


def _pct_from_raw(raw: int) -> int:
    """Raw 0..254 level as the whole percent the user sees on the entity."""
    return round(raw * 100 / _FULL)


def _raw_from_pct(pct: float) -> int:
    """Percent as a raw 1..254 level, rounding half UP.

    Half-up rather than Python's half-to-even round() for consistency with the
    TS110D sibling quirk, which needs it to agree with the Tuya gateway
    byte-for-byte. On this 254 domain the two disagree at exactly one value
    (75 % -> 191 half-up, 190 half-to-even) and BOTH round-trip cleanly for every
    whole percent in 1..100 -- so this choice is about matching the sibling, not
    about correctness. The round trip itself is locked in by the unit tests.

    No attempt is made to reproduce the Tuya gateway's own rounding: it differs
    from a clean 254-domain conversion by 1-2 raw steps (~0.6 %), and matching it
    would mean carrying a fitted constant nobody could later justify.
    """
    return max(1, min(_FULL, int(pct * _FULL / 100 + 0.5)))


class SimonDimmerLevelControl(CustomCluster, LevelControl):
    """LevelControl presenting MinLevel/MaxLevel as writable percents.

    The device stores the dimming window in the standard MinLevel (0x0002) /
    MaxLevel (0x0003) attributes as a raw 0..254 level. get() converts to a
    whole percent and write_attributes() converts back, so ZHA's `multiplier` is
    left at 1 — feeding the conversion through `multiplier` would make the
    entity state a long float instead of a whole number.

    On app_version 132 these writes succeed and the firmware genuinely enforces
    the window; on 129 the device answers READ_ONLY and ZHA surfaces that as an
    error. Either way the quirk's job here is only conversion and validation.

    NOTE for anyone poking the device by hand: the percent contract applies to
    EVERY writer, not just the entities. `zha.set_zigbee_cluster_attribute` on
    min_level/max_level now takes a percent too — passing a raw level (say 77)
    writes something else entirely (raw 196). Same shape as the TS110D sibling.

    move_to_level* command handling is left untouched — both revisions are
    working standard dimmers.
    """

    _PCT_ATTRS = frozenset({MIN_LEVEL, MAX_LEVEL, "min_level", "max_level"})

    def get(self, key, default=None):
        """Show the raw 0..254 min/max brightness as a nearest-integer percent."""
        if key in self._PCT_ATTRS:
            raw = super().get(key, None)
            return default if raw is None else _pct_from_raw(raw)
        return super().get(key, default)

    async def write_attributes(self, attributes, manufacturer=None, **kwargs):
        """Convert percent -> raw, then refuse an inverted window."""
        converted = {}
        touches_limits = False
        for key, value in attributes.items():
            if key in self._PCT_ATTRS and isinstance(value, (int, float)):
                converted[key] = _raw_from_pct(value)
                touches_limits = True
            else:
                converted[key] = value

        if touches_limits:
            self._reject_inverted_window(converted, set(attributes))

        return await super().write_attributes(converted, manufacturer, **kwargs)

    def _raw_cached(self, attr_id: int):
        """The cached RAW level, bypassing this cluster's percent view of get()."""
        return super().get(attr_id, None)

    @staticmethod
    def _pick(converted: dict, attr_id: int, name: str):
        """Read a limit out of the write dict, whichever key form was used."""
        if attr_id in converted:
            return converted[attr_id]
        return converted.get(name)

    def _reject_inverted_window(self, converted: dict, requested: set) -> None:
        """Refuse a write that would leave max at or below min.

        This is our rule, not the firmware's. The device accepts an inverted
        window without complaint — measured on app_version 132: min 200 / max 100
        was written, acknowledged, read back, and the running level jumped to 200
        (min wins) — so nothing downstream will catch it.

        It is enforced here rather than through the entity bounds because ZHA
        takes a quirk's number min/max as static and cannot narrow one entity's
        range from the other's current value.

        Rejecting rather than silently adjusting the partner is deliberate: a
        value the user did not type is exactly the kind of quiet wrongness this
        device has already produced too much of. The message names which entity
        to move first, because with two coupled numbers the legal path depends on
        the order they are changed.

        A pair that cannot be completed (partner never cached) is let through
        rather than locking the control over an unverifiable rule.
        """
        lo = self._pick(converted, MIN_LEVEL, "min_level")
        hi = self._pick(converted, MAX_LEVEL, "max_level")
        if lo is None:
            lo = self._raw_cached(MIN_LEVEL)
        if hi is None:
            hi = self._raw_cached(MAX_LEVEL)
        if lo is None or hi is None or lo < hi:
            return

        wants_min = bool(requested & {MIN_LEVEL, "min_level"})
        wants_max = bool(requested & {MAX_LEVEL, "max_level"})
        if wants_min and not wants_max:
            msg = (
                f"Max Brightness is {_pct_from_raw(hi)} %, so Min Brightness cannot "
                f"be set to {_pct_from_raw(lo)} %. Raise Max Brightness first."
            )
        elif wants_max and not wants_min:
            msg = (
                f"Min Brightness is {_pct_from_raw(lo)} %, so Max Brightness cannot "
                f"be set to {_pct_from_raw(hi)} %. Lower Min Brightness first."
            )
        else:
            msg = (
                f"Min Brightness {_pct_from_raw(lo)} % must be below Max Brightness "
                f"{_pct_from_raw(hi)} %."
            )
        self.debug("rejecting inverted brightness window: %s", msg)
        raise ZigbeeException(msg)


class SimonDimmerOnOff(TuyaZBOnOffAttributeCluster):
    """Tuya OnOff with backlight_mode redeclared as uint8.

    Upstream types 0x8001 as the `SwitchBackLight` enum8. app_version 132
    rejects an enum8 (0x30) write to this attribute with INVALID_DATA_TYPE
    (0x8D); the Tuya gateway writes it as uint8 (0x20) and gets SUCCESS —
    sniffed directly, and corroborated by the type each revision uses when it
    REPORTS the attribute (132 reports uint8, 129 reports enum8).

    Redeclaring the type here makes every write go out as uint8. The select
    entity still uses SimonDimmerBacklightMode for its labels; the enum members
    are ints, so they serialise cleanly into a uint8 attribute.
    """

    class AttributeDefs(TuyaZBOnOffAttributeCluster.AttributeDefs):
        """Attribute definitions."""

        backlight_mode: Final = ZCLAttributeDef(id=0x8001, type=t.uint8_t)


class SimonDimmerBacklightMode(t.enum8):
    """Indicator / backlight LED mode (OnOff 0x8001).

    Labels follow the Simon SM0502 sibling dimmer: ZHA renders a select option
    as ``member_name.replace("_", " ")``, so these display as "Switch Status" /
    "Close" / "Switch Position". Integer values match the OnOff 0x8001 attribute.
    """

    Switch_Status = 0x00
    Close = 0x01
    Switch_Position = 0x02


def _brightness_numbers(builder):
    """Add the Min/Max Brightness percent numbers for both gangs.

    mode="slider" is a deliberate product choice: a brightness limit is a
    magnitude, and a slider shows where it sits in its range at a glance in a
    way a text box cannot.

    The cost is known and accepted. Dragging a ZHA number slider can emit one
    Zigbee write per intermediate step -- measured on the TS110D sibling, six
    writes inside one second -- so the device sees values the user only passed
    through on the way to the one they meant. Nothing here is damaged by that
    (each write is independent and the last one wins), it is just chatty; and
    the inverted-window guard is evaluated per write, so a drag that crosses
    the partner limit raises on the way past rather than only at the end.
    Switch back to mode="box" if that chattiness ever becomes a problem.
    """
    for endpoint_id in (1, 2):
        for attr_name, key, label in (
            (SimonDimmerLevelControl.AttributeDefs.min_level.name, "min", "Min"),
            (SimonDimmerLevelControl.AttributeDefs.max_level.name, "max", "Max"),
        ):
            builder = builder.number(
                attr_name,
                LEVEL,
                endpoint_id=endpoint_id,
                min_value=_PCT_MIN,
                max_value=_PCT_MAX,
                step=1,
                unit="%",
                mode="slider",
                entity_type=EntityType.CONFIG,
                translation_key=f"{key}_brightness_{endpoint_id}",
                fallback_name=f"{label} Brightness {endpoint_id}",
            )
    return builder


# ────────────────────────────────────────────────────────────────
# TS0052 — 241E8016TY 2-gang dimmer (_TZ3002_cqpubrcz)
# Built to the app_version 132 standard — see the module docstring.
# ────────────────────────────────────────────────────────────────
_builder = (
    QuirkBuilder("_TZ3002_cqpubrcz", "TS0052")
    # ── EP1 / EP2: OnOff with backlight_mode retyped to uint8 ──
    .replaces(SimonDimmerOnOff, endpoint_id=1)
    .replaces(SimonDimmerOnOff, endpoint_id=2)
    # ── EP1 / EP2: LevelControl with percent min/max conversion + validation ──
    .replaces(SimonDimmerLevelControl, endpoint_id=1)
    .replaces(SimonDimmerLevelControl, endpoint_id=2)
    # ── Suppress useless default LevelControl config entities (both gangs) ──
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=LEVEL, unique_id_suffix="on_off_transition_time"
    )
    .prevent_default_entity_creation(
        endpoint_id=2, cluster_id=LEVEL, unique_id_suffix="on_off_transition_time"
    )
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=LEVEL, unique_id_suffix="on_level"
    )
    .prevent_default_entity_creation(
        endpoint_id=2, cluster_id=LEVEL, unique_id_suffix="on_level"
    )
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=LEVEL, unique_id_suffix="default_move_rate"
    )
    .prevent_default_entity_creation(
        endpoint_id=2, cluster_id=LEVEL, unique_id_suffix="default_move_rate"
    )
    # ── Suppress the duplicate Tuya power-on / child-lock selects ──
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=ONOFF, unique_id_suffix="power_on_state"
    )
    .prevent_default_entity_creation(
        endpoint_id=2, cluster_id=ONOFF, unique_id_suffix="power_on_state"
    )
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=ONOFF, unique_id_suffix="child_lock"
    )
    .prevent_default_entity_creation(
        endpoint_id=2, cluster_id=ONOFF, unique_id_suffix="child_lock"
    )
    # ── Remove the non-functional power-on controls (both gangs): the Tuya app
    #    has no power-on setting for this SKU and the firmware ACKs but never
    #    applies StartUpOnOff (0x4003) / StartUpCurrentLevel (0x4000) at power-up
    #    (user-confirmed) — so they are dead controls, not exposed. ──
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=ONOFF, unique_id_suffix="StartUpOnOff"
    )
    .prevent_default_entity_creation(
        endpoint_id=2, cluster_id=ONOFF, unique_id_suffix="StartUpOnOff"
    )
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=LEVEL, unique_id_suffix="start_up_current_level"
    )
    .prevent_default_entity_creation(
        endpoint_id=2, cluster_id=LEVEL, unique_id_suffix="start_up_current_level"
    )
)

# ── Min / Max brightness (standard 0x0002 / 0x0003) — writable percent numbers ──
_builder = _brightness_numbers(_builder)

(
    _builder
    # ── Indicator (backlight) LED mode select (device-global, EP1 only) ──
    .enum(
        SimonDimmerOnOff.AttributeDefs.backlight_mode.name,
        SimonDimmerBacklightMode,
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
