# 三代理與共用工具

套件預裝 Pi 0.99.1、Claude Code 2.1.285、Codex CLI 0.167.0。
ACP 面板對應 `pi-code`、`claude-agent-acp` 0.84.0、`codex-code`
（Codex ACP 2.6.0）。登入與模型訂閱仍由各代理分別管理。
ACP 切換代理時會出現 `Switch Agent` 確認，斷開上一代理並清空面板顯示；
各代理的對話記錄仍分開儲存，不會自動轉交對話上下文。

在 IDE 終端執行 `pi login`、`claude auth login`、`codex login --device-auth`。
既有 Pi／Claude 登入不需要重做；Codex 使用 `/data/pi-agent/codex`。
這些登入只屬於目前的 code-server 實例，不會從其他服務或租戶複製。

## Skills

共用目錄是 `/data/pi-agent/skills`。每項 skill 使用 `<名稱>/SKILL.md`。
Claude 的 `$CLAUDE_CONFIG_DIR/skills`、Codex 的 `$CODEX_HOME/skills`、
登入使用者的 `~/.agents/skills`、Pi 的 HOME skills 橋接均指向同一目錄。

啟動時 `woow-agent-sync` 合併既有技能，保留原目錄為
`*.before-shared-agents-<時間>`。同名檔案內容不同會停止遷移並說明衝突，
不會靜默覆蓋。技能的語法、權限以及客戶端支援仍依各代理而定。

## MCP

共同來源是 `/data/pi-agent/shared/mcp.json`：

```json
{
  "mcpServers": {
    "docs": { "url": "https://example.com/mcp" },
    "local": { "command": "/absolute/path/to/server", "args": [] }
  }
}
```

修改後執行 `woow-agent-sync`，再重新連線 ACP 或開新終端代理 session。
同步會更新 Pi 的 `mcp.json`、Claude 的 `.claude.json` 與 Codex 的
`config.toml`。刪除共同來源中的伺服器也會同步移除三份受管理設定。
執行中的對話不會自動重新載入設定。

支援 stdio 與 Streamable HTTP；`env`、`headers` 可引用 `${VARIABLE}`。
環境變數必須提供給整個容器，避免終端與 IDE 設定不同。
產生的私人設定權限為 0600；首次修改保留 `.before-shared-agents` 備份。
Codex TOML 的值會保留，註解與排版可能改變，原始檔在備份中。

首次同步會匯入明確設定於各代理全域檔案的 MCP。具備客戶端專有 OAuth
選項、工具限制或隱藏工具的設定會報錯，避免轉換後遺失限制。
SSE、shell substitution 和相對 `cwd` 不屬於共同格式；需要工作目錄的
stdio 伺服器請使用明確的包裝腳本。`timeout` 適用於 Pi/Codex；Claude
使用自己的逾時機制。各代理仍保有自己的工具批准機制。

**共用連線定義不等於共用 OAuth 登入。** 遠端服務若要求 OAuth，仍需在
各代理完成其授權。Claude 帳號自動提供的雲端連接器、專案層設定與
外掛不會被當作已成功共用，也不會被刪除；欲共用須將受支援的連線
明確加入共同來源並逐個驗證。PaaS 保留原有的帳號連接器開關。

## 驗證與復原

`node --test tests/shared-agents.test.mjs` 驗證遷移、碰撞、憑證保留、
重複執行、刪除同步和不支援格式的拒絕行為。
`tests/smoke-acp.sh` 檢查三個代理及 skills 實際路徑。
真實模型測試必須另外驗證 assistant 回覆與 MCP 呼叫紀錄；僅顯示
connected 或在使用者訊息中找到測試文字均不算成功。

正式升級前建立一致的資料備份。需要復原時，停止該實例、還原資料與
上一版映像。單一設定亦可使用保留的 `.before-shared-agents` 檔案復原。
不要將 auth.json、OAuth token、MCP 私有網址或其他憑證提交到 Git。
