"""ZHA Quirk for Tuya TS0601 curtain track _TZE200_nogaemzt.

開合簾 (curtain track) — TZE200 protocol.
Uses single DP2 for both position set and position report.

DP map:
  DP1   - ENUM  - cover control: 0=open, 1=stop, 2=close
  DP2   - VALUE - position (0-100), set AND report (single DP)
  DP5   - ENUM  - motor direction: 0=normal, 1=reversed
  DP7   - ENUM  - work state: 0=idle, 1=moving
  DP101 - BOOL  - remote register (pairing)
  DP102 - BOOL  - reset all limits
  DP103 - BOOL  - upper limit confirm/reset
  DP104 - BOOL  - middle limit confirm/reset
  DP105 - BOOL  - lower limit confirm/reset
  DP106 - ENUM  - motor mode: 0=linkage, 1=inching
"""

import zigpy.types as t
from zigpy.profiles import zha
from zigpy.quirks.v2 import EntityType
from zigpy.zcl.clusters.closures import WindowCovering
from zhaquirks.tuya.builder import TuyaQuirkBuilder
from zhaquirks.tuya.mcu import TuyaWindowCovering


class MotorMode(t.enum8):
    """Motor operating mode."""
    Linkage = 0x00
    Inching = 0x01


(
    TuyaQuirkBuilder("_TZE200_nogaemzt", "TS0601")
    # ── Cover setup (manual, since DP2 serves both state & control) ──
    .tuya_dp(
        dp_id=1,
        ep_attribute=TuyaWindowCovering.ep_attribute,
        attribute_name=TuyaWindowCovering.AttributeDefs.tuya_cover_command.name,
    )
    .tuya_dp(
        dp_id=2,
        ep_attribute=TuyaWindowCovering.ep_attribute,
        attribute_name=WindowCovering.AttributeDefs.current_position_lift_percentage.name,
        converter=lambda x: 100 - x,
        dp_converter=lambda x: 100 - x,
    )
    .adds(TuyaWindowCovering)
    .replaces_endpoint(1, device_type=zha.DeviceType.WINDOW_COVERING_DEVICE)
    # ── Motor direction (DP5) ────────────────────────────────
    .tuya_switch(
        dp_id=5,
        attribute_name="motor_direction",
        entity_type=EntityType.CONFIG,
        translation_key="motor_direction",
        fallback_name="Motor Direction",
    )
    # ── Remote register (DP101) ──────────────────────────────
    .tuya_switch(
        dp_id=101,
        attribute_name="remote_register",
        entity_type=EntityType.CONFIG,
        translation_key="remote_register",
        fallback_name="Remote Register",
    )
    # ── Reset all limits (DP102) ─────────────────────────────
    .tuya_switch(
        dp_id=102,
        attribute_name="reset_all_limits",
        entity_type=EntityType.CONFIG,
        translation_key="reset_all_limits",
        fallback_name="Reset All Limits",
    )
    # ── Upper limit (DP103) ──────────────────────────────────
    .tuya_switch(
        dp_id=103,
        attribute_name="upper_limit_set",
        entity_type=EntityType.CONFIG,
        translation_key="upper_limit_set",
        fallback_name="Upper Limit Set/Reset",
    )
    # ── Middle limit (DP104) ─────────────────────────────────
    .tuya_switch(
        dp_id=104,
        attribute_name="middle_limit_set",
        entity_type=EntityType.CONFIG,
        translation_key="middle_limit_set",
        fallback_name="Middle Limit Set/Reset",
    )
    # ── Lower limit (DP105) ──────────────────────────────────
    .tuya_switch(
        dp_id=105,
        attribute_name="lower_limit_set",
        entity_type=EntityType.CONFIG,
        translation_key="lower_limit_set",
        fallback_name="Lower Limit Set/Reset",
    )
    # ── Motor mode (DP106) — select entity ───────────────────
    .tuya_enum(
        dp_id=106,
        attribute_name="motor_mode",
        enum_class=MotorMode,
        entity_type=EntityType.CONFIG,
        translation_key="motor_mode",
        fallback_name="Motor Mode",
    )
    .skip_configuration()
    .add_to_registry()
)
