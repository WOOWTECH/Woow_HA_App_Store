# Woow Hermes Agent

[Hermes Agent](https://github.com/NousResearch/hermes-agent) by NousResearch, packaged from
[Woow_podman_hermes](https://github.com/WOOWTECH/Woow_podman_hermes) (the `slim` image).

## Entrances

| What | Where | Auth |
|---|---|---|
| Dashboard + chat terminal | Home Assistant sidebar (**Hermes**) | Home Assistant login, then the Hermes login |
| Dashboard + chat terminal | `http://<Home Assistant IP>:9119` | Hermes login |
| OpenAI-compatible API | `http://<Home Assistant IP>:8642/v1` | `Authorization: Bearer <Gateway API key>` |
| Webhook receiver | `http://<Home Assistant IP>:8644/webhooks/<route>` | HMAC with the webhook secret |

The sidebar and the LAN port run the same dashboard process with the same accounts, sessions,
chats, skills and settings. The sidebar goes through an adapter on port 9120 that only rewrites
URLs for the Home Assistant ingress path.

Browser-local preferences (theme, language) are stored per address, so the sidebar and the LAN
port keep their own. The LAN port is plain HTTP, so the browser disables clipboard access there.

## First start

Leave the password, API key and webhook secret empty. They are generated on the first start and
saved into the Configuration tab, where you can reveal them. Sign in with `admin` (or your
`dashboard_username`) and the dashboard password.

Provider keys (MiniMax, OpenRouter, GitHub) set here are written to Hermes only when you change
them, so keys you edit in the dashboard's Keys page are kept across restarts.

## Cloudflare Tunnel

With the Cloudflared add-on on the same Home Assistant, point public hostnames at the host ports:

```yaml
additional_hosts:
  - hostname: hermes-api.example.com
    service: http://homeassistant:8642
  - hostname: hermes-hook.example.com
    service: http://homeassistant:8644
```

Changing or disabling a host port in the Network tab breaks the matching tunnel rule.

The dashboard is not meant to be published. When you sign in to an MCP server with OAuth, the
provider sends your browser back to **Dashboard public URL**. Left empty, that is
`http://<Home Assistant IP>:9119`, which only works from the LAN. To sign in from anywhere, publish
only the callback path of the dashboard on the API hostname
(`^/api/mcp/oauth/callback/` → `http://homeassistant:9119`) and set **Dashboard public URL** to
`https://<api hostname>`.

Cloudflare limits apply to anything that goes through it, including the sidebar when Home
Assistant itself is reached through a tunnel: 100 MB request bodies and 125 s until the first
response byte (use `stream: true` for long completions).

## Web and browser tools

Web search uses DuckDuckGo (`ddgs`) and page extraction uses Parallel, both without an API key.
The browser tool drives the Chromium bundled in the image. The add-on sets these on start only
while they are empty, so a backend you pick in the dashboard stays.

## After installing

Turn on **Start on boot** and **Watchdog** on the add-on's Info tab. Home Assistant does not
switch them on for you.

## Known differences between the sidebar and the LAN port

- The sidebar and `http://<Home Assistant IP>:9119` keep separate logins. Signing in or out on one
  does not affect the other.
- The Webhooks page shows `http://localhost:8644/...`. Senders outside the add-on must use
  `http://<Home Assistant IP>:8644/webhooks/<route>` or the Cloudflare hostname.
- Through Cloudflare, a single upload is limited to 100 MB. Upload larger files on the LAN.

## Security

The agent runs shell commands with Hermes' default approval settings: low-risk commands run
directly, risky ones (deleting files, installing packages, `sudo`, piping downloads into a shell)
wait for you to approve them in the chat. Runs with nobody there to approve (scheduled jobs, the
OpenAI-compatible API and webhooks) refuse them. You can change this under Config in the
dashboard (`approvals.cron_mode`, `approvals.unattended_mode`). Anyone who can use the dashboard,
the API key, or a webhook route that triggers the agent can still run the commands that need no
approval.

Upstream Hermes auto-approves those risky commands in unattended runs, because its gateway runs in
ask mode; the add-on patches that so the deny settings apply. The add-on removes the Supervisor token from
the agent's environment. Home Assistant backups of this add-on contain its secrets and
conversation history.

Keep the generated dashboard password, or use an equally long random one. Hermes limits wrong
login attempts per client address, but it takes that address from a header the client can set, so
on the LAN port the limit can be sidestepped. A long random password cannot be guessed either way.

## Data

Hermes' home (`/opt/data`) is the add-on's config folder, `/addon_configs/<slug>/`. It is in the
add-on backup, except `logs`, `lazy-packages`, `.cache` and `.npm`. Backups are cold: Hermes stops
while the backup runs.

## Memory

Home Assistant cannot limit an add-on's memory. Hermes with a browser session can use 3-6 GiB;
the log warns when less than 4 GiB is available at start.


## Upgrading to add-on 0.1.10 / Hermes 0.22.5

The data mount, add-on options, ports and dashboard credentials are preserved.
Take a Home Assistant backup before upgrading; restore that backup to roll back
upstream database migrations.

Home Assistant's former core integration is now the official `homeassistant`
plugin. Upstream gateway startup detects an existing `HASS_TOKEN`, enabled
`platforms.homeassistant`, or selected Home Assistant toolset and attempts the
catalog migration. It retains `HASS_TOKEN`, `HASS_URL`, platform configuration
and `ha_*` tool names. Automatic installation requires network access and
`security.allow_lazy_installs`; an intentionally removed plugin is not silently
reinstalled after a successful migration.

If the integration is missing after upgrade, open Settings > Plugins and
install/enable **Home Assistant**, or use `hermes plugins install homeassistant`
for the affected profile. Check the plugin's dependency-install result and
connection status. Existing valid credentials can be reused; reconnect or issue
a new Home Assistant token only if the existing credentials no longer work.
Fresh installs should configure this integration explicitly. The HA Supervisor
bootstrap token remains isolated from Hermes and is not an integration token.

MoA is still available as a model provider with named presets (`hermes moa` and
`/moa`); it is no longer a core toolset to enable with `hermes tools enable moa`.
The add-on does not start `hermes mcp serve`; the separately packaged WOOW MCP
bridge continues to use the HTTP gateway API.

OAuth issuer validation now follows upstream. A server that advertises one
issuer but returns another must correct its OAuth metadata or callback, then
be reconnected. The old permissive issuer override is not reapplied.


<a id="paseo-remote-plugin-ha-ingress"></a>

## Paseo 插件與 Dashboard 重載（0.1.11 起）

附加元件包含 Paseo 的主機介面。插件仍由使用者在 Hermes 的 **Plugins** 頁安裝及啟用，不會因升級附加元件而自動新增插件、開放工具或要求更換模型帳號。

1. 更新附加元件並確認啟動正常。若從 HA 側欄使用 Paseo，在此附加元件的「設定」填入 **Paseo 的 Home Assistant 網址**（`paseo_ingress_url`），例如 `https://ha.example.com` 或 `http://homeassistant.local:8123`。這必須是瀏覽器實際開啟 HA 的來源，不含 `/lovelace`、`/api/hassio_ingress/…`、帳密、query 或 fragment。保存後重啟此附加元件一次。
2. 保留 **儀表板公開網址**（`public_url`）供 LAN 及 MCP OAuth 使用。兩個入口不同時，不要用 HA 網址取代它。僅使用 LAN Dashboard 時可以留空 `paseo_ingress_url`。
3. 進入 Hermes → **Plugins**，在 Git URL or owner/repo 填入 `WOOWTECH/hermes-paseo-plugin`，安裝目前公開的 `0.1.4-rc.5` 並啟用。來源為公開 GitHub，不需要 GitHub token。若 Hermes 顯示執行程序的 caution，先核對來源及權限說明，再使用原生確認選項。
4. 點 **Paseo**。首次安裝後若後端尚未載入，在此頁點 **重載 Dashboard → 確認重載**；等頁面恢復，不需進入 PaaS 或重新啟動整台 HA。
5. 待 runtime 下載及啟動完成，產生配對連結，再點 **開啟 Paseo**。官方介面在新分頁開啟；配對連結具有存取能力，請勿公開貼出。
6. 在官方 Paseo 按 **Connect** 完成配對。全新裝置若顯示 **No projects yet**，先按 **Add project → New directory**，父目錄填 `/opt/data`，按 **Use this parent**，再填自己的專案目錄名稱並按 Enter；也可用 **Search for directory** 選已有目錄。目錄位於 Hermes 主機，不是目前瀏覽器的電腦。
7. 按 **New workspace** 並選定 project，接著選擇 Hermes、已登入且有額度的模型和 Default 模式，輸入訊息再按 **Create**。配對 Online、模型清單可見、實際收到模型回覆是不同檢查；模型帳號仍由 Hermes 管理。

停用或移除插件時，從 Hermes 原生 Plugins 頁操作，主機先停止插件擁有的 Paseo daemon。從 CLI 移除時請先執行 `/paseo stop`。手動停止狀態、配對、模型登入與對話保存在 `/opt/data`，附加元件重啟會保留。原生 `file` 工具集需管理者另行開啟，安裝插件不會自動擴大模型權限。

若配對／重載回報拒絕，先確認 `paseo_ingress_url` 的 scheme、主機與 port 全部符合目前瀏覽器網址，並重新啟動附加元件使設定生效。不要關閉來源驗證或把 ingress token 填進設定。錯誤或缺少模型憑證、額度不足，不會因重載 Dashboard 而修復。

HA 0.1.11 的實機完整對話驗收使用 rc.4；rc.5 的新增模型檢查已在 PaaS 的插件發起對話中驗證。從 Paseo Web 直接建立的對話仍須核對實際模型；若模型不可用，上游可能改用供應商預設模型。

完整插件教學與目前驗收範圍：[Hermes Paseo plugin](https://github.com/WOOWTECH/hermes-paseo-plugin)。
