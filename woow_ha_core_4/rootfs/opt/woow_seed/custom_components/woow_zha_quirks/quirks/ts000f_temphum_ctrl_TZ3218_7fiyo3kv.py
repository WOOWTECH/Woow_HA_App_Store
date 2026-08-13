"""ZHA Quirk for Tuya 1-channel temperature/humidity controller _TZ3218_7fiyo3kv (21-TYZGTH1CH-D1RF).

Tuya product "1路zb温湿度" (1-way ZB temp/humidity), category ``kg``, product_id ``7fiyo3kv``.
Functionally an inkbird / STC-1000-style **温湿度控制器**: a single relay output that can be
driven manually or automatically switched on/off against temperature & humidity thresholds,
with live temperature/humidity readings, calibration, hysteresis and child-lock.

ZHA signature (read from the paired device, IEEE a4:c1:38:0b:14:d4:9d:2b):
  manufacturer = "_TZ3218_7fiyo3kv", model = "TS000F"
  EP1  profile 0x0104  in: 0x0000,0x0003,0x0004,0x0005,0x0006, 0xE000,0xE001, 0xEF00
                       out: 0x000A,0x0019      EP242 = Green Power
The 0xEF00 Tuya MCU cluster carries all the temp/humidity datapoints, so a bare pairing
exposes almost nothing useful — this TuyaQuirkBuilder quirk decodes the DPs into entities.

DP map (from the Tuya cloud thing-model, see tuya_export/DP_REFERENCE.md → 21-TYZGTH1CH-D1RF;
``scale`` = decimal places → on-wire integer = value x 10^scale):
Exposed entity set (trimmed 2026-07-02 per user request — only the useful/working entities):
  DP1   - BOOL  - switch_1: relay STATUS echo only (ACK-then-ignore on write; the real relay
                  control is STANDARD ZCL OnOff 0x0006 On/Off — proven by sniffing) -> not used
  DP14  - ENUM  - relay_status: off / on / memory (power-on behaviour)           -> select (config)
  DP102 - VALUE - temp_current: -50.0..100.0 C (x10)                             -> temperature sensor
  DP103 - VALUE - humidity_value: 0..100 % (x1)                                  -> humidity sensor
  DP108 - VALUE - temp_correction: -9.0..9.0 C (x10) "Temperature Offset"         -> number (config)
  DP109 - VALUE - hum_calibration: -10..10 % (x1) "Humidity Offset"              -> number (config)
  DP112 - VALUE - hum_sensitivity: 1..10 % (x1) "Humidity Sensitivity" (deadband)-> number (config)
  DP113 - VALUE - temp_sensitivity: 0.1..1.0 C (x10) "Temperature Sensitivity"    -> number (config)
  DP115 - ENUM  - Sensor_Dect: none / tpm / mix / soil (device-detected probe)   -> sensor (ro diag)

Removed per user request (present in the thing-model but intentionally NOT exposed): DP101 work_mode
(device left on Manual — Auto can't drive the relay from ZHA anyway), DP7 countdown, DP104/105
humidity upper/lower limit, DP106/107 temperature upper/lower limit, DP116 temp_unit (device left on
Celsius), DP111 child_lock, DP123 alarm_enable, DP110 fault, DP121 tpm_alarm, DP122 hum_alarm1,
DP114 alarm code. The alarm/limit/auto DPs never emit in ZHA and their rules
live in the opaque DP119 (not reachable from ZHA). DP19 / DP119 are opaque blobs (not exposed).

Scaling notes: tuya_temperature/tuya_humidity convert ``measured_value = dp * scale`` into the
ZCL 0.01-unit convention, so DP102 (0.1 C) uses scale=10 and DP103 (whole %) uses scale=100.
tuya_number stores the raw DP value and the HA entity displays ``raw * multiplier`` (and writes
``raw = value / multiplier``), so multiplier=0.1 surfaces the x10 datapoints in real units while
min/max/step are given in displayed units.
"""

import zigpy.types as t
from zigpy.profiles import zha
from zigpy.quirks.v2 import EntityType
from zigpy.quirks.v2.homeassistant import EntityPlatform
from zigpy.quirks.v2.homeassistant.number import NumberDeviceClass
from zigpy.zcl.foundation import ZCLAttributeAccess
from zhaquirks.tuya.builder import TuyaQuirkBuilder

UNIT_C = "°C"
UNIT_PCT = "%"


class RelayStatus(t.enum8):
    """Power-on relay behaviour (DP14)."""

    Off = 0x00
    On = 0x01
    Memory = 0x02


class ProbeType(t.enum8):
    """Detected probe type (DP115)."""

    None_ = 0x00
    Temperature = 0x01  # tpm
    TempHumidity = 0x02  # mix
    Soil = 0x03


(
    TuyaQuirkBuilder("_TZ3218_7fiyo3kv", "TS000F")
    # ── Live readings ──────────────────────────────────────────────
    .tuya_temperature(dp_id=102, scale=10)
    .tuya_humidity(dp_id=103, scale=100)
    # ── Relay output — STANDARD ZCL OnOff (0x0006), NOT a Tuya DP ────
    # Sniffing the Tuya gateway (docs/21-TYZGTH1CH-D1RF-sniff-findings) proved the relay is
    # driven by plain ZCL OnOff On/Off on ep1 (gateway → device 0x212b: cmd On/Off, no payload,
    # no manufacturer code); the device confirms with OnOff attribute reports (on_off 0x0000).
    # Tuya DP1 over 0xEF00 is only a status echo — writing it is ACK-then-ignored, which is why
    # the earlier DP1-based switch never actuated the relay. So we keep the native OnOff cluster
    # untouched and only re-type EP1 from On/Off Light (0x0100) to On/Off Switch so ZHA exposes
    # the OnOff as a `switch` (not a `light`). No tuya_switch for DP1.
    .replaces_endpoint(endpoint_id=1, device_type=zha.DeviceType.ON_OFF_SWITCH)
    # ── Relay behaviour ────────────────────────────────────────────
    .tuya_enum(
        dp_id=14,
        attribute_name="relay_status",
        enum_class=RelayStatus,
        entity_type=EntityType.CONFIG,
        translation_key="relay_status",
        fallback_name="Power-on State",
    )
    # ── Temperature tuning (sensitivity/deadband + offset) ─────────
    .tuya_number(
        dp_id=113,
        type=t.uint16_t,
        attribute_name="temp_sensitivity",
        min_value=0.1,
        max_value=1.0,
        step=0.1,
        unit=UNIT_C,
        multiplier=0.1,
        entity_type=EntityType.CONFIG,
        translation_key="temp_sensitivity",
        fallback_name="Temperature Sensitivity",
    )
    .tuya_number(
        dp_id=108,
        type=t.int16s,
        attribute_name="temp_correction",
        min_value=-9.0,
        max_value=9.0,
        step=0.1,
        unit=UNIT_C,
        multiplier=0.1,
        device_class=NumberDeviceClass.TEMPERATURE,
        entity_type=EntityType.CONFIG,
        # keep a NON-standard translation_key so HA doesn't auto-localize the label (the UI is
        # Chinese); the English fallback_name is then shown as requested.
        translation_key="temp_correction",
        fallback_name="Temperature Offset",
    )
    # ── Humidity tuning (sensitivity/deadband + offset) ────────────
    .tuya_number(
        dp_id=112,
        type=t.uint16_t,
        attribute_name="hum_sensitivity",
        min_value=1,
        max_value=10,
        step=1,
        unit=UNIT_PCT,
        multiplier=1,
        entity_type=EntityType.CONFIG,
        translation_key="hum_sensitivity",
        fallback_name="Humidity Sensitivity",
    )
    .tuya_number(
        dp_id=109,
        type=t.int16s,
        attribute_name="hum_calibration",
        min_value=-10,
        max_value=10,
        step=1,
        unit=UNIT_PCT,
        multiplier=1,
        device_class=NumberDeviceClass.HUMIDITY,
        entity_type=EntityType.CONFIG,
        # keep a NON-standard translation_key (see Temperature Offset note above) so the English
        # fallback_name is shown rather than HA's localized "偏移量".
        translation_key="hum_calibration",
        fallback_name="Humidity Offset",
    )
    # ── Probe type — device-DETECTED value, read-only diagnostic sensor ──
    # The Tuya app offers no way to set this (DP115 "Sensor_Dect" = probe-type detection); the
    # device auto-detects the connected probe. So expose it as a read-only enum SENSOR (shows
    # None / Temperature / TempHumidity / Soil), not a writable select.
    .tuya_enum(
        dp_id=115,
        attribute_name="probe_type",
        enum_class=ProbeType,
        access=ZCLAttributeAccess.Read,
        entity_platform=EntityPlatform.SENSOR,
        entity_type=EntityType.DIAGNOSTIC,
        translation_key="probe_type",
        fallback_name="Probe Type",
    )
    # Suppress the redundant firmware/OTA update entity.
    .prevent_default_entity_creation(unique_id_suffix="firmware_update")
    # NOTE: intentionally NOT skip_configuration(). The relay is a REAL standard OnOff (0x0006)
    # cluster and the device supports OnOff attribute reporting (the first bare pairing bound it
    # and configured on_off report-on-change, max 900 s = SUCCESS). Skipping configuration left the
    # switch state optimistic-only, so it went stale whenever the relay changed by other means
    # (power-on default, physical button, Tuya-side). Letting ZHA bind + configure_reporting on
    # OnOff makes the device push relay-state changes so HA stays in sync. The quirk's Tuya
    # datapoint clusters are LocalDataCluster-based (bind() is a local no-op), so this only
    # (re)configures the real clusters; the DP sensors keep arriving via unsolicited 0xEF00 reports.
    .add_to_registry()
)
