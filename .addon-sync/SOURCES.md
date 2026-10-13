# WOOW HA addon 來源對照

由 `WOOWTECH` 帳號的 315 個 repo（掃描當時的數量）實際掃描產生（2026-10-06，掃描到第 3 層的 `config.yaml|yml|json`，並以 manifest 內容判斷，不靠 repo 名稱）。
**即時的版本、來源 SHA 與映像 digest 以 [`catalog.json`](catalog.json) 為準；映射與政策以 [`registry.json`](registry.json) 為準。** 本表只說明各來源為什麼納入或排除。

## 已登錄來源（27 個 repo、52 個 context）

「rebrand」欄＝是否已出現在 `catalog.json`（ha-rebrand 的 `release/addons/catalog.json` 與它逐位元組相同）。
「CI／映像要求」是 Store consumer 會重新檢查的條件；沒有 required workflow 的本機建置項目只做結構檢查，**不代表 Docker 建置或實機健康已驗證**（Tailscale 例外：它的 `Build` 在 CI 實際建置 amd64＋aarch64）。

| 來源 repo | 發布政策 | context | slug／通道 | Store 目錄 | rebrand | CI／映像要求 | 交付方式 | 狀態 |
|---|---|---|---|---|---|---|---|---|
| [apporo_ha_multi_ha_core](https://github.com/WOOWTECH/apporo_ha_multi_ha_core) | 預設分支（`main`） | `apporo_ha_core_1` | `apporo_ha_core_1`／stable | `apporo_ha_core_1` | ✓ | — | 本機建置（aarch64、amd64、armhf、armv7、i386） | 已同步 |
| [apporo_ha_multi_ha_core](https://github.com/WOOWTECH/apporo_ha_multi_ha_core) | 預設分支（`main`） | `apporo_ha_core_2` | `apporo_ha_core_2`／stable | `apporo_ha_core_2` | ✓ | — | 本機建置（aarch64、amd64、armhf、armv7、i386） | 已同步 |
| [apporo_ha_multi_ha_core](https://github.com/WOOWTECH/apporo_ha_multi_ha_core) | 預設分支（`main`） | `apporo_ha_core_3` | `apporo_ha_core_3`／stable | `apporo_ha_core_3` | ✓ | — | 本機建置（aarch64、amd64、armhf、armv7、i386） | 已同步 |
| [apporo_ha_multi_ha_core](https://github.com/WOOWTECH/apporo_ha_multi_ha_core) | 預設分支（`main`） | `apporo_ha_core_4` | `apporo_ha_core_4`／stable | `apporo_ha_core_4` | ✓ | — | 本機建置（aarch64、amd64、armhf、armv7、i386） | 已同步 |
| [apporo_ha_multi_ha_core](https://github.com/WOOWTECH/apporo_ha_multi_ha_core) | 預設分支（`main`） | `apporo_ha_core_5` | `apporo_ha_core_5`／stable | `apporo_ha_core_5` | ✓ | — | 本機建置（aarch64、amd64、armhf、armv7、i386） | 已同步 |
| [woow-lan-gateway](https://github.com/WOOWTECH/woow-lan-gateway) | 正式 Release（`main`） | `app` | `woow_lan_gateway`／stable | `woow-lan-gateway` | ✓ | `test.yml` | 本機建置（amd64） | 已同步 |
| [woowtech_ha_multi_ha_core](https://github.com/WOOWTECH/woowtech_ha_multi_ha_core) | 正式 Release（`main`） | `woow_ha_core_1` | `woow_ha_core_1`／stable | `woow_ha_core_1` | ✓ | `release.yml`（amd64 建置） | 本機建置（aarch64、amd64、armhf、armv7、i386） | 已同步 |
| [woowtech_ha_multi_ha_core](https://github.com/WOOWTECH/woowtech_ha_multi_ha_core) | 正式 Release（`main`） | `woow_ha_core_2` | `woow_ha_core_2`／stable | `woow_ha_core_2` | ✓ | `release.yml`（amd64 建置） | 本機建置（aarch64、amd64、armhf、armv7、i386） | 已同步 |
| [woowtech_ha_multi_ha_core](https://github.com/WOOWTECH/woowtech_ha_multi_ha_core) | 正式 Release（`main`） | `woow_ha_core_3` | `woow_ha_core_3`／stable | `woow_ha_core_3` | ✓ | `release.yml`（amd64 建置） | 本機建置（aarch64、amd64、armhf、armv7、i386） | 已同步 |
| [woowtech_ha_multi_ha_core](https://github.com/WOOWTECH/woowtech_ha_multi_ha_core) | 正式 Release（`main`） | `woow_ha_core_4` | `woow_ha_core_4`／stable | `woow_ha_core_4` | ✓ | `release.yml`（amd64 建置） | 本機建置（aarch64、amd64、armhf、armv7、i386） | 已同步 |
| [woowtech_ha_multi_ha_core](https://github.com/WOOWTECH/woowtech_ha_multi_ha_core) | 正式 Release（`main`） | `woow_ha_core_5` | `woow_ha_core_5`／stable | `woow_ha_core_5` | ✓ | `release.yml`（amd64 建置） | 本機建置（aarch64、amd64、armhf、armv7、i386） | 已同步 |
| [Woow_haos_ha_core](https://github.com/WOOWTECH/Woow_haos_ha_core) | 預設分支（`main`） | `ha_core` | `woow_ha_core`／stable | `woow_ha_core` | ✓ | `validate.yml` | 本機建置（amd64、aarch64） | 已同步 |
| [Woow_ha_ai_mcp](https://github.com/WOOWTECH/Woow_ha_ai_mcp) | 預設分支（`master`） | `homeassistant-addon-dev` | `ha_mcp_dev`／prerelease | `ha_mcp_dev` | — | — | — | 開發通道，不進 stable |
| [Woow_ha_ai_mcp](https://github.com/WOOWTECH/Woow_ha_ai_mcp) | 預設分支（`master`） | `homeassistant-addon-webhook-proxy-dev` | `ha_mcp_webhook_proxy_dev`／prerelease | `ha_mcp_webhook_proxy_dev` | — | — | — | 開發通道，不進 stable |
| [Woow_ha_ai_mcp](https://github.com/WOOWTECH/Woow_ha_ai_mcp) | 預設分支（`master`） | `homeassistant-addon-webhook-proxy` | `ha_mcp_webhook_proxy`／stable | `ha_mcp_webhook_proxy` | ✓ | — | 本機建置（aarch64、amd64） | 已同步 |
| [Woow_ha_ai_mcp](https://github.com/WOOWTECH/Woow_ha_ai_mcp) | 預設分支（`master`） | `homeassistant-addon` | `ha_mcp`／stable | `ha_mcp` | ✓ | —；各架構映像 digest | 預建映像（aarch64、amd64） | 已同步 |
| [Woow_ha_cloudflare_tunnel_webgui](https://github.com/WOOWTECH/Woow_ha_cloudflare_tunnel_webgui) | 正式 Release（`main`） | `cloudflared` | `cloudflared`／stable | `cloudflared` | ✓ | `build.yaml`；各架構映像 digest | 預建映像（aarch64、amd64） | 已同步 |
| [Woow_ha_code_server_add_on](https://github.com/WOOWTECH/Woow_ha_code_server_add_on) | 正式 Release（`main`） | `.` | `woow_ha_code_server`／stable | `woow_ha_code_server` | ✓ | `build.yml`；各架構映像 digest | 預建映像（amd64、aarch64） | 已同步 |
| [Woow_ha_dnsmasq_dhcp_add_on](https://github.com/WOOWTECH/Woow_ha_dnsmasq_dhcp_add_on) | 正式 Release（`main`） | `dnsmasq-dhcp` | `dnsmasq-dhcp`／stable | `dnsmasq-dhcp` | ✓ | —；各架構映像 digest | 預建映像（aarch64、amd64） | 已同步 |
| [Woow_ha_emqx](https://github.com/WOOWTECH/Woow_ha_emqx) | 正式 Release（`main`） | `emqx` | `woow-emqx`／stable | `emqx` | ✓ | `release.yml`（amd64 建置） | 本機建置（aarch64、amd64） | 已同步 |
| [Woow_ha_frigate_add_on](https://github.com/WOOWTECH/Woow_ha_frigate_add_on) | 預設分支（`main`） | `frigate` | `frigate`／stable | `frigate` | ✓ | —；各架構映像 digest | 預建映像（amd64、aarch64） | 已同步 |
| [Woow_ha_hermes_add_on](https://github.com/WOOWTECH/Woow_ha_hermes_add_on) | 正式 Release（`main`） | `hermes` | `woow-hermes`／stable | `woow-hermes` | ✓ | `publish-hermes-addon-images.yml`；各架構映像 digest | 預建映像（amd64） | 已同步 |
| [Woow_ha_immich](https://github.com/WOOWTECH/Woow_ha_immich) | 正式 Release（`main`） | `woow-immich` | `woow-immich`／stable | `woow-immich` | ✓ | `release.yml`（amd64 建置） | 本機建置（aarch64、amd64） | 已同步 |
| [Woow_ha_jellyfin_add_on](https://github.com/WOOWTECH/Woow_ha_jellyfin_add_on) | 預設分支（`main`） | `jellyfin` | `jellyfin`／stable | `jellyfin` | ✓ | —；各架構映像 digest | 預建映像（aarch64、amd64） | 已同步 |
| [Woow_ha_knxd_add_on](https://github.com/WOOWTECH/Woow_ha_knxd_add_on) | 正式 Release（`main`） | `knxd` | `knxd`／stable | `knxd` | ✓ | `release.yml`（amd64 建置）；各架構映像 digest | 預建映像（armhf、armv7、aarch64、amd64、i386） | 已同步 |
| [Woow_ha_matter_hub_add_on](https://github.com/WOOWTECH/Woow_ha_matter_hub_add_on) | 正式 Release（`main`） | `hamh-alpha` | `hamh-alpha`／prerelease | `hamh-alpha` | — | — | — | 開發通道，不進 stable |
| [Woow_ha_matter_hub_add_on](https://github.com/WOOWTECH/Woow_ha_matter_hub_add_on) | 正式 Release（`main`） | `hamh-testing` | `hamh-testing`／prerelease | `hamh-testing` | — | — | — | 開發通道，不進 stable |
| [Woow_ha_matter_hub_add_on](https://github.com/WOOWTECH/Woow_ha_matter_hub_add_on) | 正式 Release（`main`） | `hamh` | `hamh`／stable | `hamh` | ✓ | —；各架構映像 digest | 預建映像（aarch64、amd64） | 已同步 |
| [Woow_ha_mcp_addons](https://github.com/WOOWTECH/Woow_ha_mcp_addons) | 預設分支（`claude-delivery`） | `addons/n8n` | `woow_mcp_n8n`／stable | `woow_mcp_n8n` | ✓ | —；各架構映像 digest | 預建映像（amd64） | 已同步 |
| [Woow_ha_mcp_addons](https://github.com/WOOWTECH/Woow_ha_mcp_addons) | 預設分支（`claude-delivery`） | `addons/odoo` | `woow_mcp_odoo`／stable | `woow_mcp_odoo` | ✓ | —；各架構映像 digest | 預建映像（amd64） | 已同步 |
| [Woow_ha_mcp_addons](https://github.com/WOOWTECH/Woow_ha_mcp_addons) | 預設分支（`claude-delivery`） | `addons/hermes` | `woow_mcp_hermes`／stable | `woow_mcp_hermes` | ✓ | —；各架構映像 digest | 預建映像（amd64） | 已同步 |
| [Woow_ha_mcp_addons](https://github.com/WOOWTECH/Woow_ha_mcp_addons) | 預設分支（`claude-delivery`） | `addons/opendesign` | `woow_mcp_opendesign`／stable | `woow_mcp_opendesign` | ✓ | —；各架構映像 digest | 預建映像（amd64） | 已同步 |
| [Woow_ha_mcp_addons](https://github.com/WOOWTECH/Woow_ha_mcp_addons) | 預設分支（`claude-delivery`） | `addons/emqx` | `woow_mcp_emqx`／stable | `woow_mcp_emqx` | ✓ | —；各架構映像 digest | 預建映像（amd64） | 已同步 |
| [Woow_ha_mcp_addons](https://github.com/WOOWTECH/Woow_ha_mcp_addons) | 預設分支（`claude-delivery`） | `addons/litellm` | `woow_mcp_litellm`／stable | `woow_mcp_litellm` | ✓ | —；各架構映像 digest | 預建映像（amd64） | 已同步 |
| [Woow_ha_mcp_addons](https://github.com/WOOWTECH/Woow_ha_mcp_addons) | 預設分支（`claude-delivery`） | `addons/nextcloud` | `woow_mcp_nextcloud`／stable | `woow_mcp_nextcloud` | ✓ | —；各架構映像 digest | 預建映像（amd64） | 已同步 |
| [Woow_ha_music_assistant_add_on](https://github.com/WOOWTECH/Woow_ha_music_assistant_add_on) | 正式 Release（`main`） | `local_audio` | `local_audio`／stable | `local_audio` | ✓ | —；各架構映像 digest | 預建映像（amd64、aarch64） | 已同步 |
| [Woow_ha_music_assistant_add_on](https://github.com/WOOWTECH/Woow_ha_music_assistant_add_on) | 正式 Release（`main`） | `music_assistant` | `music_assistant`／stable | `music_assistant` | ✓ | —；各架構映像 digest | 預建映像（amd64、aarch64） | 已同步 |
| [Woow_ha_music_assistant_add_on](https://github.com/WOOWTECH/Woow_ha_music_assistant_add_on) | 正式 Release（`main`） | `music_assistant_beta` | `music_assistant_beta`／prerelease | `music_assistant_beta` | — | — | — | 開發通道，不進 stable |
| [Woow_ha_music_assistant_add_on](https://github.com/WOOWTECH/Woow_ha_music_assistant_add_on) | 正式 Release（`main`） | `music_assistant_dev` | `music_assistant_dev`／prerelease | `music_assistant_dev` | — | — | — | 開發通道，不進 stable |
| [Woow_ha_music_assistant_add_on](https://github.com/WOOWTECH/Woow_ha_music_assistant_add_on) | 正式 Release（`main`） | `music_assistant_nightly` | `music_assistant_nightly`／prerelease | `music_assistant_nightly` | — | — | — | 開發通道，不進 stable |
| [Woow_ha_music_assistant_add_on](https://github.com/WOOWTECH/Woow_ha_music_assistant_add_on) | 正式 Release（`main`） | `netease_cloud_music_api` | `netease_cloud_music_api`／stable | `netease_cloud_music_api` | ✓ | — | 本機建置（aarch64、amd64） | 已同步 |
| [Woow_ha_music_assistant_add_on](https://github.com/WOOWTECH/Woow_ha_music_assistant_add_on) | 正式 Release（`main`） | `ytm_po_token_generator` | `ytm_po_token_generator`／stable | `ytm_po_token_generator` | ✓ | —；各架構映像 digest | 預建映像（amd64、aarch64） | 已同步 |
| [Woow_ha_n8n](https://github.com/WOOWTECH/Woow_ha_n8n) | 正式 Release（`main`） | `n8n` | `woow-n8n`／stable | `n8n` | ✓ | `publish-n8n-addon-images.yml`；各架構映像 digest | 預建映像（aarch64、amd64） | 已同步 |
| [Woow_ha_nextcloud](https://github.com/WOOWTECH/Woow_ha_nextcloud) | 正式 Release（`main`） | `woow-nextcloud-office` | `woow-nextcloud-office`／stable | `woow-nextcloud-office` | ✓ | `publish-nextcloud-addon-images.yml`；各架構映像 digest | 預建映像（amd64） | 已同步 |
| [Woow_ha_nginxpm](https://github.com/WOOWTECH/Woow_ha_nginxpm) | 預設分支（`main`） | `nginxpm` | `woow-nginxproxymanager`／stable | `woow-nginxproxymanager` | ✓ | — | 本機建置（aarch64、amd64） | 已同步 |
| [Woow_ha_odoo](https://github.com/WOOWTECH/Woow_ha_odoo) | 正式 Release（`main`） | `odoo18ce` | `odoo18ce`／stable | `odoo18ce` | ✓ | `ci.yml`、`release.yml`；各架構映像 digest | 預建映像（amd64、aarch64） | 已同步 |
| [Woow_ha_omnigent_addon](https://github.com/WOOWTECH/Woow_ha_omnigent_addon) | 正式 Release（`main`） | `omnigent` | `woow-omnigent`／stable | `omnigent` | ✓ | `publish-omnigent-addon-images.yml`；各架構映像 digest | 預建映像（amd64、aarch64） | 已同步 |
| [Woow_ha_opendesign_add_on](https://github.com/WOOWTECH/Woow_ha_opendesign_add_on) | 正式 Release（`main`） | `.` | `woow_ha_opendesign`／stable | `woow_ha_opendesign` | ✓ | `build.yml`；各架構映像 digest | 預建映像（amd64、aarch64） | 已同步 |
| [Woow_ha_pi_agent_add_on](https://github.com/WOOWTECH/Woow_ha_pi_agent_add_on) | 正式 Release（`main`） | `.` | `woow_ha_pi_agent`／stable | `woow_ha_pi_agent` | ✓ | `build.yml`；各架構映像 digest | 預建映像（amd64、aarch64） | 已同步 |
| [Woow_ha_vpn_headscale_package](https://github.com/WOOWTECH/Woow_ha_vpn_headscale_package) | 正式 Release（`main`） | `headscale` | `woow-headscale`／stable | `headscale` | ✓ | `release.yml`（amd64 建置） | 本機建置（aarch64、amd64） | 已同步 |
| [Woow_ha_vpn_tailscale_package](https://github.com/WOOWTECH/Woow_ha_vpn_tailscale_package) | 正式 Release（`main`） | `tailscale` | `woow-tailscale`／stable | `woow-tailscale` | ✓ | `build.yml` | 本機建置（aarch64、amd64） | 已同步 |
| [Woow_ha_vscode_add_on](https://github.com/WOOWTECH/Woow_ha_vscode_add_on) | 預設分支（`main`） | `vscode` | `vscode`／stable | `vscode` | — | — | — | 退役，不發布 |

## 不納入的來源

| 來源 | 原因 |
|---|---|
| [haos-enrollment-bridge](https://github.com/WOOWTECH/haos-enrollment-bridge) | 已 archived；不重新上架（1 個 context） |
| [Woow_ha_community_add_ons](https://github.com/WOOWTECH/Woow_ha_community_add_ons) | 已 archived；不重新上架（47 個 context） |
| [Woow_ha_multi_ha_core_1](https://github.com/WOOWTECH/Woow_ha_multi_ha_core_1) | 已 archived；不重新上架（1 個 context） |
| [Woow_ha_multi_ha_core_2](https://github.com/WOOWTECH/Woow_ha_multi_ha_core_2) | 已 archived；不重新上架（1 個 context） |
| [Woow_ha_multi_ha_core_3](https://github.com/WOOWTECH/Woow_ha_multi_ha_core_3) | 已 archived；不重新上架（1 個 context） |
| [Woow_ha_multi_ha_core_4](https://github.com/WOOWTECH/Woow_ha_multi_ha_core_4) | 已 archived；不重新上架（1 個 context） |
| [Woow_ha_multi_ha_core_5](https://github.com/WOOWTECH/Woow_ha_multi_ha_core_5) | 已 archived；不重新上架（1 個 context） |
| [Woow_immich_docker_compose_all](https://github.com/WOOWTECH/Woow_immich_docker_compose_all) | 已 archived；不重新上架（1 個 context） |
| [Odoo_pos_self_checkout_enhance](https://github.com/WOOWTECH/Odoo_pos_self_checkout_enhance) | `ha-addon-escpos-print-proxy` 只有原始碼、未上架、沒有 CI；列為候選，需負責人確認權威與相容性後才登錄 |
| private repo（3 個） | 公開 Store 不得輸出 private 內容；consumer 也會拒絕 private 來源 |
| `Woow_ha_ai_mcp` 的 `tests/haos_image_build/screenshot_engine_mock` | 測試夾具（slug `puppet`），不是 addon |

開發／測試通道（`ha_mcp_dev`、`ha_mcp_webhook_proxy_dev`、`hamh-alpha`、`hamh-testing`、`music_assistant_beta`、`music_assistant_dev`、`music_assistant_nightly`）會出現在來源通知裡，但 consumer 只取 stable，不會進入 Store 或 Local Download。
`woow_ha_core` 與 `local_audio` 的 manifest 自己標為 `stage: experimental`，經負責人決定保留在 stable catalog；`Woow_ha_mcp_addons` 的七支 MCP Server 也是 `stage: experimental`，負責人 2026-10-09 決定上架 stable catalog（該 repo 同時保留自己的 store；發佈把關在它自己的建置 VM 與映像驗證，GitHub 上沒有 required workflow，Store 仍逐架構驗證已公開映像）。
`vscode`（`Woow_ha_vscode_add_on`）已退役並由不同的 `woow_ha_code_server` 取代，不會重新上架。

## 維運

- **新增來源**
  1. 確認 repo 是 public、未 archived、manifest 合法，且 slug 不和既有項目撞名。預設分支**不能被 force push**：Store 只接受從上一版延續下來的 commit，鏡像同步也必須一般 commit 疊在上一版上（Dnsmasq 的 `mirror-sync.yml` 自 2026-09-03 起、Frigate／Jellyfin／Matter Hub／Music Assistant 的自 2026-10-07 起都是這樣；已停用的 `Woow_ha_vscode_add_on` 鏡像仍會 force push，重新啟用前要先改）。
  2. 決定 `ref_policy`（`main` 或 `release`）與 `required_workflows`。
  3. 在 `registry.json` 加入映射並跑 `test_addon_sync.py`。
  4. 在來源 repo 加入 `woow-addon-sync.yml`（可參考 `Woow_ha_vpn_tailscale_package`），job 以 `uses: WOOWTECH/Woow_HA_App_Store/.github/workflows/woow-addon-publish.yml@main` 呼叫共用的發布 workflow，並加第二個 job `notify-store`（照抄 `Woow_ha_vpn_tailscale_package` 的）：`needs: publish`，只在 `needs.publish.outputs.ready == 'true'` 時執行，`permissions: {}`，用 secret `APP_STORE_DISPATCH_TOKEN` 對 Store 送 `repository_dispatch`（`event_type: woow-addon-ready`），讓 Store 幾分鐘內同步，不必等排程。來源 repo 要設這個 secret；沒設時 job 只顯示警告、不失敗，新版本等下一次排程同步。目前（2026-10-13）只有 `Woow_ha_odoo` 設了，其他來源 repo 的 token 待建立與分發。registry 變更須先經 PR 合併到 Store `main`。
  5. 確認來源的 `woow-addon-sync/notification.json` 已產生後，以 `only=<id>` 手動執行 Store 同步。
  6. 核對 Store 目錄、`catalog.json` 與 ha-rebrand `sync-state.json` 的 catalog ID 一致。
- **發布工具**：來源 repo 不再釘選 Store commit，一律呼叫 `woow-addon-publish.yml@main`，每次執行都用 Store `main` 的程式與 registry；改 `ref_policy` 或 `required_workflows` 只要改 Store 的 `registry.json`，不必動來源 repo。consumer 照舊用 Store `main` 的 registry 重新檢查。代價是 Store `main` 對 `.addon-sync/` 或 `woow-addon-publish.yml` 的變更會在各來源 repo 下一次發布時、以該 repo 自己的 `contents: write` token 執行，所以 Store `main` 有保護規則，這些變更一律要經過審查（見下方「Store `main` 保護」）。共用 workflow 只用呼叫端的 `GITHUB_TOKEN`，不接收其他 secret（`test_addon_sync.py` 檢查）；送 `woow-addon-ready` 的 token 只在來源 repo 自己的 `notify-store` job 裡用，靠共用 workflow 的 output `ready` 決定要不要送。來源 repo 的 `woow-addon-sync.yml` 本身（觸發條件、`if` 條件）改動時，有 ruleset 的 repo（例如 `Woow_ha_odoo`）要走 PR；fork `Woow_ha_ai_mcp` 從上游帶來的 dev 發布 workflow 會在 push 到 master 時執行：`Publish Dev Channel`（`publish-dev.yml`）已於 2026-10-13 手動停用，所以只改 `.github/workflows/` 的 push 只會跑 `woow-addon-sync.yml`；改到 `src/**`、`homeassistant-addon*/**` 或 `pyproject.toml` 的 push 仍會觸發 `addon-publish-dev.yml`（建 dev 映像並推一個改版號的 commit）與 `notify-dev-channel.yml`。
- **正式 Release**（ADR-0002：只有正式 Release 才能出貨）：來源 repo 在自己的 CI 通過後，以 job `uses: WOOWTECH/Woow_HA_App_Store/.github/workflows/woow-addon-release.yml@main` 呼叫共用的發 Release workflow（`addon_sync.py release`）。它讀 Store `main` 的 registry，替還沒有 Release 的 stable addon 版本在該 commit 發正式 Release：單一 addon 的 repo tag 是 `v<version>`，多個 addon 的 repo 每個升版的 addon 各一個 `<slug>-v<version>`；已發過的版本不動，同一個 commit 上已經有同名 tag 時（例如 OpenDesign 由維護者推 tag 發映像）直接在該 tag 發 Release；tag 指向別的 commit 時擋下，等人處理。用 `GITHUB_TOKEN` 發的 Release 不會觸發其他 workflow，所以來源的 `woow-addon-sync.yml` 要加 `workflow_run` 觸發（呼叫發 Release 的那個 workflow）。已發過 Release 的版本不重建映像（同版號的映像不可變）。mirror repo 由 `mirror-sync` 在推送後對新的 commit 發 Release，`required_workflows` 留空：`mirror-sync` 的 run 掛在推送前的 commit 上，不能當成新 commit 的 CI 證明，所以只靠各架構映像就緒的檢查。要求所有 action 釘 commit 的來源 repo（OpenDesign）把這個 workflow 也釘在 Store commit 上；被釘住的 workflow 仍會讀 Store `main` 的程式與 registry，只有 workflow 檔本身改動時才要更新釘選。
  切換一個來源：先用 `addon_sync.py release --apply` 對目前預設分支的 commit 補發現行版本的 Release（種子 Release，避免 `No stable release` 或版本倒退），再推來源 repo 的 workflow 變更，最後在 `registry.json` 改成 `ref_policy: release` 並開 PR。
- **失敗處理**：看 Store run 頁面的 `WOOW addon blocked／waiting` 註記。修正來源後，先重跑來源的通知 workflow，再重跑 Store 同步。被擋的項目保留舊版，不會清空。映像 tag 在驗證後被改寫時會被擋下，這時要發新版本，不要覆寫 tag。
- **排程被停用**：public repo 若 60 天沒有活動，GitHub 會自動停用其排程（來源的通知 workflow 平常很少 commit，最容易遇到）。push 與 workflow_run 觸發不受影響；在 Actions 頁面按 Enable workflow，或用 `PUT /repos/{owner}/{repo}/actions/workflows/{id}/enable` 重新啟用。
- **停止同步**：停用 `sync-upstreams.yml`（必要時再停用來源通知）。要回復時，針對特定同步 commit 做 revert 並開 PR 合併，不要 force push（規則也會擋）。
- **輪替 rebrand deploy key**
  1. 產生新的 ed25519 金鑰。
  2. 在 ha-rebrand 的 Deploy keys 新增它（write）。
  3. 用 `gh secret set REBRAND_SYNC_SSH_KEY --env store-sync -R WOOWTECH/Woow_HA_App_Store` 經 stdin 寫入私鑰。
  4. 手動跑一次 Store 同步，確認 rebrand 推送成功。
  5. 刪除舊 key，並刪除本機私鑰。
- **輪替 Store 同步 deploy key**：同上，但在 Store 的 Deploy keys 新增（write），寫入 `gh secret set STORE_SYNC_DEPLOY_KEY --env store-sync -R WOOWTECH/Woow_HA_App_Store`，手動跑同步確認 Store commit 推送成功後再刪舊 key。ruleset 的 bypass 是「所有 deploy key」，所以換 key 不必改 ruleset。也因此 Store **不要再新增其他 write deploy key**，否則它也能跳過審查。
- **Store `main` 保護**（負責人 2026-10-12 決定）
  - ruleset 擋刪除與 force push，並要求 PR＋1 個 approval（推新 commit 後舊 approval 失效）。
  - **唯一例外是 deploy key**：同步機器人用 `STORE_SYNC_DEPLOY_KEY` 直接寫 `catalog.json` 與 addon 目錄。管理員（`WOOWTECH`）也不能跳過。
  - 兩把 deploy key 都放在 `store-sync` environment，只有 `main` 上的 run 拿得到；workflow 自己的 `GITHUB_TOKEN` 是唯讀。**不要把 GitHub Actions 或任何角色加進 bypass**，否則任何分支上的 workflow 都能不經審查改 `main`。
  - 負責人用兩個帳號作業：一個開 PR、另一個 approve。
  - ha-rebrand 是免費個人帳號下的 private repo，GitHub 不提供分支保護；已接受此風險，靠「rebrand key 只有 Store `main` 拿得到」補償。
