"""ZHA Quirk for Simon SM0308C fan-coil thermostat (8-58E7101).

Device: _TZ2000_cykrrj2x / SM0308C, IEEE 0c:2a:6f:ff:fe:92:22:4e.
Standard ZCL (EP1: OnOff 0x0006, Thermostat 0x0201, Fan 0x0202) — NOT a Tuya
0xEF00 MCU device, so a plain QuirkBuilder.

Controllable functions (reverse-engineered live — see docs/8-58E7101-findings.html
and sniffer-related/HOP3-FINDINGS.md):
  - power            -> OnOff (0x0006)                    -> auto-created **switch**
  - temperature      -> Thermostat occupied_cooling_setpoint (whole °C, 15-35)
                        -> a **number**
  - fan speed        -> Fan fan_mode (passthrough to Tuya speed_set:
                        1=Low, 3=Medium, 5=High, 6=Auto) -> a **select**
  - operating mode   -> Thermostat system_mode (0x001C) with a DEVICE-CUSTOM enum
                        0=Cool, 1=Heat, 2=Fan (NOT ZCL-standard 3/4/7!) -> a **select**
  - sleep mode       -> Thermostat 0x9002 enum {0=Null, 1=Sleep}        -> a **select**

How mode/sleep were found: sniffed the Tuya gateway with an nRF52840, derived the
network key, decrypted the ZCL. The gateway sets both with a PLAIN ZCL Write
Attributes (no manufacturer code, ZCL FCF 0x10). Confirmed on ZHA: writing
system_mode 0/1/2 changes and holds the mode (the earlier "ACK-then-ignore" was
because the old probe wrote the ZCL-standard 3/4/7, which the device clamps to Auto).

For sleep, 0x9002 is added to the Thermostat cluster as a plain (non-manufacturer)
enum8 so ZHA writes it exactly the way the gateway does. (The device's periodic
0x900x *reports* are manufacturer-coded; we only need the *write* path here.)
Verified on ZHA 2026-06-26: Mode select drives 0x001C (read-back tracks 0/1/2,
holds 33 s+); Sleep select drives 0x9002 0/1 but ONLY when the AC is powered on
(an off unit ACK-then-ignores the sleep write — mode is accepted either way).

ZHA's default climate, setpoint-limit numbers, HVAC-action / setpoint-source
sensors, Identify button, OTA update and LQI/RSSI are suppressed.

NOTE: the device reports the setpoint in WHOLE °C (e.g. 24 = 24 °C), which violates
the ZCL 0.01 °C convention — but with no climate entity in play, a plain number
reads/writes that raw value directly, so no rescaling is needed.
"""

from typing import Final

import zigpy.types as t
from zigpy.quirks import CustomCluster
from zigpy.quirks.v2 import EntityType, QuirkBuilder
from zigpy.quirks.v2.homeassistant.number import NumberDeviceClass
from zigpy.quirks.v2.homeassistant.sensor import SensorDeviceClass, SensorStateClass
from zigpy.zcl import ClusterType
from zigpy.zcl.clusters.general import Time
from zigpy.zcl.clusters.hvac import Thermostat
from zigpy.zcl.foundation import ZCLAttributeDef

THERM = 0x0201
FAN = 0x0202
IDENTIFY = 0x0003
SLEEP_ATTR = 0x9002


class FanSpeed(t.enum8):
    """Fan speeds the device honours on the standard fan_mode (passthrough to the
    Tuya speed_set). Values are TRUE Tuya semantics (3 = mid, not ZCL "High").
    """

    low = 0x01
    medium = 0x03
    high = 0x05
    auto = 0x06


class ACMode(t.enum8):
    """Operating mode on the standard system_mode (0x001C). Device-custom enum
    (NOT the ZCL-standard cool=3/heat=4/fan_only=7 — those get clamped to Auto).
    Sniffed from the Tuya gateway; confirmed writable on ZHA.
    """

    Cool = 0x00
    Heat = 0x01
    Fan = 0x02


class SleepMode(t.enum8):
    """Sleep mode (Thermostat 0x9002). Sniffed from the Tuya gateway."""

    Null = 0x00
    Sleep = 0x01


class SM0308CThermostat(CustomCluster, Thermostat):
    """Thermostat with the device's sleep attribute (0x9002) added as a plain
    (non-manufacturer) enum8, so ZHA writes it with no manufacturer code — exactly
    as the Tuya gateway does (verified by sniffing). All standard Thermostat
    attributes (system_mode, occupied_cooling_setpoint, …) are inherited unchanged.
    """

    class AttributeDefs(Thermostat.AttributeDefs):
        sleep_mode: Final = ZCLAttributeDef(id=SLEEP_ATTR, type=SleepMode)


def _is_climate(e) -> bool:
    return getattr(e, "PLATFORM", "") == "climate"


def _is_button(e) -> bool:
    return getattr(e, "PLATFORM", "") == "button"


(
    QuirkBuilder("_TZ2000_cykrrj2x", "SM0308C")
    # ── CLOCK: standard ZCL Time cluster (0x000A) ──
    # The panel keeps an on-screen clock and syncs it the STANDARD Zigbee way: it
    # periodically reads the Time cluster (0x000A) attr time (0x0000) from the coordinator
    # (confirmed in the Tuya gateway sniff sm0308c_ch20.pcap: "dev->GW clu0x000a read
    # attr0x0000" → gateway answers). On its bare endpoint EP1 has no Time cluster, so ZHA
    # logs "Ignoring message on unknown cluster: 0x000a" (seen live for this device, nwk
    # 0x1229) and the clock never syncs. Add Time as a client/output cluster so zigpy's
    # built-in Time server auto-answers each read with the current UTC + local time (HA
    # container TZ Asia/Taipei → correct). Same fix as the SM0308F sibling.
    .adds(Time, cluster_type=ClusterType.Client)
    # ── Replace Thermostat with our subclass that adds the sleep attribute (0x9002) ──
    .replaces(SM0308CThermostat, endpoint_id=1)
    # ── Temperature setpoint as a Number (raw whole-°C, 15-35) ──
    .number(
        attribute_name="occupied_cooling_setpoint",
        cluster_id=THERM,
        endpoint_id=1,
        min_value=15,  # device's own temp_cold_cfg/temp_hot_cfg = 8975 → 15-35 °C
        max_value=35,
        step=1,
        unit="°C",
        device_class=NumberDeviceClass.TEMPERATURE,
        entity_type=EntityType.STANDARD,
        translation_key="ac_temperature",
        fallback_name="Temperature",
    )
    # ── Current temperature sensor (Thermostat local_temperature, 0.1 °C → ÷10) ──
    # Feeds the unified climate entity's current_temperature (see climate.py).
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
    # ── Operating mode select (system_mode 0x001C, custom enum 0/1/2) ──
    .enum(
        "system_mode",
        ACMode,
        THERM,
        endpoint_id=1,
        entity_type=EntityType.STANDARD,
        translation_key="ac_mode",
        fallback_name="Mode",
    )
    # ── Fan speed select (writable, passes through to the device's speed_set) ──
    .enum(
        "fan_mode",
        FanSpeed,
        FAN,
        endpoint_id=1,
        entity_type=EntityType.STANDARD,
        translation_key="fan_speed",
        fallback_name="Fan Speed",
    )
    # ── Sleep mode select (0x9002, {Null, Sleep}) ──
    .enum(
        "sleep_mode",
        SleepMode,
        THERM,
        endpoint_id=1,
        entity_type=EntityType.STANDARD,
        translation_key="ac_sleep",
        fallback_name="Sleep",
    )
    # ── Suppress everything else; keep {number, 3 selects, OnOff switch} ──
    # Native climate (primary thermostat entity)
    .prevent_default_entity_creation(endpoint_id=1, cluster_id=THERM, function=_is_climate)
    # NOTE: the Thermostat hvac_action + setpoint-change-source sensors are NO LONGER
    # suppressed here — a blanket sensor filter would also kill our local_temperature
    # current-temperature sensor. The climate platform (climate.py _hide_backing) hides
    # all ZHA entities on this device anyway, so those extra sensors stay hidden.
    # Thermostat setpoint-limit config numbers (distinct suffixes; not our Number)
    .prevent_default_entity_creation(endpoint_id=1, cluster_id=THERM, unique_id_suffix="min_heat_setpoint_limit")
    .prevent_default_entity_creation(endpoint_id=1, cluster_id=THERM, unique_id_suffix="max_heat_setpoint_limit")
    .prevent_default_entity_creation(endpoint_id=1, cluster_id=THERM, unique_id_suffix="min_cool_setpoint_limit")
    .prevent_default_entity_creation(endpoint_id=1, cluster_id=THERM, unique_id_suffix="max_cool_setpoint_limit")
    # Identify button
    .prevent_default_entity_creation(endpoint_id=1, cluster_id=IDENTIFY, function=_is_button)
    # OTA firmware update + LQI/RSSI diagnostics (match by suffix; output/device-level)
    .prevent_default_entity_creation(endpoint_id=1, unique_id_suffix="firmware_update")
    .prevent_default_entity_creation(endpoint_id=1, unique_id_suffix="lqi")
    .prevent_default_entity_creation(endpoint_id=1, unique_id_suffix="rssi")
    .add_to_registry()
)
