"""Expose the Gledopto GL-SPI-206P's 44 dreamlight scenes as HA light *effects*.

Background
----------
ZHA's light platform hard-codes the light `effect_list` (in the `zha` library,
``zha/application/platforms/light`` → ``Light.recompute_capabilities``) to only
``["off", "colorloop"]`` — colorloop only if the Color cluster advertises the
color-loop capability bit — and ``async_turn_on(effect=...)`` only understands
``colorloop``. There is **no quirks-v2 hook** to give a light entity a custom
effect list. So to put our 44 scenes on the light card's native "Effect" button
(instead of a separate ``select`` entity), we extend the zha ``Light`` class at
runtime.

What this does (guarded to ``_TZE284_gt5al3bl`` only, wrapped in try/except so it
can never break HA startup or any other light):
  1. Wraps ``Light.recompute_capabilities`` — after the original runs, for our
     device it sets ``_effect_list = ["off", <44 scene names>]`` and OR-s in the
     ``EFFECT`` feature flag.
  2. Wraps ``BaseSharedLight.async_turn_on`` — when ``effect`` is one of
     our scene names, it calls the Tuya MCU cluster's ``play_scene(index)``
     (which sends DP1=on + DP2=scene + DP51=raw payload) and returns; otherwise
     it defers to the original (so off/brightness/colour/CCT behave normally).

Scenes / payloads live in ``quirks/ts0601_light_TZE284_gt5al3bl.py``
(``SCENE_NAMES`` / ``ScenePreset`` / ``TuyaSPILightMCUCluster.play_scene``).
The patch is applied once from ``async_setup``; it survives a ZHA reload but a
Core restart re-imports and re-applies it. Same monkey-patch tradeoff the
component already uses for the ZHA fan platform.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import LightEntityFeature
from homeassistant.core import HomeAssistant

from .quirks.ts0601_light_TZE284_gt5al3bl import SCENE_NAMES, ScenePreset

_LOGGER = logging.getLogger(__name__)

DOMAIN = "woow_zha_quirks"
TARGET_MANUFACTURER = "_TZE284_gt5al3bl"
DATA_PATCHED = "woow_zha_quirks_light_effects_patched"

# effect name -> ScenePreset index (0..43); enum members iterate in definition
# order, matching SCENE_NAMES, and each member's value is its select index.
NAME_TO_INDEX: dict[str, int] = {
    name: member.value for member, name in zip(ScenePreset, SCENE_NAMES)
}
EFFECT_NAMES: list[str] = list(SCENE_NAMES)


def _color_endpoint(entity: Any) -> Any:
    """Return the zigpy endpoint behind the light's Color cluster.

    HA 2026.7 exposes the Color cluster directly as ``entity._color_cluster``; older
    ZHA wrapped it in a cluster handler (``entity._color_cluster_handler.cluster``).
    """
    cluster = getattr(entity, "_color_cluster", None)
    if cluster is None:
        handler = getattr(entity, "_color_cluster_handler", None)
        cluster = getattr(handler, "cluster", None)
    return getattr(cluster, "endpoint", None)


def _is_target(entity: Any) -> bool:
    """True if this zha light entity is our Gledopto GL-SPI-206P."""
    try:
        return _color_endpoint(entity).device.manufacturer == TARGET_MANUFACTURER
    except Exception:  # noqa: BLE001 - any missing attr → not our device
        return False


def _get_mcu(entity: Any) -> Any:
    """Return the device's Tuya MCU (0xEF00) cluster for scene playback."""
    return _color_endpoint(entity).tuya_manufacturer


def _apply_patch() -> bool:
    """Monkey-patch the zha Light class. Idempotent. Returns True if applied."""
    # HA 2026.7 renamed the turn-on base class BaseClusterHandlerLight -> BaseSharedLight
    # (hierarchy Light -> BaseSharedLight -> BaseLight; async_turn_on lives on
    # BaseSharedLight). Fall back to the old name for older ZHA.
    from zha.application.platforms.light import Light

    try:
        from zha.application.platforms.light import BaseSharedLight as _TurnOnBase
    except ImportError:
        from zha.application.platforms.light import (
            BaseClusterHandlerLight as _TurnOnBase,
        )

    try:
        from zha.application.platforms.light.const import EFFECT_OFF
    except Exception:  # noqa: BLE001
        EFFECT_OFF = "off"

    if getattr(Light.recompute_capabilities, "_woow_patched", False):
        return False  # already patched this process

    # ── 1. effect_list + EFFECT feature for our device ──────────────────
    _orig_recompute = Light.recompute_capabilities

    def _recompute(self: Any) -> None:
        _orig_recompute(self)
        if _is_target(self):
            try:
                self._supported_features |= LightEntityFeature.EFFECT
                self._effect_list = [EFFECT_OFF, *EFFECT_NAMES]
            except Exception:  # noqa: BLE001
                _LOGGER.exception("%s: effect recompute patch failed", DOMAIN)

    _recompute._woow_patched = True  # type: ignore[attr-defined]
    Light.recompute_capabilities = _recompute  # type: ignore[assignment]

    # ── 2. turn_on(effect=<scene>) → play_scene ─────────────────────────
    _orig_turn_on = _TurnOnBase.async_turn_on

    async def _turn_on(self: Any, *, effect: str | None = None, **kwargs: Any) -> None:
        if effect is not None and effect in NAME_TO_INDEX and _is_target(self):
            try:
                _get_mcu(self).play_scene(NAME_TO_INDEX[effect])
                self._effect = effect
                self.maybe_emit_state_changed_event()
                return
            except Exception:  # noqa: BLE001 - fall back to normal turn_on
                _LOGGER.exception("%s: play_scene failed for effect %s", DOMAIN, effect)
        await _orig_turn_on(self, effect=effect, **kwargs)

    _turn_on._woow_patched = True  # type: ignore[attr-defined]
    _TurnOnBase.async_turn_on = _turn_on  # type: ignore[assignment]

    return True


async def async_setup_light_effects(hass: HomeAssistant) -> None:
    """Apply the light-effect monkey-patch once (called from async_setup)."""
    if hass.data.get(DATA_PATCHED):
        return
    try:
        applied = _apply_patch()
        hass.data[DATA_PATCHED] = True
        if applied:
            _LOGGER.info(
                "%s: exposed %d dreamlight scenes as light effects for %s",
                DOMAIN,
                len(EFFECT_NAMES),
                TARGET_MANUFACTURER,
            )
    except Exception:  # noqa: BLE001 - never break HA startup
        _LOGGER.exception("%s: failed to apply light-effect patch", DOMAIN)
