# Woow Code Server（Home Assistant Add-on）

[![HA add-on](https://img.shields.io/badge/Home%20Assistant-Add--on-41BDF5)](https://www.home-assistant.io/)
[![code-server](https://img.shields.io/badge/code--server-4.135.0-blueviolet)](https://github.com/coder/code-server)
[![pi-coding-agent](https://img.shields.io/badge/pi--coding--agent-0.83.0-blue)](https://www.npmjs.com/package/@earendil-works/pi-coding-agent)
[![ACP](https://img.shields.io/badge/ACP%20client-formulahendry.acp--client%400.2.0-green)](https://open-vsx.org/extension/formulahendry/acp-client)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[English](README.md) · **繁體中文**

把 [`code-server`](https://github.com/coder/code-server)（瀏覽器版 VS Code）包成 Home Assistant Supervisor add-on，疊在 HA Community App Store 的 [Studio Code Server](https://github.com/hassio-addons/addon-vscode) 上——上游提供的一切（HA ingress、`ha` CLI、Home Assistant/YAML/MDI extension）完全保留。在上面加的是：[pi coding agent](https://github.com/earendil-works/pi)、[pi-acp](https://www.npmjs.com/package/pi-acp)、以及預先接好線的 [ACP Client](https://open-vsx.org/extension/formulahendry/acp-client) 聊天側欄。

這是 WOOWTECH 三個對齊的 code-server 部署之一——本 add-on、一份 [podman package](https://github.com/WOOWTECH/Woow_podman_code_server_package)、以及一份 [k3s Helm chart](https://github.com/WOOWTECH/Woow_k3s_code_server_package)——三者共用同一個 pi 版本與 pi 狀態目錄結構。詳見 [`PARITY_CONTRACT.md`](PARITY_CONTRACT.md)。

這裡的 pi 狀態**只屬於本 add-on**——不跟另一個獨立的 `Woow HA Pi Agent` add-on 共用，也不跟 podman/k3s 部署共用。

---

## 提供什麼

| | |
|---|---|
| **UI** | Home Assistant 側邊欄（ingress），第一次開機自動啟用 |
| **IDE** | code-server 4.135.0，疊在 `hassio-addons/vscode:7.0.0` 上——HA/YAML/MDI extension、`ha` CLI、oh-my-zsh 全部保留 |
| **Agent** | pi 0.83.0，右側 ACP chat panel 直接可用；每個 terminal 的 PATH 上都有 `pi` |
| **Workspace** | 可設定的 `config_path`（預設 `/share/projects`） |
| **持久化** | pi 狀態在本 add-on 自己的 `/data/pi-agent`；IDE 設定在 `/data/vscode`（兩者都由 Supervisor 管理，都會被備份） |
| **備援** | 萬一聊天 webview 打不開：一個永遠可用的 terminal `pi` 任務、以及一個選用的 HTTP Basic 驗證直連埠 |

## pi 接線的原理 —— 30 秒版

新增一個 s6-rc oneshot「`init-woow`」，在上游自己的 `init-code-server` **之前**執行（這是本 add-on 加的一條依賴邊，完全不改動任何上游檔案）。它從跟 podman package、k3s chart 相同的骨架初始化 `/data/pi-agent`，用冪等的 `jq` merge 把 ACP + workspace-trust 的必要 key 併入 `settings.json`，並把 `PI_*` 環境變數發布給之後啟動的每一個服務——包括 code-server 自己的 extension host 和每一個內建終端機（這點是直接對著跑起來的行程的 `/proc/<pid>/environ` 驗證過的，不是憑空宣稱）。

```
init-woow（新）  →  init-code-server（上游）  →  code-server（上游、longrun）
     │
     ├─ pi-seed → /data/pi-agent（三個部署逐位元組相同的腳本）
     ├─ jq merge → /data/vscode/User/settings.json
     └─ /run/s6/container_environment/PI_* → code-server + extension host + 每個終端機都繼承得到
```

完整的 s6-rc 圖與「為什麼這個 settings 合併順序在 upstream 自己的預設邏輯面前是安全的」證明，見 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。

## 安裝

透過 WOOWTECH HA App Store，或直接加這個 repo：

1. HA → Settings → Add-ons → Add-on Store → ⋮ → Repositories → 加入 `https://github.com/WOOWTECH/Woow_ha_code_server_add_on`。
2. 安裝 **Woow Code Server**，啟動它。
3. 從側邊欄打開 Web UI。
4. 開一個 terminal 跑 `pi login`——這個 add-on 的 pi 在你做這件事之前是沒有任何憑證的。

完整檢查清單：[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)。

## ACP 聊天 webview

已經對著一台實際在跑的 Home Assistant 完整驗證過：HA 的 ingress 來源是瀏覽器信任的安全 context，ingress 的路徑前綴不會干擾 webview 的 ServiceWorker 註冊（code-server 本來就用相對路徑產生每一個資源網址），而且一個內建的 webview（Markdown 預覽）透過真正的 ingress 網址渲染成功、ServiceWorker 也正確啟用了。兩分鐘的手動驗證步驟見 [`tests/smoke-acp-webview.md`](tests/smoke-acp-webview.md)；如果你的環境萬一表現不一樣，F1（永遠可用的 terminal 任務）/ F2（選用直連埠）備援階梯見 [`DOCS.md`](DOCS.md)。

**這一段之所以特別寫出來**：VS Code 的 webview 是透過 ServiceWorker 送達內容的，而瀏覽器只允許在「安全」的 context（瀏覽器信任的憑證，或 `localhost`）裡註冊 ServiceWorker——使用者在頁面層級點過的自簽憑證「繼續前往」不算數，SW 那層還是會擋。這正是姊妹的 podman package 至今聊天面板在純 HTTP 區網下打不開的原因。HA 這邊因為 Supervisor ingress 本身就跑在瀏覽器信任的 HTTPS 來源後面，這個限制天生就滿足；上面那句「已完整驗證」指的正是這件事真的被測過，不是假設。

## 目錄結構

```
config.yaml / build.yaml         HA add-on 定義 + 各架構的 base image
Dockerfile                       在 hassio-addons/vscode 上疊 Node 22 + pi + pi-acp + ACP extension
rootfs/
  usr/local/bin/pi-code          HOME 轉向的 ACP 指令 wrapper（三個部署逐位元組相同）
  usr/local/bin/pi-seed          冪等的 pi 狀態初始化腳本（逐位元組相同）
  etc/profile.d/pi.sh            terminal pi 的環境變數設定（逐位元組相同）
  opt/acp-settings.json          settings.json 需要的 6 個 key
  opt/SHA256SUMS                 上面三個共用檔案的雜湊值
  etc/s6-overlay/scripts/init-woow           新 oneshot 的實際腳本
  etc/s6-overlay/s6-rc.d/init-woow/          type=oneshot，up 指向上面那支腳本
  etc/s6-overlay/s6-rc.d/init-code-server/dependencies.d/init-woow   依賴邊（上游服務、我們加的標記檔）
  etc/s6-overlay/s6-rc.d/nginx-direct/       F2 備援 longrun（依 direct_password 自我開關）
  etc/s6-overlay/user-bundles.d/user/contents.d/{init-woow,nginx-direct}  s6 bundle 成員標記
docs/ARCHITECTURE.md             s6-rc 圖、settings 合併安全性證明、「為什麼不能加 nginx shim」
docs/DEPLOYMENT.md               安裝檢查清單、上架步驟
DOCS.md                          HA add-on 頁面文字（設定說明、首次使用、備援階梯）
tests/
  lib/parity.sh                  通用轉接器，跟 podman/k3s 兩個 repo 共用（PARITY_TARGET=ha）
  smoke-container.sh / smoke-acp.sh / smoke-pi-integration.sh   跟另外兩個 repo 相同的斷言
  smoke-addon.sh                 透過 Supervisor REST API 檢查 add-on 自己的狀態
  smoke-acp-webview.md           兩分鐘的手動瀏覽器驗收步驟
translations/{en,zh-tw}.yaml     每個選項的 HA UI 文字
.github/workflows/build.yml      amd64 + aarch64 CI，push/release 推到 ghcr，含共用雜湊驗證閘門
```

## 驗收部署

```bash
# 對著一個跑起來的 container（要有辦法 exec 進去——見 tests/lib/parity.sh）：
SSHHA=/path/to/sshha.sh HA_ADDON_CONTAINER=app_woow_ha_code_server \
  PARITY_TARGET=ha bash tests/smoke-container.sh
PARITY_TARGET=ha bash tests/smoke-acp.sh
PARITY_TARGET=ha EXPECTED_PI_VERSION=0.83.0 bash tests/smoke-pi-integration.sh

# 對著 Supervisor 自己看到的 add-on 狀態：
HA_URL=https://your-ha-host HA_TOKEN=... bash tests/smoke-addon.sh
```

這三支跟容器內部相關的腳本，在開發過程中都對著一個真的建置出來的 image + 模擬的 Supervisor API 完整跑過一遍（不是憑感覺寫完就算）——實際驗證了什麼寫在 `CHANGELOG.md` 與 `docs/ARCHITECTURE.md` 裡。

## 安全

- 預設只靠 HA Supervisor ingress 這一關驗證——code-server 本身是 `--auth none`。
- `/config`、`/backup`、`/addons`、`/share`、`/ssl`、`/media` 以及其他所有 add-on 的設定都是 read-write 掛載。這個 add-on 本來就設計成對 HAOS 有很廣的存取權——把它當成對你的 Home Assistant 有 root shell 權限來看待。
- 選用的 F2 直連埠（1338）靠 `direct_password` 加一層 HTTP Basic 驗證，沒設就絕對不能對外開放這個埠。
- pi 唯一的憑證是 `/data/pi-agent/auth.json` 裡的 OAuth pair。任何拿到這個 add-on shell 的人都讀得到。

完整內容見 [`DOCS.md`](DOCS.md#security)。

## 相關

- [`Woow_podman_code_server_package`](https://github.com/WOOWTECH/Woow_podman_code_server_package) — 同一套 pi/ACP 接線，包給 rootless Podman 用
- [`Woow_k3s_code_server_package`](https://github.com/WOOWTECH/Woow_k3s_code_server_package) — 同一顆 image，用 Helm + Cloudflare Tunnel 部署到 k3s
- [ACP Client (formulahendry)](https://open-vsx.org/extension/formulahendry/acp-client) — 渲染聊天面板的 VS Code extension
- [pi-acp](https://www.npmjs.com/package/pi-acp) — 社群做的 ACP JSON-RPC → pi `--mode rpc` bridge
- [Woow_ha_pi_agent_add_on](https://github.com/WOOWTECH/Woow_ha_pi_agent_add_on) — 另一個獨立的 HA add-on，包 pi-web；跟本 add-on 不共用任何狀態

## 授權

MIT
