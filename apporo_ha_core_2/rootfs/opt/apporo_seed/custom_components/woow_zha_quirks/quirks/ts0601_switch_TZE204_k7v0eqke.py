"""ZHA Quirk (v2) for Tuya 3-Gang Screen Switch (_TZE204_k7v0eqke / TS0601)

3-Gang Zigbee Smart Screen Switch with full feature support.
Uses the same MCU firmware as the 4-gang _TZE204_wwaeqnrf but with
only 3 physical gangs connected.  DP 4/10/32/108 are phantom (MCU
accepts them but no physical relay/screen).

Verified DP Map (tested 2026-06-08 via zha-toolkit):
  DP  1-3   : Switch 1-3 on/off          (bool)
  DP  13    : All switches on/off        (bool, controls 1-3 only)
  DP  7-9   : Countdown timer 1-3        (value, uint32 seconds)
  DP  15    : Indicator LED mode          (enum: 0=off, 1=relay, 2=position)
  DP  16    : Backlight master switch     (bool)
  DP  29-31 : Relay power-on state 1-3   (enum: 0=off, 1=on, 2=memory)
  DP  101   : Child lock                  (bool)
  DP  102   : Backlight brightness        (value, 0-100%)
  DP  103   : ON indicator color          (enum: 0-6)
  DP  104   : OFF indicator color         (enum: 0-6)
  DP  105-107: Switch 1-3 screen label    (raw/string, write-only, 12-char max)

Screen labels (DP105-107):
  Auto-sync from HA entity friendly_name on startup and entity rename.
  No external automation needed.

Device Signature (from scan_device):
  Endpoint 1:
    Input:  [0x0000 Basic, 0x0004 Groups, 0x0005 Scenes, 0xEF00 Tuya MCU]
    Output: [0x000A Time, 0x0019 OTA]
  Endpoint 242 (GreenPower proxy):
    Profile: 0xA1E0, Device Type: 0x0061
    Input:  []
    Output: [0x0021 GreenPower]
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import zigpy.types as t
from zigpy.quirks.v2 import EntityType
from zigpy.zcl import foundation
from zhaquirks.tuya import (
    TuyaCommand,
    TuyaData,
    TuyaDatapointData,
    TuyaDPType,
)
from zhaquirks.tuya.builder import TuyaQuirkBuilder
from zhaquirks.tuya.mcu import TuyaMCUCluster

_LOGGER = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────
# Custom Enums (shared with 4-gang)
# ────────────────────────────────────────────────────────────────

class IndicatorMode(t.enum8):
    Off = 0x00
    Relay = 0x01
    Position = 0x02


class LEDColor(t.enum8):
    Red = 0x00
    Blue = 0x01
    Green = 0x02
    White = 0x03
    Yellow = 0x04
    Magenta = 0x05
    Cyan = 0x06


class PowerOnState(t.enum8):
    Off = 0x00
    On = 0x01
    Memory = 0x02


def _str_to_raw_tuya(value) -> TuyaData:
    """Convert a string to TuyaData with RAW type (UTF-8 encoded bytes)."""
    td = TuyaData()
    td.dp_type = TuyaDPType.RAW
    if isinstance(value, str):
        td.raw = value[:12].encode("utf-8")
    elif isinstance(value, (bytes, bytearray)):
        td.raw = bytes(value[:12])
    else:
        td.raw = str(value)[:12].encode("utf-8")
    return td


# ────────────────────────────────────────────────────────────────
# DP mappings (3-gang specific)
# ────────────────────────────────────────────────────────────────

_SCREEN_LABEL_DPS: dict[str, int] = {
    "screen_label_1": 105,
    "screen_label_2": 106,
    "screen_label_3": 107,
}

_SWITCH_ATTR_TO_LABEL_ATTR: dict[str, str] = {
    "on_off_1": "screen_label_1",
    "on_off_2": "screen_label_2",
    "on_off_3": "screen_label_3",
}

_SYNC_TRIGGERED_IEES: set[str] = set()


def _get_hass(cluster: Any) -> Any | None:
    """Extract the HA hass object from a zigpy cluster via ZHA internals."""
    try:
        app = cluster.endpoint.device.application
        for _lid, (listener, _inc_ctx) in app._listeners.items():
            if not hasattr(listener, "application_controller"):
                continue
            for gl in getattr(listener, "_global_listeners", []):
                cb = getattr(gl, "callback", None)
                if cb is None:
                    continue
                proxy = getattr(cb, "__self__", None)
                if proxy is not None and hasattr(proxy, "hass"):
                    return proxy.hass
    except (AttributeError, RuntimeError, TypeError):
        pass
    return None


# ────────────────────────────────────────────────────────────────
# Custom MCU Cluster with screen label write + auto-sync
# ────────────────────────────────────────────────────────────────

class ThreeGangScreenLabelCluster(TuyaMCUCluster):
    """TuyaMCU cluster with screen-label write support and auto-sync.

    3-gang version: syncs friendly_name → screen_label for 3 switches.
    """

    SWITCH_ATTR_TO_LABEL_ATTR: dict[str, str] = _SWITCH_ATTR_TO_LABEL_ATTR

    _sync_unsub: Any | None = None

    # ── String DP write support ───────────────────────────────────

    async def write_attributes(self, attributes, manufacturer=None, **kwargs):
        """Handle string-type screen label attributes directly."""
        regular_attrs = {}
        for attr_name, value in attributes.items():
            if isinstance(attr_name, int):
                attr_def = self.attributes.get(attr_name)
                name = attr_def.name if attr_def else None
            else:
                name = attr_name

            if name in _SCREEN_LABEL_DPS:
                dp_id = _SCREEN_LABEL_DPS[name]
                tuya_data = _str_to_raw_tuya(value)
                dpd = TuyaDatapointData(dp=dp_id, data=tuya_data)
                cmd = TuyaCommand(
                    status=0,
                    tsn=self.endpoint.device.application.get_sequence(),
                    datapoints=[dpd],
                )
                await self.command(0x00, cmd)
                attr_id = self.attributes_by_name[name].id
                self._update_attribute(attr_id, value)
                _LOGGER.debug("Screen label DP%d written: %s", dp_id, value)
            else:
                regular_attrs[attr_name] = value

        if regular_attrs:
            return await super().write_attributes(
                regular_attrs, manufacturer=manufacturer, **kwargs
            )
        return [[foundation.WriteAttributesStatusRecord(foundation.Status.SUCCESS)]]

    # ── Auto-sync: friendly_name → screen label ──────────────────

    def handle_cluster_request(self, hdr, args, *, dst_addressing=None):
        """Trigger auto-sync on first incoming message from the device."""
        result = super().handle_cluster_request(
            hdr, args, dst_addressing=dst_addressing,
        )
        ieee = str(self.endpoint.device.ieee)
        if ieee not in _SYNC_TRIGGERED_IEES:
            _SYNC_TRIGGERED_IEES.add(ieee)
            _LOGGER.info(
                "Screen label auto-sync: first message from %s, starting sync",
                ieee,
            )
            self.create_catching_task(self._setup_auto_sync())
        return result

    async def _setup_auto_sync(self) -> None:
        await asyncio.sleep(10)

        hass = _get_hass(self)
        if hass is None:
            _LOGGER.warning("Screen label auto-sync: cannot reach hass")
            return

        await self._sync_labels_from_registry(hass)

        if self._sync_unsub is None:
            self._sync_unsub = hass.bus.async_listen(
                "entity_registry_updated", self._on_entity_registry_updated,
            )
            _LOGGER.info("Screen label auto-sync: listener registered")

    async def _on_entity_registry_updated(self, event: Any) -> None:
        if event.data.get("action") != "update":
            return
        changes = event.data.get("changes", {})
        if "name" not in changes and "original_name" not in changes:
            return

        hass = _get_hass(self)
        if hass is None:
            return

        from homeassistant.helpers import (
            device_registry as dr_mod,
            entity_registry as er_mod,
        )

        entity_id = event.data.get("entity_id", "")
        ent_reg = er_mod.async_get(hass)
        entry = ent_reg.async_get(entity_id)
        if entry is None or entry.device_id is None:
            return

        device_ieee = str(self.endpoint.device.ieee)
        dev_reg = dr_mod.async_get(hass)
        device_entry = dev_reg.async_get(entry.device_id)
        if device_entry is None:
            return

        is_our_device = any(
            device_ieee in str(ident)
            for _domain, ident in device_entry.identifiers
        )
        if not is_our_device:
            return

        _LOGGER.info("Screen label auto-sync: entity renamed %s", entity_id)
        await asyncio.sleep(1)
        await self._sync_labels_from_registry(hass)

    async def _sync_labels_from_registry(self, hass: Any) -> None:
        from homeassistant.helpers import (
            device_registry as dr_mod,
            entity_registry as er_mod,
        )

        try:
            ent_reg = er_mod.async_get(hass)
            dev_reg = dr_mod.async_get(hass)
        except Exception:
            _LOGGER.warning("Screen label sync: cannot access registries")
            return

        device_ieee = str(self.endpoint.device.ieee)

        our_device_id = None
        for dev in dev_reg.devices.values():
            for _domain, ident in dev.identifiers:
                if device_ieee in str(ident):
                    our_device_id = dev.id
                    break
            if our_device_id:
                break

        if our_device_id is None:
            _LOGGER.warning("Screen label sync: device %s not in registry",
                            device_ieee)
            return

        switch_names: dict[str, str] = {}
        for entry in ent_reg.entities.values():
            if entry.device_id != our_device_id:
                continue
            if not entry.entity_id.startswith("switch."):
                continue
            name = entry.name or entry.original_name or entry.entity_id
            switch_names[entry.unique_id] = name

        synced = 0
        for switch_attr, label_attr in self.SWITCH_ATTR_TO_LABEL_ATTR.items():
            friendly = None
            for uid, name in switch_names.items():
                if switch_attr in uid:
                    friendly = name
                    break

            if friendly is None:
                continue

            label_dp = _SCREEN_LABEL_DPS.get(label_attr)
            if label_dp is None:
                continue

            try:
                await self.write_attributes({label_attr: friendly})
                synced += 1
                _LOGGER.info("Screen label sync: %s → DP%d = '%s'",
                             switch_attr, label_dp, friendly)
            except Exception as exc:
                _LOGGER.warning("Screen label sync failed for %s: %s",
                                label_attr, exc)

        _LOGGER.info("Screen label auto-sync complete: %d/%d labels written",
                     synced, len(self.SWITCH_ATTR_TO_LABEL_ATTR))


# ────────────────────────────────────────────────────────────────
# Quirk V2 — TuyaQuirkBuilder
# ────────────────────────────────────────────────────────────────

(
    TuyaQuirkBuilder("_TZE204_k7v0eqke", "TS0601")
    # ── 3 main switches (DP 1-3) ─────────────────────────────
    .tuya_switch(
        dp_id=1,
        attribute_name="on_off_1",
        entity_type=EntityType.STANDARD,
        translation_key="on_off_1",
        fallback_name="Switch 1",
    )
    .tuya_switch(
        dp_id=2,
        attribute_name="on_off_2",
        entity_type=EntityType.STANDARD,
        translation_key="on_off_2",
        fallback_name="Switch 2",
    )
    .tuya_switch(
        dp_id=3,
        attribute_name="on_off_3",
        entity_type=EntityType.STANDARD,
        translation_key="on_off_3",
        fallback_name="Switch 3",
    )
    # NOTE: All-On/Off (DP13) and Countdown timers (DP7-9) are intentionally
    # NOT exposed as entities (removed per user request). The device may still
    # emit those DP reports; TuyaMCUCluster logs them as unhandled at debug level.
    # ── Indicator LED mode (DP 15) → Select entity ───────────
    .tuya_enum(
        dp_id=15,
        attribute_name="indicator_mode",
        enum_class=IndicatorMode,
        entity_type=EntityType.CONFIG,
        translation_key="indicator_mode",
        fallback_name="Indicator Mode",
    )
    # ── Backlight switch (DP 16) → Switch entity ─────────────
    .tuya_switch(
        dp_id=16,
        attribute_name="backlight_switch",
        entity_type=EntityType.CONFIG,
        translation_key="backlight_switch",
        fallback_name="Backlight",
    )
    # ── Power-on states (DP 29-31) → Select entities ─────────
    .tuya_enum(
        dp_id=29,
        attribute_name="power_on_state_1",
        enum_class=PowerOnState,
        entity_type=EntityType.CONFIG,
        translation_key="power_on_state_1",
        fallback_name="Power On State 1",
    )
    .tuya_enum(
        dp_id=30,
        attribute_name="power_on_state_2",
        enum_class=PowerOnState,
        entity_type=EntityType.CONFIG,
        translation_key="power_on_state_2",
        fallback_name="Power On State 2",
    )
    .tuya_enum(
        dp_id=31,
        attribute_name="power_on_state_3",
        enum_class=PowerOnState,
        entity_type=EntityType.CONFIG,
        translation_key="power_on_state_3",
        fallback_name="Power On State 3",
    )
    # ── Child lock (DP 101) → Switch entity ───────────────────
    .tuya_switch(
        dp_id=101,
        attribute_name="child_lock",
        entity_type=EntityType.CONFIG,
        translation_key="child_lock",
        fallback_name="Child Lock",
    )
    # ── Backlight brightness (DP 102) → Number entity ────────
    .tuya_number(
        dp_id=102,
        attribute_name="backlight_level",
        type=t.uint32_t,
        min_value=0,
        max_value=100,
        step=1,
        entity_type=EntityType.CONFIG,
        translation_key="backlight_level",
        fallback_name="Backlight Level",
    )
    # ── ON/OFF indicator colors (DP 103-104) → Select entities
    .tuya_enum(
        dp_id=103,
        attribute_name="on_color",
        enum_class=LEDColor,
        entity_type=EntityType.CONFIG,
        translation_key="on_color",
        fallback_name="ON Indicator Color",
    )
    .tuya_enum(
        dp_id=104,
        attribute_name="off_color",
        enum_class=LEDColor,
        entity_type=EntityType.CONFIG,
        translation_key="off_color",
        fallback_name="OFF Indicator Color",
    )
    # ── Screen labels (DP 105-107) — write-only string DPs ──
    .tuya_dp_attribute(
        dp_id=105,
        attribute_name="screen_label_1",
        type=t.CharacterString,
        access=foundation.ZCLAttributeAccess.Read | foundation.ZCLAttributeAccess.Write,
        dp_converter=_str_to_raw_tuya,
    )
    .tuya_dp_attribute(
        dp_id=106,
        attribute_name="screen_label_2",
        type=t.CharacterString,
        access=foundation.ZCLAttributeAccess.Read | foundation.ZCLAttributeAccess.Write,
        dp_converter=_str_to_raw_tuya,
    )
    .tuya_dp_attribute(
        dp_id=107,
        attribute_name="screen_label_3",
        type=t.CharacterString,
        access=foundation.ZCLAttributeAccess.Read | foundation.ZCLAttributeAccess.Write,
        dp_converter=_str_to_raw_tuya,
    )
    # ── Suppress the redundant firmware/OTA update entity ────
    # No ZHA-distributable OTA image exists for this Tuya device, so the update
    # entity is permanently inert.
    .prevent_default_entity_creation(unique_id_suffix="firmware_update")
    .skip_configuration()
    .add_to_registry(replacement_cluster=ThreeGangScreenLabelCluster)
)
