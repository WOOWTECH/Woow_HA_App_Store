"""ZHA quirk for Simon SM0308F multi-function climate panel (14-66E7109TY).

Device: _TZC200_qbuzgrdocufrqgdu / SM0308F, IEEE f0:82:c0:ff:fe:c9:19:22.

HYBRID device. EP1 carries BOTH standard ZCL clusters and a Tuya 0xEF00 MCU
cluster, so this uses TuyaQuirkBuilder (which only *replaces* 0xEF00 with the MCU
cluster and leaves the standard clusters intact).

CONTROL PATHS — important. On this firmware the standard ZCL clusters are mostly a
report/mirror veneer: a write into OnOff / Fan is ACK-then-IGNORED (the attribute
cache flips so HA looks like it worked, but the MCU never receives it and the real
AC does NOT change). Only the Tuya 0xEF00 datapoints write through to the MCU. The
ONE exception is the Thermostat cooling setpoint, whose WRITE the firmware *did* wire
through the standard Thermostat cluster. So:

  - power        -> Tuya DP 130 (ac_power_set)              -> switch   (DP write-through)
  - temperature  -> Thermostat occupied_cooling_setpoint    -> number   (std WRITE-through)
  - fan speed    -> Tuya DP 115 (speed_set)                 -> select   (DP write-through)
  - mode         -> Tuya DP 116 (mode_set)                  -> select   (DP write-through)
  - scenario     -> Tuya DP 152 (ac_scene_set)             -> select   (DP write-through)

SETPOINT REPORTS are the mirror-image of the write path and were the source of a bug:
a setpoint change made ON THE PHYSICAL PANEL is pushed *immediately* as Tuya DP 16
(temp_set, raw ×10) — NOT as a standard Thermostat report. The device does emit a
standard occupied_cooling_setpoint report too, but only slowly/periodically, so
without handling DP 16 the HA value stayed stale until the next active read/poll.
DP 16 is therefore mapped into occupied_cooling_setpoint (see .tuya_dp below) so
external changes ingest at once. (Verified live 2026-07-08: panel 26 °C ->
"set_data_response … dp=16 … value 260", previously "No datapoint handler for dp=16".)

Driving power via standard OnOff and fan via standard Fan.fan_mode did NOT actuate
the unit (user-confirmed) — that is why they moved to DP 130 / DP 115.

STATUS SENSORS (read-only). The standard ZCL attributes do NOT mirror the Tuya DPs on
this firmware (OnOff.on_off stays false, Fan.fan_mode stays stuck), so the power / fan /
mode / scenario sensors read the DP attributes directly — which only carry live state
because the custom MCU cluster below repairs this firmware's mis-directed DP reports.
The two temperature sensors read the standard Thermostat attributes (which the firmware
does keep in sync), while the setpoint's live push arrives via DP 16 (mapped into
occupied_cooling_setpoint above):

  - Power Status        <- DP 130 ac_power
  - Fan Speed Status    <- DP 115 ac_fan
  - Mode Status         <- DP 116 ac_mode
  - Scenario Status     <- DP 152 ac_scenario
  - Target Temperature  <- Thermostat.occupied_cooling_setpoint (÷10)
  - Current Temperature <- Thermostat.local_temperature (÷10)

REPORT-DIRECTION BUG. This firmware sends its DP reports with the wrong ZCL direction
bit, which the stock TuyaMCUCluster rejects (UNSUP_CLUSTER_COMMAND). SM0308FMCUCluster
(passed as replacement_cluster) flips the bit so reports ingest normally — this is
what lets the DP-backed entities reflect real device state (incl. external changes).

Reverse-engineered + functionally verified live on 192.168.2.6 (2026-06-23/24):
  * setpoint/local_temperature reported ×10 (raw 350 = 35.0 °C) -> multiplier 0.1 /
    divisor 10; the default climate entity (which misreads ×10 as 3.5 °C) is suppressed.
  * standard system_mode mirrors DP 116 as raw 1/2/3 (cool/heat/fan); the Mode Status
    sensor maps those back to text.
  * air-quality DPs (135/146/147/148) never report on this AC-only unit and were
    dropped (mappings kept commented below). Current temperature comes from the standard
    local_temperature attribute; DP 24 (temp_current) does report on this unit (seen live
    2026-07-08, raw 317 = 31.7 °C) but is left unmapped since local_temperature covers it.
"""

import zigpy.types as t
from zigpy.quirks.v2 import EntityType
from zigpy.quirks.v2.homeassistant.binary_sensor import BinarySensorDeviceClass
from zigpy.quirks.v2.homeassistant.number import NumberDeviceClass
from zigpy.quirks.v2.homeassistant.sensor import SensorDeviceClass, SensorStateClass
from zigpy.zcl import ClusterType, foundation
from zigpy.zcl.clusters.general import Time
from zigpy.zcl.clusters.hvac import Thermostat
from zhaquirks.tuya import (
    TUYA_ACTIVE_STATUS_RPT,
    TUYA_GET_DATA,
    TUYA_SET_DATA_RESPONSE,
)
from zhaquirks.tuya.builder import TuyaQuirkBuilder
from zhaquirks.tuya.mcu import TuyaMCUCluster

ONOFF = 0x0006
THERM = 0x0201
TUYA = 0xEF00
IDENTIFY = 0x0003

# Tuya commands the MCU uses to *report* datapoint values back to the coordinator.
_TUYA_REPORT_CMDS = (TUYA_GET_DATA, TUYA_SET_DATA_RESPONSE, TUYA_ACTIVE_STATUS_RPT)


class SM0308FMCUCluster(TuyaMCUCluster):
    """MCU cluster tolerant of this firmware's mis-directed DP reports.

    The SM0308F sends its datapoint reports (get_data 0x01 / set_data_response 0x02 /
    active_status_report 0x06) with the WRONG ZCL direction bit — Client_to_Server
    instead of Server_to_Client. The stock dispatch then looks the command up in
    server_commands (where it doesn't exist), logs "unknown manufacturer command" and
    replies UNSUP_CLUSTER_COMMAND, so the DP values are never ingested (the control
    entities stay optimistic and the DP-backed status sensors never update).

    Fix: at deserialize time, flip the direction bit on those report commands so the
    stock machinery decodes and routes them through the normal report path
    (handle_get_data -> _dp_2_attr_update). Outgoing frames and correctly-directed
    frames are untouched.
    """

    def deserialize(self, data: bytes):
        # Flip the wrong direction bit so the report payload DECODES (the stock
        # deserializer picks the command schema by direction; without this the body
        # arrives as raw bytes).
        hdr, rest = foundation.ZCLHeader.deserialize(data)
        if (
            hdr.frame_control.frame_type == foundation.FrameType.CLUSTER_COMMAND
            and hdr.direction != foundation.Direction.Server_to_Client
            and hdr.command_id in _TUYA_REPORT_CMDS
        ):
            hdr.frame_control = hdr.frame_control.replace(
                direction=foundation.Direction.Server_to_Client
            )
            data = hdr.serialize() + rest
        return super().deserialize(data)

    def handle_cluster_request(self, hdr, args, *, dst_addressing=None):
        # Route the report commands to their report handler by command-id, regardless
        # of the direction bit (the stock dispatch keys off hdr.direction, which this
        # firmware sets wrong — sending reports as Client_to_Server).
        if hdr.command_id in _TUYA_REPORT_CMDS:
            try:
                cmd_def = self.client_commands[hdr.command_id]
                status = getattr(self, f"handle_{cmd_def.name}")(*args)
            except (KeyError, AttributeError) as exc:
                self.debug("SM0308F report handler failed: %s", exc)
                status = foundation.Status.UNSUP_CLUSTER_COMMAND
            if not hdr.frame_control.disable_default_response:
                self.send_default_rsp(hdr, status=status)
            return
        return super().handle_cluster_request(hdr, args, dst_addressing=dst_addressing)


class ACMode(t.enum8):
    """AC mode via Tuya DP 116 (full device range is 0-9; expose the 3 wanted)."""

    cool = 1
    heat = 2
    fan_only = 3


class FanSpeed(t.enum8):
    """Fan speed via Tuya DP 115 speed_set (1=Auto, 3=Low, 5=Med, 7=High …)."""

    low = 3
    medium = 5
    high = 7
    auto = 1


class Scenario(t.enum8):
    """AC scenario via Tuya DP 152 (0=none/standard, 1=sleep, 2=energy-saving)."""

    standard = 0
    sleep = 1


# ── status-sensor value converters (raw cached DP value -> human text) ──
_MODE_TEXT = {1: "cool", 2: "heat", 3: "fan_only"}  # DP 116 mode_set
_FAN_TEXT = {  # DP 115 speed_set
    1: "auto", 2: "super_low", 3: "low", 4: "low_medium",
    5: "medium", 6: "medium_high", 7: "high", 8: "super_high",
}
_SCEN_TEXT = {0: "standard", 1: "sleep", 2: "energy_saving"}  # DP 152 ac_scene_set


def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _mode_status(v):
    i = _to_int(v)
    return None if i is None else _MODE_TEXT.get(i, f"mode_{i}")


def _fan_status(v):
    i = _to_int(v)
    return None if i is None else _FAN_TEXT.get(i, f"speed_{i}")


def _scenario_status(v):
    i = _to_int(v)
    return None if i is None else _SCEN_TEXT.get(i, f"scene_{i}")


def _is_climate(e) -> bool:
    return getattr(e, "PLATFORM", "") == "climate"


def _is_switch(e) -> bool:
    return getattr(e, "PLATFORM", "") == "switch"


def _is_button(e) -> bool:
    return getattr(e, "PLATFORM", "") == "button"


(
    TuyaQuirkBuilder("_TZC200_qbuzgrdocufrqgdu", "SM0308F")
    # ══════════════════════ CLOCK ══════════════════════
    # The panel keeps an on-screen clock and syncs it the STANDARD ZCL way: it
    # periodically reads the Time cluster (0x000A) attributes time (0x0000) and
    # local_time (0x0007) from the coordinator (verified live on ZHA + in the Tuya
    # gateway sniff: "dev->GW clu0x000a read attr0x0000 / attr0x0007" → gateway answers).
    # This device does NOT use the Tuya 0xEF00 set_time (0x24) datapoint at all. On its
    # bare endpoint EP1 has no Time cluster, so ZHA logs "Ignoring message on unknown
    # cluster: 0x000a" and the clock never syncs. Add Time as a client/output cluster so
    # zigpy's built-in Time server (handle_read_attribute_time / _local_time) auto-answers
    # each read with the current UTC + local time (HA container TZ Asia/Taipei → correct).
    .adds(Time, cluster_type=ClusterType.Client)
    # ══════════════════════ CONTROLS ══════════════════════
    # Power → Tuya DP 130 (standard OnOff is ACK-then-ignore on this firmware)
    .tuya_switch(
        dp_id=130,
        attribute_name="ac_power",
        entity_type=EntityType.STANDARD,
        translation_key="ac_power",
        fallback_name="Power",
    )
    # Temperature setpoint → standard Thermostat (write-through here), ×10 → 0.1
    .number(
        attribute_name="occupied_cooling_setpoint",
        cluster_id=THERM,
        endpoint_id=1,
        min_value=15,
        max_value=35,
        step=1,
        unit="°C",
        multiplier=0.1,
        device_class=NumberDeviceClass.TEMPERATURE,
        entity_type=EntityType.STANDARD,
        translation_key="ac_temperature",
        fallback_name="Temperature",
    )
    # Setpoint REPORTS: a change made on the physical panel is pushed immediately over
    # Tuya DP 16 (temp_set, raw ×10), NOT as a standard Thermostat report — verified live
    # (log: "set_data_response … dp=16 … value 260" → previously dropped with "No datapoint
    # handler for dp=16"). Route DP 16 into the standard occupied_cooling_setpoint attribute
    # so the change ingests at once and the Temperature number / Target Temperature sensor /
    # climate entity all update. Report-only (no dp_converter): HA→device writes still go
    # through the standard-Thermostat write-through path above. DP raw already matches the
    # attribute's ×10 form (260 → 26.0 °C via the number's multiplier 0.1), so no converter.
    .tuya_dp(
        dp_id=16,
        ep_attribute=Thermostat.ep_attribute,
        attribute_name=Thermostat.AttributeDefs.occupied_cooling_setpoint.name,
    )
    # Fan speed → Tuya DP 115 (standard Fan.fan_mode is ACK-then-ignore)
    .tuya_enum(
        dp_id=115,
        attribute_name="ac_fan",
        enum_class=FanSpeed,
        entity_type=EntityType.STANDARD,
        translation_key="fan_speed",
        fallback_name="Fan Speed",
    )
    # Mode → Tuya DP 116
    .tuya_enum(
        dp_id=116,
        attribute_name="ac_mode",
        enum_class=ACMode,
        entity_type=EntityType.STANDARD,
        translation_key="ac_mode",
        fallback_name="Mode",
    )
    # Scenario → Tuya DP 152
    .tuya_enum(
        dp_id=152,
        attribute_name="ac_scenario",
        enum_class=Scenario,
        entity_type=EntityType.STANDARD,
        translation_key="ac_scenario",
        fallback_name="Scenario",
    )
    # ══════════════════════ STATUS SENSORS (read-only) ══════════════════════
    # Power on/off status from the DP-130 attribute. (The standard OnOff.on_off is
    # NOT mirrored by this firmware — it stays false — so power state lives only in
    # DP 130, which the custom MCU cluster above now ingests from device reports.)
    .binary_sensor(
        attribute_name="ac_power",
        cluster_id=TUYA,
        endpoint_id=1,
        device_class=BinarySensorDeviceClass.POWER,
        entity_type=EntityType.STANDARD,
        unique_id_suffix="power_status",
        translation_key="power_status",
        fallback_name="Power Status",
    )
    # Fan speed status from the DP-115 attribute. (Standard Fan.fan_mode is NOT
    # mirrored — it stays stuck — so the real fan state lives only in DP 115.)
    .sensor(
        attribute_name="ac_fan",
        cluster_id=TUYA,
        endpoint_id=1,
        attribute_converter=_fan_status,
        entity_type=EntityType.STANDARD,
        unique_id_suffix="fan_speed_status",
        translation_key="fan_speed_status",
        fallback_name="Fan Speed Status",
    )
    # Mode status from the DP-116 attribute. (Standard Thermostat.system_mode is not
    # a reliable mirror of DP 116 on this firmware.)
    .sensor(
        attribute_name="ac_mode",
        cluster_id=TUYA,
        endpoint_id=1,
        attribute_converter=_mode_status,
        entity_type=EntityType.STANDARD,
        unique_id_suffix="mode_status",
        translation_key="mode_status",
        fallback_name="Mode Status",
    )
    # Target temperature status from the reported standard setpoint (÷10)
    .sensor(
        attribute_name="occupied_cooling_setpoint",
        cluster_id=THERM,
        endpoint_id=1,
        divisor=10,
        unit="°C",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_type=EntityType.STANDARD,
        unique_id_suffix="target_temperature",
        translation_key="target_temperature",
        fallback_name="Target Temperature",
    )
    # Scenario status from the DP 152 attribute (no standard mirror; reflects the
    # last HA-set value — the MCU does not spontaneously report DP 152)
    .sensor(
        attribute_name="ac_scenario",
        cluster_id=TUYA,
        endpoint_id=1,
        attribute_converter=_scenario_status,
        entity_type=EntityType.STANDARD,
        unique_id_suffix="scenario_status",
        translation_key="scenario_status",
        fallback_name="Scenario Status",
    )
    # Current temperature from the STANDARD Thermostat local_temperature (×10 → ÷10)
    .sensor(
        attribute_name="local_temperature",
        cluster_id=THERM,
        endpoint_id=1,
        divisor=10,
        unit="°C",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_type=EntityType.STANDARD,
        translation_key="current_temperature",
        fallback_name="Current Temperature",
    )
    # NOTE: this panel's connected configuration is AC-only — it does NOT report
    # the optional Tuya air-quality DPs (135 humidity / 146 PM2.5 / 147 HCHO /
    # 148 CO₂) nor heating/ventilation DPs (confirmed live: they never report). The
    # mappings are documented here so they can be re-enabled for a unit that has
    # those sensors wired:
    #   .tuya_sensor(dp_id=135, "humidity",  uint16, divisor=10, unit="%",  HUMIDITY)
    #   .tuya_sensor(dp_id=146, "pm25",      uint16, divisor=10, unit="µg/m³", PM25)
    #   .tuya_sensor(dp_id=147, "hcho",      uint16, unit="µg/m³")
    #   .tuya_sensor(dp_id=148, "co2",       uint16, unit="ppm", CO2)
    # ══════════════════════ SUPPRESS ══════════════════════
    # Dead standard OnOff switch (replaced by the DP-130 switch above)
    .prevent_default_entity_creation(endpoint_id=1, cluster_id=ONOFF, function=_is_switch)
    # Default climate (misreads ×10 setpoint) + thermostat default sensors (by suffix,
    # so our explicit Thermostat sensors survive) + identify / OTA / lqi / rssi
    .prevent_default_entity_creation(endpoint_id=1, cluster_id=THERM, function=_is_climate)
    .prevent_default_entity_creation(endpoint_id=1, cluster_id=THERM, unique_id_suffix="hvac_action")
    .prevent_default_entity_creation(endpoint_id=1, cluster_id=THERM, unique_id_suffix="setpoint_change_source_timestamp")
    .prevent_default_entity_creation(endpoint_id=1, cluster_id=THERM, unique_id_suffix="pi_heating_demand")
    .prevent_default_entity_creation(endpoint_id=1, cluster_id=THERM, unique_id_suffix="min_heat_setpoint_limit")
    .prevent_default_entity_creation(endpoint_id=1, cluster_id=THERM, unique_id_suffix="max_heat_setpoint_limit")
    .prevent_default_entity_creation(endpoint_id=1, cluster_id=THERM, unique_id_suffix="min_cool_setpoint_limit")
    .prevent_default_entity_creation(endpoint_id=1, cluster_id=THERM, unique_id_suffix="max_cool_setpoint_limit")
    .prevent_default_entity_creation(endpoint_id=1, cluster_id=IDENTIFY, function=_is_button)
    .prevent_default_entity_creation(endpoint_id=1, unique_id_suffix="firmware_update")
    .prevent_default_entity_creation(endpoint_id=1, unique_id_suffix="lqi")
    .prevent_default_entity_creation(endpoint_id=1, unique_id_suffix="rssi")
    # NOTE: do NOT skip_configuration — the standard clusters support binding+reporting,
    # which is what keeps the standard-attr status sensors (fan_mode / system_mode /
    # setpoint / local_temperature) populated with live device-reported values.
    .add_to_registry(replacement_cluster=SM0308FMCUCluster)
)
