"""ZHA Quirk for Tuya mmWave human-presence sensor _TZE204_dtzziy1e (WO_40116).

Tuya product "人体存在传感器" (human-presence sensor), category ``hps``, product_id
``dtzziy1e``, model **MTG275-ZB-RL**. A 24 GHz mmWave radar occupancy sensor with a built-in
relay output (通斷器) that can auto-switch a load on presence — the **ceiling-mounted (吸頂式)**
sibling of WO_40117 (_TZE204_clrdrnya, MTG235-ZB-RL). TS0601 / 0xEF00 Tuya-MCU device.

The Tuya cloud thing-model is byte-for-byte identical to WO_40117 (same 20 DPs, same codes,
ranges and scales — see tuya_export/_out/WO_40116.model.json), so this quirk mirrors the proven
``ts0601_presence_TZE204_clrdrnya`` mapping verbatim, changing only the manufacturer signature.

ZHA signature (read from the paired device, IEEE 7c:31:fa:ff:fe:be:37:0f):
  manufacturer = "_TZE204_dtzziy1e", model = "TS0601"
  EP1  profile 0x0104  device_type 0x0051
       in : 0x0000 Basic, 0x0004 Groups, 0x0005 Scenes,
            0x0400 IlluminanceMeasurement, 0x0406 OccupancySensing, 0xEF00 Tuya MCU
       out: 0x000A Time, 0x0019 OTA
The native 0x0400 / 0x0406 clusters are Tuya placeholders; the real radar data arrives over
0xEF00 datapoints, so this quirk routes DP1 → OccupancySensing and DP104 → IlluminanceMeasurement
(overlaying them as Tuya-local clusters) and decodes the remaining DPs into config/diagnostic
entities.

Like the WO_40117 quirk this additionally:
  * suppresses the permanently-inert firmware / OTA ``update`` entity (no ZHA image exists), and
  * exposes the two status diagnostics the app shows but upstream omits — DP6 self-test
    (設備狀態) and DP113 parameter-config result (參數配置結果).

Firmware-specific constraints below (raised number minimums, omitted enum values) are INHERITED
from the verified _TZE204_clrdrnya sibling — this is the same OEM radar family — and are to be
re-confirmed on this unit during live verification; if the MTG275 firmware is more permissive the
bounds can be widened.

DP map (from the Tuya cloud thing-model, ``abilityId`` = DP id; ``scale`` = decimal places →
displayed value = raw / 10^scale; see tuya_export/DP_REFERENCE.md → WO_40116):
  DP1   - enum  - presence_state (none/presence)        -> occupancy binary_sensor (0x0406)
  DP2   - value - sensitivity 1-9                       -> number  "Motion sensitivity"
  DP3   - value - near_detection 0-10 m (sc 2)          -> number  "Minimum range"
  DP4   - value - far_detection 1.5-10 m (sc 2)         -> number  "Maximum range"
  DP6   - enum  - checking_result (self-test)           -> sensor  "Self test result" (diag, NEW)
  DP9   - value - target_dis_closest 0-10 m (sc 2)      -> sensor  "Target distance"
  DP101 - value - confirm_delay 入場過濾時間 0-5 s (sc 2)-> number  "Entry filter time" (÷100)
  DP102 - value - fading_time (離場延時) 5-1500 s        -> number  "Fading time"
  DP103 - string- cli ("cline") opaque                  -> not exposed
  DP104 - value - illuminance (sc 1)                    -> illuminance sensor (0x0400, ÷10)
  DP105 - value - trigger_sensitivity 1-7              -> number  "Entry sensitivity"
  DP106 - value - trigger_distance 0-10 m (sc 2)        -> number  "Entry distance indentation"
  DP107 - enum  - relay_mode (standard/local only*)     -> select  "Breaker mode" (*force/none rejected)
  DP108 - enum  - relay_state (off/on)                  -> select  "Breaker status" (manual On needs Standard mode)
  DP109 - enum  - running_sta (off/on)                  -> select  "Status indication" (LED)
  DP110 - value - illumin_threshold 0-420 lux (sc 1)    -> number  "Illuminance threshold"
  DP111 - enum  - relay_polarity (NO only*)             -> select  "Breaker polarity" (*NC rejected, fixed NO)
  DP112 - value - block_time 0-60 s (sc 1)              -> number  "Block time"
  DP113 - enum  - param_result (config validation)      -> sensor  "Parameter result" (diag, NEW)
  DP114 - enum  - resfacset (factory reset, wr)         -> not exposed (destructive, write-only)
  DP115 - enum  - sensor_ctrl (on/off/occupied/unoccup) -> select  "Sensor mode"
"""

import math

import zigpy.types as t
from zigpy.quirks.v2 import EntityPlatform, EntityType
from zigpy.quirks.v2.homeassistant import LIGHT_LUX, UnitOfLength, UnitOfTime
from zigpy.quirks.v2.homeassistant.sensor import SensorDeviceClass, SensorStateClass
from zigpy.zcl.clusters.measurement import OccupancySensing

from zhaquirks.tuya import TuyaLocalCluster
from zhaquirks.tuya.builder import TuyaQuirkBuilder


class TuyaOccupancySensing(OccupancySensing, TuyaLocalCluster):
    """Tuya local occupancy sensing cluster (fed by DP1)."""


class TuyaSelfCheckResult(t.enum8):
    """DP6 device self-test / equipment status (設備狀態)."""

    Checking = 0x00
    CheckSuccess = 0x01
    CheckFailure = 0x02
    Others = 0x03
    CommFault = 0x04
    RadarFault = 0x05


class TuyaBreakerMode(t.enum8):
    """DP107 relay/breaker mode (通斷器模式).

    The Tuya thing-model declares [standard, local, force, none], but the clrdrnya sibling's
    firmware only IMPLEMENTS standard/local — writing force(2)/none(3) is rejected by the MCU and
    HA reverts. They are intentionally omitted (matches upstream zhaquirks); re-confirm on MTG275.
    """

    Standard = 0x00
    Local = 0x01


class TuyaBreakerStatus(t.enum8):
    """DP108 relay/breaker output state (通斷器狀態)."""

    Off = 0x00
    On = 0x01


class TuyaStatusIndication(t.enum8):
    """DP109 LED status indication (狀態指示)."""

    Off = 0x00
    On = 0x01


class TuyaBreakerPolarity(t.enum8):
    """DP111 relay output polarity (輸出極性): NO = normally open.

    The thing-model declares [close(NC), open(NO)], but the clrdrnya sibling's relay is FIXED as
    NO — writing NC(0) is rejected (stays NO) and the device reports parameter_result =
    PolarityError. So NC is omitted; the select shows only NO. Re-confirm on MTG275.
    """

    NO = 0x01


class TuyaMotionSensorMode(t.enum8):
    """DP115 sensor force-control mode (傳感器)."""

    On = 0x00
    Off = 0x01
    Occupied = 0x02
    Unoccupied = 0x03


class TuyaParamResult(t.enum8):
    """DP113 parameter-configuration validation result (參數配置結果)."""

    NoError = 0x00
    TrigDistanceError = 0x01
    DistanceTooNear = 0x02
    DistanceTooFar = 0x03
    RelayNormallyOpen = 0x04
    InhibitError = 0x05
    PolarityError = 0x06


(
    TuyaQuirkBuilder("_TZE204_dtzziy1e", "TS0601")
    # ── Presence → standard Occupancy cluster (DP1) ─────────────────────
    .tuya_dp(
        dp_id=1,
        ep_attribute=TuyaOccupancySensing.ep_attribute,
        attribute_name=OccupancySensing.AttributeDefs.occupancy.name,
        converter=lambda x: x == 1,
    )
    .adds(TuyaOccupancySensing)
    # ── Live readings ───────────────────────────────────────────────────
    .tuya_sensor(
        dp_id=9,
        attribute_name="distance",
        type=t.uint16_t,
        divisor=100,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.DISTANCE,
        unit=UnitOfLength.METERS,
        entity_type=EntityType.STANDARD,
        translation_key="distance",
        fallback_name="Target distance",
    )
    # App-parity: the Tuya thing-model gives illuminance scale=1 (displayed lux = raw / 10),
    # matching the illuminance_threshold (DP110) below. Upstream's default tuya_illuminance
    # converter (10000*log10(raw)+1) displays the raw value un-divided, i.e. 10x the app and 10x
    # the threshold's units. Divide the raw by 10 before the ZCL log-encoding so the reading
    # matches both the WOOW app and the threshold.
    .tuya_illuminance(
        dp_id=104,
        converter=lambda x: 10000 * math.log10(x / 10) + 1 if x else 0,
    )
    # ── Device self-test (DP6) — diagnostic sensor (NEW vs upstream) ─────
    .tuya_enum(
        dp_id=6,
        attribute_name="self_test",
        enum_class=TuyaSelfCheckResult,
        entity_platform=EntityPlatform.SENSOR,
        entity_type=EntityType.DIAGNOSTIC,
        translation_key="self_test",
        fallback_name="Self test result",
    )
    # ── Parameter-config result (DP113) — diagnostic sensor (NEW) ────────
    .tuya_enum(
        dp_id=113,
        attribute_name="parameter_result",
        enum_class=TuyaParamResult,
        entity_platform=EntityPlatform.SENSOR,
        entity_type=EntityType.DIAGNOSTIC,
        translation_key="parameter_result",
        fallback_name="Parameter result",
    )
    # ── Radar tuning (config numbers) ───────────────────────────────────
    # Ranges are the DEVICE thing-model values (raw min/max/step x multiplier), NOT upstream's
    # generic tuya_motion defaults — the MCU rejects out-of-range/off-step writes, which made HA
    # revert (e.g. 10 -> 9). DP2 sensitivity: raw 1..9 step 1, scale 0.
    .tuya_number(
        dp_id=2,
        attribute_name="move_sensitivity",
        type=t.uint16_t,
        min_value=1,
        max_value=9,
        step=1,
        mode="slider",
        translation_key="move_sensitivity",
        fallback_name="Motion sensitivity",
    )
    # DP3 near_detection (探測屏蔽距離): raw step 10, scale 2 -> step 0.1 m. Thing-model min is 0
    # but the clrdrnya FIRMWARE floor is 0.3 m (0/0.1/0.2 rejected), so min_value=0.3.
    # CROSS-FIELD RULE (device firmware, like the Tuya app): the minimum range must stay below the
    # maximum range (DP4) with a margin; values at/near maximum_range are rejected and HA reverts.
    # A static number range cannot express that dependency, so max stays at the thing-model 10.0.
    .tuya_number(
        dp_id=3,
        attribute_name="detection_distance_min",
        type=t.uint16_t,
        device_class=SensorDeviceClass.DISTANCE,
        unit=UnitOfLength.METERS,
        min_value=0.3,
        max_value=10.0,
        step=0.1,
        multiplier=0.01,
        mode="slider",
        translation_key="detection_distance_min",
        fallback_name="Minimum range",
    )
    # DP4 far_detection (探測距離): raw 150..1000 step 10, scale 2 -> 1.5..10.0 m step 0.1.
    .tuya_number(
        dp_id=4,
        attribute_name="detection_distance_max",
        type=t.uint16_t,
        device_class=SensorDeviceClass.DISTANCE,
        unit=UnitOfLength.METERS,
        min_value=1.5,
        max_value=10.0,
        step=0.1,
        multiplier=0.01,
        mode="slider",
        translation_key="detection_distance_max",
        fallback_name="Maximum range",
    )
    # App-parity: DP101 (confirm_delay / 入場過濾時間 "entry filter time") is scale=2 in the
    # thing-model (seconds = raw / 100, range 0-5.00 s); the WOOW app shows e.g. 0.10 s. Upstream
    # maps it ÷10 (showing 1.0 s), so use multiplier 0.01 to match the app. attribute_name kept as
    # "detection_delay" so the entity unique_id is unchanged (no orphan); label follows the app.
    .tuya_number(
        dp_id=101,
        attribute_name="detection_delay",
        type=t.uint16_t,
        device_class=SensorDeviceClass.DURATION,
        unit=UnitOfTime.SECONDS,
        min_value=0,
        max_value=5,
        step=0.01,
        multiplier=0.01,
        mode="slider",
        translation_key="entry_filter_time",
        fallback_name="Entry filter time",
    )
    # DP102 fading_time (離場延時): raw 5..1500 step 1, scale 0 -> 5..1500 s step 1.
    .tuya_number(
        dp_id=102,
        attribute_name="fading_time",
        type=t.uint16_t,
        device_class=SensorDeviceClass.DURATION,
        unit=UnitOfTime.SECONDS,
        min_value=5,
        max_value=1500,
        step=1,
        mode="slider",
        translation_key="fading_time",
        fallback_name="Fading time",
    )
    # DP105 trigger_sensitivity (入場靈敏度): raw 1..7 step 1, scale 0.
    .tuya_number(
        dp_id=105,
        attribute_name="entry_sensitivity",
        type=t.uint16_t,
        min_value=1,
        max_value=7,
        step=1,
        mode="slider",
        translation_key="entry_sensitivity",
        fallback_name="Entry sensitivity",
    )
    # DP106 trigger_distance (入場距離縮進): raw 0..1000 step 10, scale 2 -> 0.0..10.0 m step 0.1.
    # CROSS-FIELD RULE: like minimum_range, this must stay below maximum_range (DP4); values
    # at/near the current maximum_range are rejected by the firmware and HA reverts (expected).
    .tuya_number(
        dp_id=106,
        attribute_name="entry_distance_indentation",
        type=t.uint16_t,
        device_class=SensorDeviceClass.DISTANCE,
        unit=UnitOfLength.METERS,
        min_value=0,
        max_value=10.0,
        step=0.1,
        multiplier=0.01,
        mode="slider",
        translation_key="entry_distance_indentation",
        fallback_name="Entry distance indentation",
    )
    .tuya_number(
        dp_id=110,
        attribute_name="illuminance_threshold",
        type=t.uint16_t,
        device_class=SensorDeviceClass.ILLUMINANCE,
        unit=LIGHT_LUX,
        min_value=0,
        max_value=420,
        step=0.1,
        multiplier=0.1,
        mode="slider",
        translation_key="illuminance_threshold",
        fallback_name="Illuminance threshold",
    )
    # DP112 block_time (封鎖時間): raw step 1, scale 1 -> step 0.1 s; max raw 600 -> 60.0 s.
    # Thing-model min is 1 (0.1 s) but the clrdrnya FIRMWARE floor is 1.5 s (0.1..1.2 s rejected),
    # so min_value=1.5.
    .tuya_number(
        dp_id=112,
        attribute_name="block_time",
        type=t.uint16_t,
        device_class=SensorDeviceClass.DURATION,
        unit=UnitOfTime.SECONDS,
        min_value=1.5,
        max_value=60.0,
        step=0.1,
        multiplier=0.1,
        mode="slider",
        translation_key="block_time",
        fallback_name="Block time",
    )
    # ── Relay / breaker + LED (config selects) ──────────────────────────
    .tuya_enum(
        dp_id=107,
        attribute_name="breaker_mode",
        enum_class=TuyaBreakerMode,
        translation_key="breaker_mode",
        fallback_name="Breaker mode",
    )
    # DP108 breaker_status (the relay). Both Off/On are device-supported, but a MANUAL write only
    # sticks when breaker_mode = Standard; in Local (auto) mode the device drives the relay from
    # presence and overrides manual writes (setting On is rejected → reverts).
    .tuya_enum(
        dp_id=108,
        attribute_name="breaker_status",
        enum_class=TuyaBreakerStatus,
        translation_key="breaker_status",
        fallback_name="Breaker status",
    )
    .tuya_enum(
        dp_id=109,
        attribute_name="status_indication",
        enum_class=TuyaStatusIndication,
        translation_key="status_indication",
        fallback_name="Status indication",
    )
    .tuya_enum(
        dp_id=111,
        attribute_name="breaker_polarity",
        enum_class=TuyaBreakerPolarity,
        translation_key="breaker_polarity",
        fallback_name="Breaker polarity",
    )
    .tuya_enum(
        dp_id=115,
        attribute_name="sensor_mode",
        enum_class=TuyaMotionSensorMode,
        translation_key="sensor_mode",
        fallback_name="Sensor mode",
    )
    # ── Suppress the permanently-inert firmware / OTA update entity ─────
    .prevent_default_entity_creation(unique_id_suffix="firmware_update")
    .skip_configuration()
    .add_to_registry()
)
