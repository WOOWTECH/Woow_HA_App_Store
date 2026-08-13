"""ZHA Quirk (v2) for Zemismart ZMS-206US-4 (_TZE204_wwaeqnrf / TS0601)

4-Gang Zigbee Smart Screen Switch with full feature support.
All settings exposed as native HA entities via TuyaQuirkBuilder.

Verified DP Map (tested 2026-04-23 via zha-toolkit):
  DP  1-4   : Switch 1-4 on/off          (bool)
  DP  13    : All switches on/off        (bool)
  DP  7-10  : Countdown timer 1-4        (value, uint32 seconds)
  DP  15    : Indicator LED mode          (enum: 0=off, 1=relay, 2=position)
  DP  16    : Backlight master switch     (bool)
  DP  29-32 : Relay power-on state 1-4   (enum: 0=off, 1=on, 2=memory)
  DP  101   : Child lock                  (bool)
  DP  102   : Backlight brightness        (value, 0-100%)
  DP  103   : ON indicator color          (enum: 0-6)
  DP  104   : OFF indicator color         (enum: 0-6)
  DP  105-108: Switch 1-4 screen label    (raw/string, write-only, 12-char max)

Screen labels (DP105-108):
  These are write-only DPs that set the text displayed on each gang's
  screen. They use RAW DP type (0x00) with UTF-8 encoded bytes.

  Auto-sync: Screen labels are automatically synced from the HA entity
  friendly_name on HA startup and whenever an entity is renamed.
  This is handled entirely within the quirk — no external automation
  needed.

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
    TUYA_MCU_COMMAND,
    TuyaCommand,
    TuyaData,
    TuyaDatapointData,
    TuyaDPType,
)
from zhaquirks.tuya.builder import TuyaQuirkBuilder
from zhaquirks.tuya.mcu import TuyaMCUCluster

_LOGGER = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────
# Custom Enums
# ────────────────────────────────────────────────────────────────

class IndicatorMode(t.enum8):
    """Indicator LED mode."""

    Off = 0x00
    Relay = 0x01
    Position = 0x02


class LEDColor(t.enum8):
    """LED indicator color."""

    Red = 0x00
    Blue = 0x01
    Green = 0x02
    White = 0x03
    Yellow = 0x04
    Magenta = 0x05
    Cyan = 0x06


class PowerOnState(t.enum8):
    """Power-on state after power loss."""

    Off = 0x00
    On = 0x01
    Memory = 0x02


def _str_to_raw_tuya(value) -> TuyaData:
    """Convert a string to TuyaData with RAW type (UTF-8 encoded bytes).

    The device MCU expects RAW (0x00) DP type for screen labels,
    not STRING (0x03). Limited to 12 characters.
    """
    td = TuyaData()
    td.dp_type = TuyaDPType.RAW
    if isinstance(value, str):
        td.raw = value[:12].encode("utf-8")
    elif isinstance(value, (bytes, bytearray)):
        td.raw = bytes(value[:12])
    else:
        td.raw = str(value)[:12].encode("utf-8")
    return td


# Screen label attribute name → DP ID mapping
_SCREEN_LABEL_DPS: dict[str, int] = {
    "screen_label_1": 105,
    "screen_label_2": 106,
    "screen_label_3": 107,
    "screen_label_4": 108,
}

# Switch DP → Screen label DP mapping (for auto-sync)
# Key: switch on_off DP id, Value: screen label DP id
_SWITCH_DP_TO_LABEL_DP: dict[int, int] = {
    1: 105,
    2: 106,
    3: 107,
    4: 108,
}

# Reverse: switch attribute_name → label attribute_name
_SWITCH_ATTR_TO_LABEL_ATTR: dict[str, str] = {
    "on_off_1": "screen_label_1",
    "on_off_2": "screen_label_2",
    "on_off_3": "screen_label_3",
    "on_off_4": "screen_label_4",
}


# Module-level set to ensure auto-sync triggers only once per device IEEE
# (survives cluster object recreation across HA internal restarts)
_SYNC_TRIGGERED_IEES: set[str] = set()


def _get_hass(cluster: Any) -> Any | None:
    """Extract the HA ``hass`` object from a zigpy cluster.

    Traverses the internal ZHA listener chain:
      cluster → application → Gateway (listener) →
      ZHAGatewayProxy (global_listener) → hass

    Returns ``None`` if the chain is broken (e.g. during unit tests or
    if ZHA internals change).
    """
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


class ScreenLabelTuyaMCUCluster(TuyaMCUCluster):
    """TuyaMCU cluster with screen-label write support and auto-sync.

    Features:
      1. Direct string DP writes for screen_label_* attributes
         (bypasses TuyaClusterData which only supports int values).
      2. Auto-sync: on HA startup and entity rename, reads each switch
         entity's friendly_name and writes it to the matching screen
         label DP.  No external automation needed.

    Subclass contract (for multi-device universal support):
      Override ``SWITCH_DP_TO_LABEL_DP`` with the device-specific mapping
      of switch DP → screen label DP.
    """

    # --- Override these in subclasses for different devices ---
    SWITCH_DP_TO_LABEL_DP: dict[int, int] = _SWITCH_DP_TO_LABEL_DP
    SWITCH_ATTR_TO_LABEL_ATTR: dict[str, str] = _SWITCH_ATTR_TO_LABEL_ATTR

    _sync_unsub: Any | None = None  # event listener unsubscribe handle

    # ── String DP write support ───────────────────────────────────

    async def write_attributes(self, attributes, manufacturer=None, **kwargs):
        """Handle string-type screen label attributes directly."""
        regular_attrs = {}
        for attr_name, value in attributes.items():
            # Resolve int attr IDs to names
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
        """Wait for HA to be ready, do initial sync, subscribe to renames."""
        await asyncio.sleep(10)  # let HA + ZHA finish entity setup

        hass = _get_hass(self)
        if hass is None:
            _LOGGER.warning("Screen label auto-sync: cannot reach hass")
            return

        # Initial sync
        await self._sync_labels_from_registry(hass)

        # Subscribe to entity_registry_updated for live rename sync
        if self._sync_unsub is None:
            self._sync_unsub = hass.bus.async_listen(
                "entity_registry_updated", self._on_entity_registry_updated,
            )
            _LOGGER.info("Screen label auto-sync: listener registered")

    async def _on_entity_registry_updated(self, event: Any) -> None:
        """Handle entity rename events."""
        if event.data.get("action") != "update":
            return
        changes = event.data.get("changes", {})
        if "name" not in changes and "original_name" not in changes:
            return

        hass = _get_hass(self)
        if hass is None:
            return

        from homeassistant.helpers import (  # noqa: E402
            device_registry as dr_mod,
            entity_registry as er_mod,
        )

        # Check if the changed entity belongs to this device
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

        # Check if any identifier matches our IEEE
        is_our_device = any(
            device_ieee in str(ident)
            for _domain, ident in device_entry.identifiers
        )
        if not is_our_device:
            return

        _LOGGER.info("Screen label auto-sync: entity renamed %s", entity_id)
        await asyncio.sleep(1)  # brief settle
        await self._sync_labels_from_registry(hass)

    async def _sync_labels_from_registry(self, hass: Any) -> None:
        """Read switch entity friendly_names and write to screen labels."""
        from homeassistant.helpers import (  # noqa: E402
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

        # Find our device in the HA device registry
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

        # Build unique_id → friendly_name map for switch entities on this device
        switch_names: dict[str, str] = {}
        for entry in ent_reg.entities.values():
            if entry.device_id != our_device_id:
                continue
            if not entry.entity_id.startswith("switch."):
                continue
            # Display name priority: custom name > original_name > entity_id
            name = entry.name or entry.original_name or entry.entity_id
            switch_names[entry.unique_id] = name

        _LOGGER.debug("Screen label sync: found %d switch entities for %s",
                      len(switch_names), device_ieee)

        # Match switch entities to labels via unique_id suffix pattern
        # ZHA unique_ids for Tuya switches end with e.g. "...61184_on_off_1"
        synced = 0
        for switch_attr, label_attr in self.SWITCH_ATTR_TO_LABEL_ATTR.items():
            friendly = None
            for uid, name in switch_names.items():
                if switch_attr in uid:
                    friendly = name
                    break

            if friendly is None:
                _LOGGER.debug("Screen label sync: no entity found for %s",
                              switch_attr)
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
    TuyaQuirkBuilder("_TZE204_wwaeqnrf", "TS0601")
    # ── 4 main switches (DP 1-4) ─────────────────────────────
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
    .tuya_switch(
        dp_id=4,
        attribute_name="on_off_4",
        entity_type=EntityType.STANDARD,
        translation_key="on_off_4",
        fallback_name="Switch 4",
    )
    # NOTE: All-On/Off (DP13) and Countdown timers (DP7-10) are intentionally
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
    # ── Power-on states (DP 29-32) → Select entities ─────────
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
    .tuya_enum(
        dp_id=32,
        attribute_name="power_on_state_4",
        enum_class=PowerOnState,
        entity_type=EntityType.CONFIG,
        translation_key="power_on_state_4",
        fallback_name="Power On State 4",
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
    # ── Screen labels (DP 105-108) — write-only string DPs ──
    # Registered as writable attributes with RAW-type dp_converter.
    # No HA entity (ZHA has no text platform), but writable via
    # zha.set_zigbee_cluster_attribute or zha_toolkit.
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
    .tuya_dp_attribute(
        dp_id=108,
        attribute_name="screen_label_4",
        type=t.CharacterString,
        access=foundation.ZCLAttributeAccess.Read | foundation.ZCLAttributeAccess.Write,
        dp_converter=_str_to_raw_tuya,
    )
    # ── Suppress the redundant firmware/OTA update entity ────
    # No ZHA-distributable OTA image exists for this Tuya device, so the update
    # entity is permanently inert.
    .prevent_default_entity_creation(unique_id_suffix="firmware_update")
    .skip_configuration()
    .add_to_registry(replacement_cluster=ScreenLabelTuyaMCUCluster)
)
