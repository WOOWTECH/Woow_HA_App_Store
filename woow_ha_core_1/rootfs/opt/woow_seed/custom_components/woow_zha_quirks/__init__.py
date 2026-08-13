"""WOOW ZHA Quirks - 集中管理自訂 ZHA Quirks 與 Tuya 裝置支援。

安裝後在 configuration.yaml 加入 `woow_zha_quirks:` 即可自動載入所有 quirks，
不需要手動設定 zha.custom_quirks_path。

重要：quirks 會在「模組匯入時」即註冊進 zigpy 的 DEVICE_REGISTRY，以確保在
ZHA 建立/還原裝置之前完成註冊。否則（例如本元件被排在 ZHA 之後載入）重新開機
後 quirk 可能未套用，需要手動 reload ZHA 整合才會生效。
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import pathlib
import pkgutil
import sys

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.typing import ConfigType

from .knob_rebind import async_setup_knob_rebind
from .light_effects import async_setup_light_effects
from .orphan_sweep import async_setup_orphan_sweep
from .presence_defaults import async_setup_presence_defaults
from .quirk_heal import async_setup_quirk_heal
from .relay_resync import async_setup_relay_resync
from .scene_activate import async_setup_scene_activate

_LOGGER = logging.getLogger(__name__)

DOMAIN = "woow_zha_quirks"

_QUIRKS_LOADED = False


def _load_quirks() -> int:
    """載入 quirks/ 下所有 quirk 模組並註冊進 zigpy registry（同步）。"""
    quirks_path = pathlib.Path(__file__).parent / "quirks"
    count = 0
    for importer, modname, _ispkg in pkgutil.walk_packages(path=[str(quirks_path)]):
        # 跳過 __init__
        if modname == "__init__":
            continue

        full_modname = f"{DOMAIN}.quirks.{modname}"
        # 已載入過則略過，避免重複註冊造成 registry 衝突
        if full_modname in sys.modules:
            continue

        _LOGGER.debug("WOOW ZHA Quirks: 載入 quirk 模組 %s", full_modname)
        try:
            spec = importer.find_spec(modname)
            if spec is None:
                _LOGGER.warning("WOOW ZHA Quirks: 找不到模組 spec: %s", modname)
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[full_modname] = module
            spec.loader.exec_module(module)
            count += 1
        except Exception:
            _LOGGER.exception("WOOW ZHA Quirks: 載入 quirk 模組失敗: %s", modname)

    return count


# ──────────────────────────────────────────────────────────────────────
# 於模組匯入時即註冊 quirks（早於 ZHA 建立裝置，避免重開機需手動 reload）。
# 以 try/except 包覆，確保即使載入失敗也不會影響 Home Assistant 啟動。
# ──────────────────────────────────────────────────────────────────────
try:
    _imported = _load_quirks()
    _QUIRKS_LOADED = True
    _LOGGER.info("WOOW ZHA Quirks: 匯入時成功載入 %d 個 quirk 模組", _imported)
    # Keep woow v2 quirks authoritative over any competing upstream v2 quirk (e.g. the
    # _TZE204_clrdrnya / WO_40117 presence sensor, which zhaquirks.tuya.tuya_motion also
    # ships a v2 builder for). Must run after _load_quirks() so the keys are woow-owned.
    from .quirk_priority import install_priority_guard

    install_priority_guard()
except Exception:  # pragma: no cover - 防呆
    _LOGGER.exception("WOOW ZHA Quirks: 匯入時載入 quirks 失敗")


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """設定 WOOW ZHA Quirks 元件。

    Quirks 通常已於模組匯入時載入；若當時失敗，這裡以 executor 再嘗試一次。
    """
    global _QUIRKS_LOADED
    if not _QUIRKS_LOADED:
        loaded = await hass.async_add_executor_job(_load_quirks)
        _QUIRKS_LOADED = True
        _LOGGER.info("WOOW ZHA Quirks: async_setup 載入 %d 個 quirk 模組", loaded)

    # 啟動 climate 平台：為支援的 ZHA 裝置（目前 SM0308F / 14-66E7109TY）
    # 自動建立單一 HA-core climate 實體（包裝既有的 switch/number/select 實體）。
    hass.async_create_task(
        async_load_platform(hass, Platform.CLIMATE, DOMAIN, {}, config)
    )

    # Self-healing group bind for the 4-58E8017 rotary knob (TS0034): this Tuya controller
    # only multicasts to group 0x2760 and ignores ZHA's unicast bind, so a (re-)pair leaves
    # its sensors stuck on "Unknown". Recreate the group + group-bind automatically on pair
    # and expose the woow_zha_quirks.rebind_knob service. See knob_rebind.py.
    await async_setup_knob_rebind(hass)

    # Re-sync the 21-TYZGTH1CH-D1RF relay state after a power-cycle (the device doesn't
    # report its boot state and ZHA doesn't re-read on rejoin). See relay_resync.py.
    await async_setup_relay_resync(hass)

    # Activate the 7-58E8021 / 12-70E8306 scene-switch buttons (store a scene in group 0x270f +
    # bind their output OnOff to the coordinator) so a physical press emits OnOff cmd 0xFB, which
    # ScenePressOnOffCluster catches → toggles the HA switch. See scene_activate.py.
    await async_setup_scene_activate(hass)

    # Expose the Gledopto GL-SPI-206P (_TZE284_gt5al3bl) 44 dreamlight scenes as
    # native HA light *effects* (ZHA hard-codes effect_list, so a guarded runtime
    # patch of the zha Light class is used). See light_effects.py.
    await async_setup_light_effects(hass)

    # Write a curated set of optimal defaults into the WO_40117 (_TZE204_clrdrnya) presence
    # sensor ONCE on first pairing (persisted, so later manual changes survive restarts); plus a
    # woow_zha_quirks.apply_presence_defaults service to re-apply. See presence_defaults.py.
    await async_setup_presence_defaults(hass)

    # Self-heal the ZHA-quirk load-order race: once per HA start, detect devices that
    # match a registered woow quirk but came up quirk_applied=False (ZHA restored them
    # before our import-time registration landed) and reload ZHA once to apply the quirk.
    # See quirk_heal.py.
    await async_setup_quirk_heal(hass)

    # Standalone, always-on cleanup of stale "orphan" ZHA entities (old light/firmware/
    # power-on rows left behind when a device's quirk/config changed). Independent of the
    # heal above; gated to only ever touch dead (unavailable+restored) rows on online
    # devices, with a two-pass stability check. See orphan_sweep.py.
    await async_setup_orphan_sweep(hass)
    return True
