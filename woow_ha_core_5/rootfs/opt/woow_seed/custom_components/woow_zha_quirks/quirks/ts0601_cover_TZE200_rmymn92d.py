"""ZHA Quirk for Tuya TS0601 curtain-track motor _TZE200_rmymn92d.

Device 19-BCM500DS-TYZ-B — 窗帘电动轨道 (electric curtain track / 開合簾),
Tuya model "BCM100D tuya zigbee B", product `rmymn92d`, IEEE a4:c1:38:54:22:d6:b3:30.
On the Simon-home Tuya gateway (same as 8-58E7101).

ZHA signature (paired): manufacturer `_TZE200_rmymn92d`, model `TS0601`. EP1 is a
Tuya MCU node — input clusters Basic(0x0000)/Groups(0x0004)/Scenes(0x0005)/Tuya
0xEF00, output Time(0x000a)/OTA(0x0019); EP242 Green Power. There are NO standard
cover clusters, so without a quirk ZHA exposes no usable cover entity — all control
goes through the Tuya 0xEF00 datapoints below.

DP map (Tuya cloud thing-model, abilityId = DP id):
  DP1  - ENUM  - control:        0=open, 1=stop, 2=close
  DP2  - VALUE - percent_control: set target position 0-100 %
  DP3  - VALUE - percent_state:   current position report 0-100 % (ro)
  DP5  - BOOL  - control_back:    motor reverse (0=forward, 1=reversed)
  DP7  - ENUM  - work_state:      opening/closing (ro) — not exposed (redundant with
                                  the cover's own moving state)
  DP10 - BITMAP- fault:           motor_fault (ro)
  DP11 - VALUE - time_total:      full-travel time 0-120000 ms (ro)

This is the same standard Tuya cover layout as the sibling 20-BCM100DB
(`_TZE200_eegnwoyw`) and modelled on `ts0601_cover_TZE284_qxjkdfyt.py`.

Live-verified behaviour (2026-06-29, 192.168.2.6, motor mounted on the track):
  * Position reporting/positioning is correct with `.tuya_cover(invert=True)` (the
    Tuya-cover default): a physically-closed curtain reads 0 %, fully-open reads 100 %.
  * BUT this unit's DP1 open/close control is REVERSED vs its declared enum — sending
    ZCL up_open (TuyaCoverControl.Open=0) physically CLOSES the curtain and vice-versa,
    while the position pipeline stays correct.  `ReversedControlCover` swaps
    up_open<->down_close so the HA Open/Close buttons drive the right direction; the
    position (DP2 set / DP3 report) pipeline is left untouched (already correct).
    (Motor Reverse / DP5 is left at its default OFF and stays available as a per-install
    escape hatch, but it changes the motor's own frame and needs a recalibration cycle,
    so the deterministic control swap is done in the quirk instead.)
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
    TuyaQuirkBuilder("_TZE200_rmymn92d", "TS0601")
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
