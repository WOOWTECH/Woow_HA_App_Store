# WOOW HA addon 來源對照

由 `WOOWTECH` 帳號的 315 個 repo 實際掃描產生（2026-10-06，掃描到第 3 層的 `config.yaml|yml|json`，並以 manifest 內容判斷，不靠 repo 名稱）。
**即時的版本、來源 SHA 與映像 digest 以 [`catalog.json`](catalog.json) 為準；映射與政策以 [`registry.json`](registry.json) 為準。** 本表只說明各來源為什麼納入或排除。

## 已登錄來源（26 個 repo、45 個 context）

「rebrand」欄＝是否已出現在 `catalog.json`（ha-rebrand 的 `release/addons/catalog.json` 與它逐位元組相同）。
「CI／映像要求」是 Store consumer 會重新檢查的條件；沒有 required workflow 的本機建置項目只做結構檢查，**不代表 Docker 建置或實機健康已驗證**（Tailscale 例外：它的 `Build` 在 CI 實際建置 amd64＋aarch64）。

| 來源 repo | 發布政策 | context | slug／通道 | Store 目錄 | rebrand | CI／映像要求 | 交付方式 | 狀態 |
|---|---|---|---|---|---|---|---|---|
| [apporo_ha_multi_ha_core](https://github.com/WOOWTECH/apporo_ha_multi_ha_core) | 預設分支（`main`） | `apporo_ha_core_1` | `apporo_ha_core_1`／stable | `apporo_ha_core_1` | ✓ | — | 本機建置（aarch64、amd64、armhf、armv7、i386） | 已同步 |
| [apporo_ha_multi_ha_core](https://github.com/WOOWTECH/apporo_ha_multi_ha_core) | 預設分支（`main`） | `apporo_ha_core_2` | `apporo_ha_core_2`／stable | `apporo_ha_core_2` | ✓ | — | 本機建置（aarch64、amd64、armhf、armv7、i386） | 已同步 |
| [apporo_ha_multi_ha_core](https://github.com/WOOWTECH/apporo_ha_multi_ha_core) | 預設分支（`main`） | `apporo_ha_core_3` | `apporo_ha_core_3`／stable | `apporo_ha_core_3` | ✓ | — | 本機建置（aarch64、amd64、armhf、armv7、i386） | 已同步 |
| [apporo_ha_multi_ha_core](https://github.com/WOOWTECH/apporo_ha_multi_ha_core) | 預設分支（`main`） | `apporo_ha_core_4` | `apporo_ha_core_4`／stable | `apporo_ha_core_4` | ✓ | — | 本機建置（aarch64、amd64、armhf、armv7、i386） | 已同步 |
| [apporo_ha_multi_ha_core](https://github.com/WOOWTECH/apporo_ha_multi_ha_core) | 預設分支（`main`） | `apporo_ha_core_5` | `apporo_ha_core_5`／stable | `apporo_ha_core_5` | ✓ | — | 本機建置（aarch64、amd64、armhf、armv7、i386） | 已同步 |
| [woow-lan-gateway](https://github.com/WOOWTECH/woow-lan-gateway) | 預設分支（`main`） | `app` | `woow_lan_gateway`／stable | `woow-lan-gateway` | ✓ | `test.yml` | 本機建置（amd64） | 已同步 |
| [woowtech_ha_multi_ha_core](https://github.com/WOOWTECH/woowtech_ha_multi_ha_core) | 預設分支（`main`） | `woow_ha_core_1` | `woow_ha_core_1`／stable | `woow_ha_core_1` | ✓ | — | 本機建置（aarch64、amd64、armhf、armv7、i386） | 已同步 |
| [woowtech_ha_multi_ha_core](https://github.com/WOOWTECH/woowtech_ha_multi_ha_core) | 預設分支（`main`） | `woow_ha_core_2` | `woow_ha_core_2`／stable | `woow_ha_core_2` | ✓ | — | 本機建置（aarch64、amd64、armhf、armv7、i386） | 已同步 |
| [woowtech_ha_multi_ha_core](https://github.com/WOOWTECH/woowtech_ha_multi_ha_core) | 預設分支（`main`） | `woow_ha_core_3` | `woow_ha_core_3`／stable | `woow_ha_core_3` | ✓ | — | 本機建置（aarch64、amd64、armhf、armv7、i386） | 已同步 |
| [woowtech_ha_multi_ha_core](https://github.com/WOOWTECH/woowtech_ha_multi_ha_core) | 預設分支（`main`） | `woow_ha_core_4` | `woow_ha_core_4`／stable | `woow_ha_core_4` | ✓ | — | 本機建置（aarch64、amd64、armhf、armv7、i386） | 已同步 |
| [woowtech_ha_multi_ha_core](https://github.com/WOOWTECH/woowtech_ha_multi_ha_core) | 預設分支（`main`） | `woow_ha_core_5` | `woow_ha_core_5`／stable | `woow_ha_core_5` | ✓ | — | 本機建置（aarch64、amd64、armhf、armv7、i386） | 已同步 |
| [Woow_haos_ha_core](https://github.com/WOOWTECH/Woow_haos_ha_core) | 預設分支（`main`） | `ha_core` | `woow_ha_core`／stable | `woow_ha_core` | ✓ | `validate.yml` | 本機建置（amd64、aarch64） | 已同步 |
| [Woow_ha_ai_mcp](https://github.com/WOOWTECH/Woow_ha_ai_mcp) | 預設分支（`master`） | `homeassistant-addon-dev` | `ha_mcp_dev`／prerelease | `ha_mcp_dev` | — | — | — | 開發通道，不進 stable |
| [Woow_ha_ai_mcp](https://github.com/WOOWTECH/Woow_ha_ai_mcp) | 預設分支（`master`） | `homeassistant-addon-webhook-proxy-dev` | `ha_mcp_webhook_proxy_dev`／prerelease | `ha_mcp_webhook_proxy_dev` | — | — | — | 開發通道，不進 stable |
| [Woow_ha_ai_mcp](https://github.com/WOOWTECH/Woow_ha_ai_mcp) | 預設分支（`master`） | `homeassistant-addon-webhook-proxy` | `ha_mcp_webhook_proxy`／stable | `ha_mcp_webhook_proxy` | ✓ | — | 本機建置（aarch64、amd64） | 已同步 |
| [Woow_ha_ai_mcp](https://github.com/WOOWTECH/Woow_ha_ai_mcp) | 預設分支（`master`） | `homeassistant-addon` | `ha_mcp`／stable | `ha_mcp` | ✓ | —各架構映像 digest | 預建映像（aarch64、amd64） | 已同步 |
| [Woow_ha_cloudflare_tunnel_webgui](https://github.com/WOOWTECH/Woow_ha_cloudflare_tunnel_webgui) | 預設分支（`main`） | `cloudflared` | `cloudflared`／stable | `cloudflared` | ✓ | `build.yaml`；各架構映像 digest | 預建映像（aarch64、amd64） | 已同步 |
| [Woow_ha_code_server_add_on](https://github.com/WOOWTECH/Woow_ha_code_server_add_on) | 預設分支（`main`） | `.` | `woow_ha_code_server`／stable | `woow_ha_code_server` | ✓ | `build.yml`；各架構映像 digest | 預建映像（amd64、aarch64） | 已同步 |
| [Woow_ha_dnsmasq_dhcp_add_on](https://github.com/WOOWTECH/Woow_ha_dnsmasq_dhcp_add_on) | 預設分支（`main`） | `dnsmasq-dhcp` | `dnsmasq-dhcp`／stable | `dnsmasq-dhcp` | ✓ | —各架構映像 digest | 預建映像（aarch64、amd64） | 已同步 |
| [Woow_ha_emqx](https://github.com/WOOWTECH/Woow_ha_emqx) | 預設分支（`main`） | `emqx` | `woow-emqx`／stable | `emqx` | ✓ | — | 本機建置（aarch64、amd64） | 已同步 |
| [Woow_ha_frigate_add_on](https://github.com/WOOWTECH/Woow_ha_frigate_add_on) | 預設分支（`main`） | `frigate` | `frigate`／stable | `frigate` | ✓ | —各架構映像 digest | 預建映像（amd64、aarch64） | 已同步 |
| [Woow_ha_hermes_add_on](https://github.com/WOOWTECH/Woow_ha_hermes_add_on) | 正式 Release（`main`） | `hermes` | `woow-hermes`／stable | `woow-hermes` | ✓ | `publish-hermes-addon-images.yml`；各架構映像 digest | 預建映像（amd64） | 已同步 |
| [Woow_ha_immich](https://github.com/WOOWTECH/Woow_ha_immich) | 預設分支（`main`） | `woow-immich` | `woow-immich`／stable | `woow-immich` | ✓ | — | 本機建置（aarch64、amd64） | 已同步 |
| [Woow_ha_jellyfin_add_on](https://github.com/WOOWTECH/Woow_ha_jellyfin_add_on) | 預設分支（`main`） | `jellyfin` | `jellyfin`／stable | `jellyfin` | ✓ | —各架構映像 digest | 預建映像（aarch64、amd64） | 已同步 |
| [Woow_ha_knxd_add_on](https://github.com/WOOWTECH/Woow_ha_knxd_add_on) | 預設分支（`main`） | `knxd` | `knxd`／stable | `knxd` | ✓ | —各架構映像 digest | 預建映像（armhf、armv7、aarch64、amd64、i386） | 已同步 |
| [Woow_ha_matter_hub_add_on](https://github.com/WOOWTECH/Woow_ha_matter_hub_add_on) | 預設分支（`main`） | `hamh-alpha` | `hamh-alpha`／prerelease | `hamh-alpha` | — | — | — | 開發通道，不進 stable |
| [Woow_ha_matter_hub_add_on](https://github.com/WOOWTECH/Woow_ha_matter_hub_add_on) | 預設分支（`main`） | `hamh-testing` | `hamh-testing`／prerelease | `hamh-testing` | — | — | — | 開發通道，不進 stable |
| [Woow_ha_matter_hub_add_on](https://github.com/WOOWTECH/Woow_ha_matter_hub_add_on) | 預設分支（`main`） | `hamh` | `hamh`／stable | `hamh` | ✓ | —各架構映像 digest | 預建映像（aarch64、amd64） | 已同步 |
| [Woow_ha_music_assistant_add_on](https://github.com/WOOWTECH/Woow_ha_music_assistant_add_on) | 預設分支（`main`） | `local_audio` | `local_audio`／stable | `local_audio` | ✓ | —各架構映像 digest | 預建映像（amd64、aarch64） | 已同步 |
| [Woow_ha_music_assistant_add_on](https://github.com/WOOWTECH/Woow_ha_music_assistant_add_on) | 預設分支（`main`） | `music_assistant` | `music_assistant`／stable | `music_assistant` | ✓ | —各架構映像 digest | 預建映像（amd64、aarch64） | 已同步 |
| [Woow_ha_music_assistant_add_on](https://github.com/WOOWTECH/Woow_ha_music_assistant_add_on) | 預設分支（`main`） | `music_assistant_beta` | `music_assistant_beta`／prerelease | `music_assistant_beta` | — | — | — | 開發通道，不進 stable |
| [Woow_ha_music_assistant_add_on](https://github.com/WOOWTECH/Woow_ha_music_assistant_add_on) | 預設分支（`main`） | `music_assistant_dev` | `music_assistant_dev`／prerelease | `music_assistant_dev` | — | — | — | 開發通道，不進 stable |
| [Woow_ha_music_assistant_add_on](https://github.com/WOOWTECH/Woow_ha_music_assistant_add_on) | 預設分支（`main`） | `music_assistant_nightly` | `music_assistant_nightly`／prerelease | `music_assistant_nightly` | — | — | — | 開發通道，不進 stable |
| [Woow_ha_music_assistant_add_on](https://github.com/WOOWTECH/Woow_ha_music_assistant_add_on) | 預設分支（`main`） | `netease_cloud_music_api` | `netease_cloud_music_api`／stable | `netease_cloud_music_api` | ✓ | — | 本機建置（aarch64、amd64） | 已同步 |
| [Woow_ha_music_assistant_add_on](https://github.com/WOOWTECH/Woow_ha_music_assistant_add_on) | 預設分支（`main`） | `ytm_po_token_generator` | `ytm_po_token_generator`／stable | `ytm_po_token_generator` | ✓ | —各架構映像 digest | 預建映像（amd64、aarch64） | 已同步 |
| [Woow_ha_n8n](https://github.com/WOOWTECH/Woow_ha_n8n) | 預設分支（`main`） | `n8n` | `woow-n8n`／stable | `n8n` | ✓ | `publish-n8n-addon-images.yml`；各架構映像 digest | 預建映像（aarch64、amd64） | 已同步 |
| [Woow_ha_nextcloud](https://github.com/WOOWTECH/Woow_ha_nextcloud) | 正式 Release（`main`） | `woow-nextcloud-office` | `woow-nextcloud-office`／stable | `woow-nextcloud-office` | ✓ | `publish-nextcloud-addon-images.yml`；各架構映像 digest | 預建映像（amd64） | 已同步 |
| [Woow_ha_nginxpm](https://github.com/WOOWTECH/Woow_ha_nginxpm) | 預設分支（`main`） | `nginxpm` | `woow-nginxproxymanager`／stable | `woow-nginxproxymanager` | ✓ | — | 本機建置（aarch64、amd64） | 已同步 |
| [Woow_ha_odoo](https://github.com/WOOWTECH/Woow_ha_odoo) | 正式 Release（`main`） | `odoo18ce` | `odoo18ce`／stable | `odoo18ce` | ✓ | `ci.yml`、`release.yml`；各架構映像 digest | 預建映像（amd64、aarch64） | 已同步 |
| [Woow_ha_omnigent_addon](https://github.com/WOOWTECH/Woow_ha_omnigent_addon) | 預設分支（`main`） | `omnigent` | `woow-omnigent`／stable | `omnigent` | ✓ | `publish-omnigent-addon-images.yml`；各架構映像 digest | 預建映像（amd64、aarch64） | 已同步 |
| [Woow_ha_opendesign_add_on](https://github.com/WOOWTECH/Woow_ha_opendesign_add_on) | 預設分支（`main`） | `.` | `woow_ha_opendesign`／stable | `woow_ha_opendesign` | ✓ | `build.yml`；各架構映像 digest | 預建映像（amd64、aarch64） | 已同步 |
| [Woow_ha_pi_agent_add_on](https://github.com/WOOWTECH/Woow_ha_pi_agent_add_on) | 預設分支（`main`） | `.` | `woow_ha_pi_agent`／stable | `woow_ha_pi_agent` | ✓ | `build.yml`；各架構映像 digest | 預建映像（amd64、aarch64） | 已同步 |
| [Woow_ha_vpn_headscale_package](https://github.com/WOOWTECH/Woow_ha_vpn_headscale_package) | 預設分支（`main`） | `headscale` | `woow-headscale`／stable | `headscale` | ✓ | — | 本機建置（aarch64、amd64） | 已同步 |
| [Woow_ha_vpn_tailscale_package](https://github.com/WOOWTECH/Woow_ha_vpn_tailscale_package) | 預設分支（`main`） | `tailscale` | `woow-tailscale`／stable | `woow-tailscale` | ✓ | `build.yml` | 本機建置（aarch64、amd64） | 已同步 |
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
| [Woow_ha_mcp_addons](https://github.com/WOOWTECH/Woow_ha_mcp_addons) | 獨立的 HA addon 商店（default branch `claude-delivery`、manifest 全為 experimental），有自己的發布線；要併入需另行決定 |
| private repo（3 個） | 公開 Store 不得輸出 private 內容；consumer 也會拒絕 private 來源 |
| `Woow_ha_ai_mcp` 的 `tests/haos_image_build/screenshot_engine_mock` | 測試夾具（slug `puppet`），不是 addon |

開發／測試通道（`ha_mcp_dev`、`ha_mcp_webhook_proxy_dev`、`hamh-alpha`、`hamh-testing`、`music_assistant_beta`、`music_assistant_dev`、`music_assistant_nightly`）會出現在來源通知裡，但 consumer 只取 stable，不會進入 Store 或 Local Download。
`woow_ha_core` 與 `local_audio` 的 manifest 自己標為 `stage: experimental`，經負責人決定保留在 stable catalog。
`vscode`（`Woow_ha_vscode_add_on`）已退役並由不同的 `woow_ha_code_server` 取代，不會重新上架。

## 維運

- **新增來源**
  1. 確認 repo 是 public、未 archived、manifest 合法，且 slug 不和既有項目撞名。預設分支**不能被 force push**：Store 只接受從上一版延續下來的 commit，鏡像同步也必須一般 commit 疊在上一版上（Frigate／Jellyfin／Matter Hub／Music Assistant 的 `mirror-sync.yml` 已於 2026-10-07 改成這樣）。
  2. 決定 `ref_policy`（`main` 或 `release`）與 `required_workflows`。
  3. 在 `registry.json` 加入映射並跑 `test_addon_sync.py`。
  4. 在來源 repo 加入 `woow-addon-sync.yml`（可參考 `Woow_ha_vpn_tailscale_package`），job 以 `uses: WOOWTECH/Woow_HA_App_Store/.github/workflows/woow-addon-publish.yml@main` 呼叫共用的發布 workflow；registry 變更須先合併到 Store `main`。
  5. 確認來源的 `woow-addon-sync/notification.json` 已產生後，以 `only=<id>` 手動執行 Store 同步。
  6. 核對 Store 目錄、`catalog.json` 與 ha-rebrand `sync-state.json` 的 catalog ID 一致。
- **發布工具**：來源 repo 不再釘選 Store commit，一律呼叫 `woow-addon-publish.yml@main`，每次執行都用 Store `main` 的程式與 registry；改 `ref_policy` 或 `required_workflows` 只要改 Store 的 `registry.json`，不必動來源 repo。consumer 照舊用 Store `main` 的 registry 重新檢查。代價是 Store `main` 對 `.addon-sync/` 或 `woow-addon-publish.yml` 的變更會在各來源 repo 下一次發布時、以該 repo 自己的 `contents: write` token 執行，所以要和 Store workflow 一樣審查。來源 repo 的 `woow-addon-sync.yml` 本身（觸發條件、`if` 條件）改動時，有 ruleset 的 repo（例如 `Woow_ha_odoo`）要走 PR；推到 fork `Woow_ha_ai_mcp` 的 master 會觸發上游的 dev 發布流程，非必要不要推。
- **失敗處理**：看 Store run 頁面的 `WOOW addon blocked／waiting` 註記。修正來源後，先重跑來源的通知 workflow，再重跑 Store 同步。被擋的項目保留舊版，不會清空。映像 tag 在驗證後被改寫時會被擋下，這時要發新版本，不要覆寫 tag。
- **排程被停用**：public repo 若 60 天沒有活動，GitHub 會自動停用其排程（來源的通知 workflow 平常很少 commit，最容易遇到）。push 與 workflow_run 觸發不受影響；在 Actions 頁面按 Enable workflow，或用 `PUT /repos/{owner}/{repo}/actions/workflows/{id}/enable` 重新啟用。
- **停止同步**：停用 `sync-upstreams.yml`（必要時再停用來源通知）。要回復時，針對特定同步 commit 做 revert，不要 force push。
- **輪替 rebrand deploy key**
  1. 產生新的 ed25519 金鑰。
  2. 在 ha-rebrand 的 Deploy keys 新增它（write）。
  3. 用 `gh secret set REBRAND_SYNC_SSH_KEY -R WOOWTECH/Woow_HA_App_Store` 經 stdin 寫入私鑰。
  4. 手動跑一次 Store 同步，確認 rebrand 推送成功。
  5. 刪除舊 key，並刪除本機私鑰。
