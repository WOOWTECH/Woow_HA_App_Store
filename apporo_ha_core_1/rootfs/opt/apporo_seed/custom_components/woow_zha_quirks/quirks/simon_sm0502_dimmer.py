"""ZHA Quirk for Simon SM0502 Dual-Gang Dimmer Switch.

Device info:
  - Model:        SM0502
  - Manufacturer: _TZ2000_qc1ntn3c
  - Chip:         Silicon Labs EFR32MG24
  - Firmware:     0x00000087
  - IEEE:         7c:c6:b6:ff:fe:82:6c:cf

This is a standard ZCL dimmer (NOT Tuya MCU / TS0601).
The device exposes 4 endpoints (device_type=DIMMABLE_LIGHT 0x0101),
but only endpoints 1 & 2 are real physical gangs.
Endpoints 3 & 4 are phantom/virtual and must be removed.

Each real endpoint has:
  - OnOff        (0x0006)  on/off control
  - LevelControl (0x0008)  brightness (0-254)

Tuya manufacturer-specific LevelControl attributes:
  - 0xFC00 (uint16) — packed min/max brightness
      high byte = min brightness (0x00-0xFF)
      low byte  = max brightness (0x00-0xFF)
      default 0x01FF → min=1, max=255
  - 0xFC01 (uint8)  — dimming mode / curve type

Virtual attributes (split from 0xFC00 for user-friendly control):
  - 0xFC10 — min brightness, HA-facing as percent (0-100), high byte of 0xFC00
  - 0xFC11 — max brightness, HA-facing as percent (0-100), low byte of 0xFC00
    (raw byte 0-255 is converted to/from percent in SimonLevelControlCluster)

Quirk adds:
  1. Remove phantom endpoints 3 & 4
  2. TuyaZBOnOffAttributeCluster on EP1 & EP2 for backlight_mode
  3. AllOnOff virtual cluster on EP200 for all-on/all-off
  4. Suppress useless default LevelControl entities
  5. Separate min / max brightness controls via 0xFC00 byte splitting
  6. Dimming mode enum via 0xFC01
"""

import logging
from typing import Final

import zigpy.types as t
from zigpy.quirks.v2 import EntityType, QuirkBuilder
from zigpy.zcl import foundation
from zigpy.zcl.clusters.general import LevelControl, OnOff
from zigpy.zcl.foundation import ZCLAttributeDef

from zhaquirks import LocalDataCluster
from zhaquirks.tuya import (
    NoManufacturerCluster,
    TuyaZBOnOffAttributeCluster,
)

_LOGGER = logging.getLogger(__name__)

ONOFF = TuyaZBOnOffAttributeCluster.cluster_id  # 0x0006
LEVEL = LevelControl.cluster_id  # 0x0008
ALL_ONOFF_EP = 200  # virtual endpoint for All On/Off

# Tuya private LevelControl attribute IDs
TUYA_LEVEL_MIN_MAX = 0xFC00  # packed: high=min, low=max
TUYA_DIMMING_MODE = 0xFC01

# Virtual attribute IDs for split min/max (not real ZCL attrs)
VIRTUAL_MIN_BRIGHTNESS = 0xFC10
VIRTUAL_MAX_BRIGHTNESS = 0xFC11


def _raw_to_pct(raw: int) -> int:
    """Device byte (0-255) → percent (0-100)."""
    return round(raw * 100 / 255)


def _pct_to_raw(pct: int) -> int:
    """Percent (0-100) → device byte (0-255)."""
    return round(pct * 255 / 100)


class SimonBacklightMode(t.enum8):
    """Backlight/indicator mode — labels match the Tuya app for this device.

    ZHA renders an enum entity's state from the member name (underscores
    shown as spaces), so these display as "Switch Status" / "Close" /
    "Switch Position". Integer values match the device attribute.
    """

    Switch_Status = 0x00
    Close = 0x01
    Switch_Position = 0x02


class TuyaDimmingMode(t.enum8):
    """Tuya dimming mode / curve type."""

    Mode_0 = 0x00
    Mode_1 = 0x01
    Mode_2 = 0x02
    Mode_3 = 0x03
    Mode_4 = 0x04
    Mode_5 = 0x05
    Mode_6 = 0x06
    Mode_7 = 0x07


class SimonLevelControlCluster(NoManufacturerCluster, LevelControl):
    """LevelControl with split min/max brightness from packed 0xFC00.

    The device stores min and max brightness in a single uint16 (0xFC00):
        high byte = min brightness (0-255)
        low byte  = max brightness (0-255)
    Example: 0x4DFF → min=77(~30%), max=255(100%)

    This cluster exposes two virtual attributes (0xFC10, 0xFC11) as
    separate number entities, scaled to percent (0-100) for the HA UI.
    Reads convert the raw byte → percent; writes convert percent → raw
    byte and read-modify-write the underlying 0xFC00. (255 raw levels map
    to 100 %, so values may round-trip ±1 %.)
    """

    class AttributeDefs(LevelControl.AttributeDefs):
        """Extended attributes with Tuya min/max and virtual split."""

        tuya_min_max_brightness: Final = ZCLAttributeDef(
            id=TUYA_LEVEL_MIN_MAX, type=t.uint16_t
        )
        tuya_dimming_mode: Final = ZCLAttributeDef(
            id=TUYA_DIMMING_MODE, type=TuyaDimmingMode
        )
        min_brightness: Final = ZCLAttributeDef(
            id=VIRTUAL_MIN_BRIGHTNESS, type=t.uint8_t
        )
        max_brightness: Final = ZCLAttributeDef(
            id=VIRTUAL_MAX_BRIGHTNESS, type=t.uint8_t
        )

    def get(self, key, default=None):
        """Override get to compute virtual attrs (as percent) from cached 0xFC00."""
        if key in (VIRTUAL_MIN_BRIGHTNESS, VIRTUAL_MAX_BRIGHTNESS):
            val = super().get(key)
            if val is None:
                packed = super().get(TUYA_LEVEL_MIN_MAX)
                if packed is not None and isinstance(packed, int):
                    super()._update_attribute(
                        VIRTUAL_MIN_BRIGHTNESS, _raw_to_pct((packed >> 8) & 0xFF)
                    )
                    super()._update_attribute(
                        VIRTUAL_MAX_BRIGHTNESS, _raw_to_pct(packed & 0xFF)
                    )
                    return super().get(key, default)
            return val if val is not None else default
        return super().get(key, default)

    async def write_attributes(self, attributes, manufacturer=None, **kwargs):
        """Intercept writes to virtual min/max and redirect to 0xFC00."""
        real_attrs = {}
        min_write = None
        max_write = None

        for attr, value in attributes.items():
            attr_id = attr if isinstance(attr, int) else getattr(
                self.AttributeDefs, attr, None
            )
            if attr_id is not None and not isinstance(attr_id, int):
                attr_id = attr_id.id

            if attr_id == VIRTUAL_MIN_BRIGHTNESS:
                min_write = _pct_to_raw(int(value))  # percent → raw byte
            elif attr_id == VIRTUAL_MAX_BRIGHTNESS:
                max_write = _pct_to_raw(int(value))  # percent → raw byte
            else:
                real_attrs[attr] = value

        if min_write is not None or max_write is not None:
            current = self.get(TUYA_LEVEL_MIN_MAX, 0x01FF)
            cur_min = (current >> 8) & 0xFF
            cur_max = current & 0xFF
            new_min = min_write if min_write is not None else cur_min
            new_max = max_write if max_write is not None else cur_max
            packed = (new_min << 8) | new_max
            real_attrs[self.AttributeDefs.tuya_min_max_brightness.name] = packed

        if real_attrs:
            return await super().write_attributes(real_attrs, manufacturer, **kwargs)
        return [[], []]

    def _update_attribute(self, attrid, value):
        """When 0xFC00 is updated, split into virtual min/max attributes."""
        super()._update_attribute(attrid, value)

        if attrid == TUYA_LEVEL_MIN_MAX and isinstance(value, int):
            min_val = (value >> 8) & 0xFF
            max_val = value & 0xFF
            min_pct = _raw_to_pct(min_val)
            max_pct = _raw_to_pct(max_val)
            _LOGGER.debug(
                "SM0502 EP%d 0xFC00=0x%04X → min=%d (%d%%), max=%d (%d%%)",
                self.endpoint.endpoint_id, value,
                min_val, min_pct, max_val, max_pct,
            )
            super()._update_attribute(VIRTUAL_MIN_BRIGHTNESS, min_pct)
            super()._update_attribute(VIRTUAL_MAX_BRIGHTNESS, max_pct)


class AllOnOffCluster(LocalDataCluster, OnOff):
    """Virtual OnOff cluster that controls all real dimmer endpoints.

    Placed on virtual endpoint 200. Intercepts on/off commands and
    fans them out to endpoints 1 and 2.
    """

    cluster_id = OnOff.cluster_id  # 0x0006

    async def command(
        self,
        command_id: foundation.GeneralCommand | int,
        *args,
        manufacturer=None,
        expect_reply: bool = True,
        **kwargs,
    ):
        """Intercept on/off/toggle and send to all real endpoints."""
        if command_id not in (0x00, 0x01, 0x02):
            return foundation.GENERAL_COMMANDS[
                foundation.GeneralCommand.Default_Response
            ].schema(command_id=command_id, status=foundation.Status.SUCCESS)

        for ep_id, ep in sorted(self.endpoint.device.endpoints.items()):
            if ep_id in (0, ALL_ONOFF_EP, 242):
                continue
            onoff = ep.in_clusters.get(OnOff.cluster_id)
            if onoff is None:
                continue
            try:
                await onoff.command(command_id)
                _LOGGER.debug(
                    "AllOnOff EP%d cmd=0x%02x OK", ep_id, command_id,
                )
            except Exception:
                _LOGGER.warning(
                    "AllOnOff EP%d cmd=0x%02x failed",
                    ep_id, command_id, exc_info=True,
                )

        if command_id == 0x01:
            self._update_attribute(OnOff.AttributeDefs.on_off.id, True)
        elif command_id == 0x00:
            self._update_attribute(OnOff.AttributeDefs.on_off.id, False)

        return foundation.GENERAL_COMMANDS[
            foundation.GeneralCommand.Default_Response
        ].schema(command_id=command_id, status=foundation.Status.SUCCESS)


# ────────────────────────────────────────────────────────────────
# SM0502 — 2-gang dimmer (_TZ2000_qc1ntn3c)
# ────────────────────────────────────────────────────────────────
(
    QuirkBuilder("_TZ2000_qc1ntn3c", "SM0502")
    # ── EP1: Gang 1 dimmer ──
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=1)
    .replaces(SimonLevelControlCluster, endpoint_id=1)
    # ── EP2: Gang 2 dimmer ──
    .replaces(TuyaZBOnOffAttributeCluster, endpoint_id=2)
    .replaces(SimonLevelControlCluster, endpoint_id=2)
    # ── Remove phantom endpoints 3 & 4 ──
    .removes_endpoint(endpoint_id=3)
    .removes_endpoint(endpoint_id=4)
    # ── Suppress OnOff StartUpOnOff selects ("啟動時的通電行為") on both gangs ──
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=ONOFF,
        unique_id_suffix="StartUpOnOff",
    )
    .prevent_default_entity_creation(
        endpoint_id=2, cluster_id=ONOFF,
        unique_id_suffix="StartUpOnOff",
    )
    # ── Suppress useless default LevelControl entities (EP1) ──
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=LEVEL,
        unique_id_suffix="on_off_transition_time",
    )
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=LEVEL,
        unique_id_suffix="on_level",
    )
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=LEVEL,
        unique_id_suffix="default_move_rate",
    )
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=LEVEL,
        unique_id_suffix="start_up_current_level",
    )
    # ── Suppress useless default LevelControl entities (EP2) ──
    .prevent_default_entity_creation(
        endpoint_id=2, cluster_id=LEVEL,
        unique_id_suffix="on_off_transition_time",
    )
    .prevent_default_entity_creation(
        endpoint_id=2, cluster_id=LEVEL,
        unique_id_suffix="on_level",
    )
    .prevent_default_entity_creation(
        endpoint_id=2, cluster_id=LEVEL,
        unique_id_suffix="default_move_rate",
    )
    .prevent_default_entity_creation(
        endpoint_id=2, cluster_id=LEVEL,
        unique_id_suffix="start_up_current_level",
    )
    # ── Suppress raw 0xFC00 auto-entity (we use virtual split instead) ──
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=LEVEL,
        unique_id_suffix="tuya_min_max_brightness",
    )
    .prevent_default_entity_creation(
        endpoint_id=2, cluster_id=LEVEL,
        unique_id_suffix="tuya_min_max_brightness",
    )
    # ── Indicator LED mode (config entity on EP1) ──
    .enum(
        TuyaZBOnOffAttributeCluster.AttributeDefs.backlight_mode.name,
        SimonBacklightMode,
        ONOFF,
        endpoint_id=1,
        entity_type=EntityType.CONFIG,
        translation_key="backlight_mode",
        fallback_name="Indicator Mode",
    )
    # ── Min brightness per gang (virtual 0xFC10 → high byte of 0xFC00, shown as %) ──
    .number(
        SimonLevelControlCluster.AttributeDefs.min_brightness.name,
        LEVEL,
        endpoint_id=1,
        min_value=0,
        max_value=100,
        step=1,
        unit="%",
        entity_type=EntityType.CONFIG,
        translation_key="min_brightness_1",
        fallback_name="Min Brightness 1",
    )
    .number(
        SimonLevelControlCluster.AttributeDefs.min_brightness.name,
        LEVEL,
        endpoint_id=2,
        min_value=0,
        max_value=100,
        step=1,
        unit="%",
        entity_type=EntityType.CONFIG,
        translation_key="min_brightness_2",
        fallback_name="Min Brightness 2",
    )
    # ── Max brightness per gang (virtual 0xFC11 → low byte of 0xFC00, shown as %) ──
    .number(
        SimonLevelControlCluster.AttributeDefs.max_brightness.name,
        LEVEL,
        endpoint_id=1,
        min_value=0,
        max_value=100,
        step=1,
        unit="%",
        entity_type=EntityType.CONFIG,
        translation_key="max_brightness_1",
        fallback_name="Max Brightness 1",
    )
    .number(
        SimonLevelControlCluster.AttributeDefs.max_brightness.name,
        LEVEL,
        endpoint_id=2,
        min_value=0,
        max_value=100,
        step=1,
        unit="%",
        entity_type=EntityType.CONFIG,
        translation_key="max_brightness_2",
        fallback_name="Max Brightness 2",
    )
    # ── Suppress dimming mode (0xFC01 is read-only on this device) ──
    .prevent_default_entity_creation(
        endpoint_id=1, cluster_id=LEVEL,
        unique_id_suffix="tuya_dimming_mode",
    )
    .prevent_default_entity_creation(
        endpoint_id=2, cluster_id=LEVEL,
        unique_id_suffix="tuya_dimming_mode",
    )
    # ── AllOnOff virtual endpoint ──
    .adds_endpoint(endpoint_id=ALL_ONOFF_EP)
    .adds(AllOnOffCluster, endpoint_id=ALL_ONOFF_EP)
    # Suppress redundant per-endpoint firmware/OTA update entities (all gangs).
    # OTA cluster (0x0019) is mirrored on every endpoint and has no ZHA OTA image,
    # so each firmware entity sits permanently "unknown". One rule, all endpoints.
    .prevent_default_entity_creation(unique_id_suffix="firmware_update")
    .add_to_registry()
)
