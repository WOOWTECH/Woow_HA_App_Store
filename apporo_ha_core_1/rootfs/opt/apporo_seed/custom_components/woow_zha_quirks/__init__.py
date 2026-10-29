"""WOOW ZHA Quirks - 集中管理自訂 ZHA Quirks 與 Tuya 裝置支援。

自 1.4.0 起改由 UI 設定（設定 → 裝置與服務 → 新增整合），`configuration.yaml` 中的
`woow_zha_quirks:` 已失效。仍留著該行的安裝會收到一則「修復」通知，按下確認即可建立
設定項目。詳見 docs/adr/0005-config-entry-setup.md。

重要：quirks 會在「模組匯入時」即註冊進 zigpy 的 DEVICE_REGISTRY，以確保在 ZHA 建立/
還原裝置之前完成註冊 —— 這早於 async_setup_entry，且與 YAML 時代的時機相同。也因此
manifest.json 刻意**不**宣告對 zha 的 dependencies / after_dependencies：兩者都會強制
ZHA 先載入，正是讓 quirk_priority 的保護太晚安裝、upstream quirk 勝出的順序。

同樣因為註冊是行程級的全域副作用，卸載設定項目**不會**解除 quirk 註冊、priority guard
或 light_effects 的 monkey-patch；那三者需要重新啟動 Home Assistant 才會消失。
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import pathlib
import pkgutil
import sys

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, ISSUE_YAML_REMOVED, NOTIFY_RESTART_REQUIRED, PLATFORMS
from .knob_rebind import async_setup_knob_rebind
from .light_effects import async_setup_light_effects
from .orphan_sweep import async_setup_orphan_sweep
from .presence_defaults import async_setup_presence_defaults
from .quirk_heal import async_setup_quirk_heal
from .relay_resync import async_setup_relay_resync
from .scene_activate import async_setup_scene_activate

_LOGGER = logging.getLogger(__name__)

DOCS_URL = "https://github.com/WOOWTECH/Woow_ha_zha_quirk_component"

# Setup is UI-only; a leftover YAML key is reported, never honoured.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

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
    """偵測殘留的 YAML 設定，並提示使用者一鍵遷移。

    這個 hook 只為 1.3.x → 1.4.0 的遷移而存在，不做任何設定工作 —— 真正的啟動在
    async_setup_entry。可移除的時機見 ADR 0005。

    注意：能走到這裡就代表 configuration.yaml 還留著 `woow_zha_quirks:`（否則沒有設定
    項目時 Home Assistant 根本不會載入本元件）。也正因為 YAML 還在，本模組仍被匯入，
    上面的 import-time 註冊照常生效 —— 這種安裝的 quirks 是正常的，缺的只是執行期掛鉤
    與 climate 實體。
    """
    if DOMAIN not in config:
        return True

    if hass.config_entries.async_entries(DOMAIN):
        # 已經遷移完成，只是 YAML 那一行還沒刪；HA 自己會在 log 提醒，不再另外打擾。
        return True

    _LOGGER.warning(
        "WOOW ZHA Quirks: configuration.yaml 的 `%s:` 自 1.4.0 起已失效；"
        "請依修復通知或「設定 → 裝置與服務 → 新增整合」重新設定",
        DOMAIN,
    )
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_YAML_REMOVED,
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_YAML_REMOVED,
        learn_more_url=DOCS_URL,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """啟動所有執行期掛鉤與 climate 平台。

    每一個掛鉤都以 entry.async_on_unload 註冊其 listener / timer / service，因此「重新
    載入」不會留下第二份 orphan_sweep（會刪 entity registry 列）或 presence_defaults
    （會寫裝置設定）在背景並行執行。
    """
    global _QUIRKS_LOADED
    if not _QUIRKS_LOADED:
        loaded = await hass.async_add_executor_job(_load_quirks)
        _QUIRKS_LOADED = True
        _LOGGER.info("WOOW ZHA Quirks: async_setup_entry 載入 %d 個 quirk 模組", loaded)

    # 遷移完成，撤掉修復通知。
    ir.async_delete_issue(hass, DOMAIN, ISSUE_YAML_REMOVED)

    # Self-healing group bind for the 4-58E8017 rotary knob (TS0034): this Tuya controller
    # only multicasts to group 0x2760 and ignores ZHA's unicast bind, so a (re-)pair leaves
    # its sensors stuck on "Unknown". Recreate the group + group-bind automatically on pair
    # and expose the woow_zha_quirks.rebind_knob service. See knob_rebind.py.
    await async_setup_knob_rebind(hass, entry)

    # Re-sync the 21-TYZGTH1CH-D1RF relay state after a power-cycle (the device doesn't
    # report its boot state and ZHA doesn't re-read on rejoin). See relay_resync.py.
    await async_setup_relay_resync(hass, entry)

    # Activate the 7-58E8021 / 12-70E8306 scene-switch buttons (join group 0x270f, store a scene
    # in it, bind their output OnOff cluster to the coordinator) so a physical press emits OnOff cmd 0xFB,
    # which ScenePressOnOffCluster catches → toggles the HA switch. See scene_activate.py.
    await async_setup_scene_activate(hass, entry)

    # Expose the Gledopto GL-SPI-206P (_TZE284_gt5al3bl) 44 dreamlight scenes as
    # native HA light *effects* (ZHA hard-codes effect_list, so a guarded runtime
    # patch of the zha Light class is used). See light_effects.py.
    await async_setup_light_effects(hass, entry)

    # Write a curated set of optimal defaults into the WO_40117 (_TZE204_clrdrnya) presence
    # sensor ONCE on first pairing (persisted, so later manual changes survive restarts); plus a
    # woow_zha_quirks.apply_presence_defaults service to re-apply. See presence_defaults.py.
    await async_setup_presence_defaults(hass, entry)

    # Self-heal the ZHA-quirk load-order race: once per HA start, detect devices that
    # match a registered woow quirk but came up quirk_applied=False (ZHA restored them
    # before our import-time registration landed) and reload ZHA once to apply the quirk.
    # See quirk_heal.py.
    await async_setup_quirk_heal(hass, entry)

    # Standalone, always-on cleanup of stale "orphan" ZHA entities (old light/firmware/
    # power-on rows left behind when a device's quirk/config changed). Independent of the
    # heal above; gated to only ever touch dead (unavailable+restored) rows on online
    # devices, with a two-pass stability check. See orphan_sweep.py.
    await async_setup_orphan_sweep(hass, entry)

    # climate：為支援的 ZHA 裝置（SM0308F / 14-66E7109TY、SM0308C / 8-58E7101）建立單一
    # HA-core climate 實體，包裝既有的 switch/number/select 實體。
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """卸載 climate 平台；掛鉤本身由 entry.async_on_unload 自動拆除。

    刻意**不**處理的三件事，它們是行程級副作用、沒有還原路徑：quirk 註冊（zigpy 沒有
    unregister）、quirk_priority 的 registry monkey-patch、light_effects 對 ZHA Light
    類別的 patch。要真正移除必須重新啟動 Home Assistant。
    """
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    _LOGGER.info(
        "WOOW ZHA Quirks: 設定項目已卸載；quirk 註冊、priority guard 與 light_effects "
        "patch 為行程級副作用，將保留至 Home Assistant 重新啟動"
    )
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """告知使用者「刪除整合」不等於移除 quirks。

    刪除後裝置仍套著 woow 的 quirk，看起來像沒刪掉。這裡用通知而非修復通知，是因為沒有
    任何按鈕能解決它 —— 唯一的解法就是重新啟動。
    """
    from homeassistant.components import persistent_notification

    persistent_notification.async_create(
        hass,
        "WOOW ZHA Quirks 的設定項目已刪除，但 quirk 註冊與燈光效果修補屬於行程級變更，"
        "仍在作用中。請重新啟動 Home Assistant 以完全移除。",
        title="WOOW ZHA Quirks：需重新啟動",
        notification_id=NOTIFY_RESTART_REQUIRED,
    )
