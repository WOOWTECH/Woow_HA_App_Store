"""Constants for the Atmocube integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    CONCENTRATION_PARTS_PER_BILLION,
    CONCENTRATION_PARTS_PER_MILLION,
    LIGHT_LUX,
    PERCENTAGE,
    UnitOfPressure,
    UnitOfSoundPressure,
    UnitOfTemperature,
)

DOMAIN = "atmocube"

DEFAULT_PORT = 502
DEFAULT_SLAVE_ID = 1
DEFAULT_SCAN_INTERVAL = 30  # seconds

REGISTER_START = 64
REGISTER_COUNT = 20

CONF_SLAVE_ID = "slave_id"


@dataclass(frozen=True)
class AtmocubeSensorDefinition:
    """Definition of an Atmocube sensor register."""

    key: str
    name: str
    register_offset: int
    unit: str | None
    scale: float = 1.0
    precision: int = 0
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    is_signed: bool = False
    icon: str | None = None


SENSOR_DEFINITIONS: tuple[AtmocubeSensorDefinition, ...] = (
    AtmocubeSensorDefinition(
        key="tvocs",
        name="總揮發性有機化合物 TVOCs",
        register_offset=0,
        unit=CONCENTRATION_PARTS_PER_BILLION,
        device_class=SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS_PARTS,
    ),
    AtmocubeSensorDefinition(
        key="pm1_0",
        name="懸浮微粒 PM 1.0",
        register_offset=1,
        unit="µg/m³",
        scale=0.1,
        precision=1,
        device_class=SensorDeviceClass.PM1,
    ),
    AtmocubeSensorDefinition(
        key="pm2_5",
        name="懸浮微粒 PM 2.5",
        register_offset=2,
        unit="µg/m³",
        scale=0.1,
        precision=1,
        device_class=SensorDeviceClass.PM25,
    ),
    AtmocubeSensorDefinition(
        key="pm4",
        name="懸浮微粒 PM 4",
        register_offset=3,
        unit="µg/m³",
        scale=0.1,
        precision=1,
        icon="mdi:blur",
    ),
    AtmocubeSensorDefinition(
        key="pm10",
        name="懸浮微粒 PM 10",
        register_offset=4,
        unit="µg/m³",
        scale=0.1,
        precision=1,
        device_class=SensorDeviceClass.PM10,
    ),
    AtmocubeSensorDefinition(
        key="co2",
        name="二氧化碳 CO2",
        register_offset=5,
        unit=CONCENTRATION_PARTS_PER_MILLION,
        device_class=SensorDeviceClass.CO2,
    ),
    AtmocubeSensorDefinition(
        key="temperature",
        name="溫度 Temperature",
        register_offset=6,
        unit=UnitOfTemperature.CELSIUS,
        scale=0.01,
        precision=2,
        device_class=SensorDeviceClass.TEMPERATURE,
        is_signed=True,
    ),
    AtmocubeSensorDefinition(
        key="humidity",
        name="相對濕度 Humidity",
        register_offset=7,
        unit=PERCENTAGE,
        scale=0.01,
        precision=1,
        device_class=SensorDeviceClass.HUMIDITY,
    ),
    AtmocubeSensorDefinition(
        key="abs_humidity",
        name="絕對濕度 Absolute Humidity",
        register_offset=8,
        unit="g/m³",
        icon="mdi:water",
    ),
    AtmocubeSensorDefinition(
        key="pressure",
        name="氣壓 Pressure",
        register_offset=9,
        unit=UnitOfPressure.HPA,
        scale=0.1,
        precision=1,
        device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE,
    ),
    AtmocubeSensorDefinition(
        key="noise",
        name="噪音 Noise",
        register_offset=10,
        unit=UnitOfSoundPressure.DECIBEL,
        device_class=SensorDeviceClass.SOUND_PRESSURE,
    ),
    AtmocubeSensorDefinition(
        key="light",
        name="光照度 Light",
        register_offset=11,
        unit=LIGHT_LUX,
        device_class=SensorDeviceClass.ILLUMINANCE,
    ),
    AtmocubeSensorDefinition(
        key="no2",
        name="二氧化氮 NO2",
        register_offset=12,
        unit=CONCENTRATION_PARTS_PER_BILLION,
        icon="mdi:smog",
    ),
    AtmocubeSensorDefinition(
        key="co",
        name="一氧化碳 CO",
        register_offset=13,
        unit=CONCENTRATION_PARTS_PER_BILLION,
        icon="mdi:molecule-co",
    ),
    AtmocubeSensorDefinition(
        key="o3",
        name="臭氧 O3",
        register_offset=14,
        unit=CONCENTRATION_PARTS_PER_BILLION,
        icon="mdi:weather-sunny-alert",
    ),
    AtmocubeSensorDefinition(
        key="formaldehyde",
        name="甲醛 Formaldehyde",
        register_offset=15,
        unit=CONCENTRATION_PARTS_PER_BILLION,
        icon="mdi:chemical-weapon",
    ),
    AtmocubeSensorDefinition(
        key="color_temp",
        name="色溫 Color Temperature",
        register_offset=16,
        unit="K",
        icon="mdi:temperature-kelvin",
    ),
    AtmocubeSensorDefinition(
        key="people_index",
        name="人員舒適指數 People Index",
        register_offset=17,
        unit=None,
        icon="mdi:account-group",
    ),
    AtmocubeSensorDefinition(
        key="voc_index",
        name="VOC 指數 VOC Index",
        register_offset=18,
        unit=None,
        icon="mdi:air-filter",
    ),
    AtmocubeSensorDefinition(
        key="nox_index",
        name="NOx 指數 NOx Index",
        register_offset=19,
        unit=None,
        icon="mdi:smog",
    ),
)
