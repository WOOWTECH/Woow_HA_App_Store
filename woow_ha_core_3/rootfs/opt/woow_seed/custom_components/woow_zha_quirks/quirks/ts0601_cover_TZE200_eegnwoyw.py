"""ZHA Quirk for Tuya TS0601 curtain-track motor _TZE200_eegnwoyw (20-BCM100DB).

窗帘电动轨道 (electric curtain track / 開合簾) — model "BCM100DB tuya ZigBee".
Despite the "BCM" name this is a CURTAIN MOTOR, not a breaker/energy meter.
Sibling of 19-BCM500DS (`_TZE200_rmymn92d`) — identical DP layout, same firmware quirks.

ZHA signature (paired, live-confirmed 2026-06-30 on 192.168.2.6): manufacturer
`_TZE200_eegnwoyw`, model `TS0601`, IEEE 8c:f6:81:ff:fe:d1:a9:e2. EP1 is a Tuya MCU node
(in: Basic 0x0000, Groups 0x0004, Scenes 0x0005, WindowCovering 0x0102, Tuya 0xEF00;
out: Time 0x000a, OTA 0x0019). All control goes through the Tuya 0xEF00 datapoints below.

DP map (Tuya cloud thing-model, see tuya_export/DP_REFERENCE.md):
  DP1  - ENUM  - control:        0=open, 1=stop, 2=close
  DP2  - VALUE - percent_control: set target position 0-100 %
  DP3  - VALUE - percent_state:   current position report 0-100 % (ro)
  DP5  - BOOL  - control_back:    motor reverse (0=forward, 1=reversed)
  DP7  - ENUM  - work_state:      opening/closing (ro) — not exposed (redundant with
                                  the cover's own moving state)
  DP10 - BITMAP- fault:           motor_fault (ro)
  DP11 - VALUE - time_total:      full-travel time 0-120000 ms (ro)

Live-verified behaviour (2026-06-30, 192.168.2.6 — same as the sibling rmymn92d):
  * Position reporting/positioning is correct with `.tuya_cover(invert=True)`: set-position
    50 % returns 50 %, the DP2 set / DP3 report pipeline is accurate.
  * BUT this unit's DP1 open/close control is REVERSED vs its declared enum — the HA
    open_cover button drove the position to 1 % (closing) and close_cover drove it to 100 %.
    `ReversedControlCover` swaps up_open<->down_close so the HA Open/Close buttons drive the
    right direction; the position pipeline is left untouched (already correct). Motor Reverse
    (DP5) is left at its default OFF as a per-install escape hatch (it changes the motor's own
    frame and needs a recalibration cycle, so the deterministic control swap is done here).
"""

from zigpy.quirks.v2 import EntityType
from zigpy.quirks.v2.homeassistant import UnitOfTime
from zigpy.quirks.v2.homeassistant.binary_sensor import BinarySensorDeviceClass
from zigpy.quirks.v2.homeassistant.sensor import SensorDeviceClass
from zigpy.zcl.clusters.closures import WindowCovering
import zigpy.types as t
from zhaquirks.tuya.builder import TuyaQuirkBuilder
from zhaquirks.tuya.mcu import TuyaWindowCovering

WINDOW_COVERING = 0x0102  # ZCL WindowCovering cluster id


class ReversedControlCover(TuyaWindowCovering):
    """TuyaWindowCovering with open/close swapped for this reversed-control firmware.

    Only the up_open/down_close *control* commands are swapped; stop and
    go_to_lift_percentage pass straight through (the DP2/DP3 position pipeline is
    already correct under invert=True)."""

    async def command(self, command_id, *args, **kwargs):
        if command_id == WindowCovering.ServerCommandDefs.up_open.id:
            command_id = WindowCovering.ServerCommandDefs.down_close.id
        elif command_id == WindowCovering.ServerCommandDefs.down_close.id:
            command_id = WindowCovering.ServerCommandDefs.up_open.id
        return await super().command(command_id, *args, **kwargs)


(
    TuyaQuirkBuilder("_TZE200_eegnwoyw", "TS0601")
    # ── Cover: open/stop/close (DP1) + position set (DP2) / report (DP3) ──
    .tuya_cover(
        control_dp=1,
        position_state_dp=3,
        position_control_dp=2,
        invert=True,
        cover_cfg=ReversedControlCover,
    )
    # ── Motor direction / reverse (DP5) ──────────────────────────────────
    .tuya_switch(
        dp_id=5,
        attribute_name="motor_direction",
        entity_type=EntityType.CONFIG,
        translation_key="motor_direction",
        fallback_name="Motor Reverse",
    )
    # ── Motor fault (DP10) — diagnostic binary_sensor ────────────────────
    .tuya_binary_sensor(
        dp_id=10,
        attribute_name="motor_fault",
        entity_type=EntityType.DIAGNOSTIC,
        device_class=BinarySensorDeviceClass.PROBLEM,
        translation_key="motor_fault",
        fallback_name="Motor Fault",
    )
    # ── Full-travel time (DP11, ms → s) — diagnostic sensor ──────────────
    .tuya_sensor(
        dp_id=11,
        attribute_name="travel_time_total",
        type=t.uint32_t,
        divisor=1000,
        unit=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        entity_type=EntityType.DIAGNOSTIC,
        translation_key="travel_time_total",
        fallback_name="Full Travel Time",
    )
    # ── Trim auto-generated noise entities ───────────────────────────────
    # ZCL WindowCovering "type" diagnostic (窗簾類型) is meaningless for this track.
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=WINDOW_COVERING,
        unique_id_suffix="window_covering_type",
    )
    # Redundant firmware/OTA update entity (matches all endpoints by uid suffix).
    .prevent_default_entity_creation(unique_id_suffix="firmware_update")
    .skip_configuration()
    .add_to_registry()
)
