"""ZHA Quirk for WOOW TECH WO_50801_5 — Zigbee dry-contact curtain (position) module.

窗簾比例模組 — three potential-free (dry-contact) relays Open / Stop / Close driving a
3/4-wire dry-contact curtain motor (see development/WO_50801_5/WO_50801_5_接線圖.html). The
board-level jog/latch DIP switch and the self-powered kinetic-switch socket are HARDWARE-only
and have NO Zigbee representation.

ZHA signature (paired 2026-07-23, IEEE a4:c1:38:10:ee:17:1b:34):
  manufacturer = "_TZ3000_9hadsgq9", model = "TS130F"
  EP1 profile 0x0104 device_type 0x0202 (Window Covering)
    in:  0x0000 Basic, 0x0004 Groups, 0x0005 Scenes, 0x0006 OnOff,
         0x0102 WindowCovering, 0xE001 (Tuya config)
    out: 0x000A Time, 0x0019 OTA;  EP242 Green Power

This is a STANDARD ZCL cover (NOT a Tuya 0xEF00 MCU node): the Tuya gateway's MCU translates
its cloud datapoints to the ZCL WindowCovering cluster, so ZHA already exposes a working
`cover` entity WITHOUT a quirk.

Live-verified 2026-07-23 that this firmware has the up_open/down_close commands SWAPPED while
the percentage pipeline is correct: HA `open_cover` (up_open) drove the device to lift 100 %
(HA 0 %/closed) and `close_cover` (down_close) to lift 0 % (HA 100 %/open), yet
`set_position 30/50` landed correctly at 30/50 %. So without a quirk the Open/Close buttons
disagree with the position slider. WoowTS130FCover swaps up_open<->down_close (like
ts0601_cover_TZE200_rmymn92d.py's ReversedControlCover) so the buttons and the slider agree;
the DP2 set / position report pipeline is left untouched (already correct). The device's own
Motor Direction (0xF002) below remains the per-install escape hatch if the whole travel is
physically mirrored.

Tuya cloud thing-model (project simon-zigbee-to-ha, Singapore DC, device
a30e15c6fb1bdb534dshci, category ``clkg`` — see development/WO_50801_5/tuya_cloud_data.json):
  DP1 control (open/stop/close)  -> ZCL WindowCovering commands  (native)
  DP2 percent_control (0-100 %)  -> ZCL current_position_lift_percentage / go_to_lift (native)
  DP7 backlight_switch (bool)    -> panel backlight (Zigbee mapping unconfirmed; not exposed)
  DP8 control_back (fwd/back)    -> WindowCovering 0xF002 motor_reversal  (config below)
  DP10 quick_calibration_1 (s)   -> WindowCovering 0xF003 calibration_time (config below;
                                    0xF003 is in DECISECONDS → shown/written as seconds ×0.1)

This quirk keeps the native cover and adds the TS130F manufacturer config attributes plus
trims the redundant firmware/OTA + window-covering-type diagnostic entities. The two config
attributes (0xF002 / 0xF003) are the standard TS130F manufacturer attributes; they are
verified live after deploy — any that read unsupported on this variant are removed.
"""

from typing import Final

import zigpy.types as t
from zigpy.quirks import CustomCluster
from zigpy.quirks.v2 import EntityType, QuirkBuilder
from zigpy.quirks.v2.homeassistant import UnitOfTime
from zigpy.quirks.v2.homeassistant.number import NumberDeviceClass
from zigpy.zcl.clusters.closures import WindowCovering
from zigpy.zcl.foundation import ZCLAttributeDef

WINDOW_COVERING = WindowCovering.cluster_id  # 0x0102

# TS130F manufacturer attributes on the WindowCovering cluster.
TUYA_COVER_CALIBRATION = 0xF001  # enum: 0=calibrating / 1=finished (trigger — not exposed)
TUYA_COVER_MOTOR_REVERSAL = 0xF002  # enum: 0=forward / 1=reversed  (Tuya DP8 control_back)
TUYA_COVER_CALIBRATION_TIME = 0xF003  # uint16 full-travel time in DECISECONDS (0.1 s); Tuya DP10


class MotorReversal(t.enum8):
    """Motor steering (WindowCovering 0xF002) — forward / reversed."""

    Forward = 0x00
    Reversed = 0x01


class WoowTS130FCover(CustomCluster, WindowCovering):
    """Standard WindowCovering + the TS130F Tuya manufacturer attributes.

    The cover behaviour is inherited unchanged (this variant honours the standard
    up_open/down_close/stop/go_to_lift_percentage commands — verified live); we only declare
    the manufacturer attributes so they can back the motor-direction / calibration-time config
    entities.
    """

    class AttributeDefs(WindowCovering.AttributeDefs):
        """Extend with the TS130F manufacturer attributes."""

        motor_reversal: Final = ZCLAttributeDef(
            id=TUYA_COVER_MOTOR_REVERSAL, type=MotorReversal
        )
        calibration_time: Final = ZCLAttributeDef(
            id=TUYA_COVER_CALIBRATION_TIME, type=t.uint16_t
        )

    async def command(self, command_id, *args, **kwargs):
        """Swap up_open<->down_close (this firmware has them inverted).

        Only the open/close *control* commands are swapped; stop and
        go_to_lift_percentage pass straight through (the position set/report
        pipeline is already correct — verified live)."""
        if command_id == WindowCovering.ServerCommandDefs.up_open.id:
            command_id = WindowCovering.ServerCommandDefs.down_close.id
        elif command_id == WindowCovering.ServerCommandDefs.down_close.id:
            command_id = WindowCovering.ServerCommandDefs.up_open.id
        return await super().command(command_id, *args, **kwargs)


(
    QuirkBuilder("_TZ3000_9hadsgq9", "TS130F")
    # ── Keep the native cover; add the TS130F manufacturer config attributes ──
    .replaces(WoowTS130FCover, endpoint_id=1)
    # ── Motor direction / reverse (0xF002) — select (config) ─────────────
    .enum(
        WoowTS130FCover.AttributeDefs.motor_reversal.name,
        MotorReversal,
        WINDOW_COVERING,
        endpoint_id=1,
        entity_type=EntityType.CONFIG,
        translation_key="motor_direction",
        fallback_name="Motor Direction",
    )
    # ── Full-travel calibration time (0xF003) — number (config) ──────────
    # 0xF003 is stored in DECISECONDS (0.1 s): live-verified — writing raw 100 gave a
    # ~10 s full travel. multiplier=0.1 shows/writes real seconds (raw 100 → 10.0 s;
    # set 12 s → raw 120), and step=0.1 exposes the device's native 0.1 s granularity
    # (decimals). Unlike the Tuya app, ZHA writes this at ANY cover position (the app's
    # "fully close first" is a UI flow, not a firmware constraint — user-confirmed).
    .number(
        WoowTS130FCover.AttributeDefs.calibration_time.name,
        WINDOW_COVERING,
        endpoint_id=1,
        min_value=1,
        max_value=900,
        step=0.1,
        multiplier=0.1,
        unit=UnitOfTime.SECONDS,
        device_class=NumberDeviceClass.DURATION,
        entity_type=EntityType.CONFIG,
        translation_key="calibration_time",
        fallback_name="Calibration Time",
    )
    # ── Trim auto-generated noise ────────────────────────────────────────
    # ZCL WindowCovering "type" diagnostic is meaningless for this dry-contact module.
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=WINDOW_COVERING,
        unique_id_suffix="window_covering_type",
    )
    # Redundant firmware/OTA update entity (no ZHA OTA image → permanently unknown).
    .prevent_default_entity_creation(unique_id_suffix="firmware_update")
    .add_to_registry()
)
