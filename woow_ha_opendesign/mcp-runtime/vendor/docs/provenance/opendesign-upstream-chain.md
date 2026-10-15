# OpenDesign vendored 來源鏈補查

協調者於 2026-10-03 以無認證 public HTTPS GET 補查；不執行來源，不讀部署/credential，不修改原 repo。這不是公開授權 clearance。

- 原來源：`https://github.com/WOOWTECH/Woow_opendesign_mcp_server`
- legacy header 的 `d6d157a` 已解析為完整 commit：`d6d157ab9542cf18515d7168f5c8082c88b11331`（commit API HTTP 200）。
- 上游檔：`od_mcp_server.py`，SHA256 `a18ec6bcd816f804e56d2f0f9380630c85c648254c96e5e1926988afc254fe06`。
- legacy snapshot `614ae663fadd91c76972f60017a76d2627bea87e` 的 `apps/opendesign/opendesign_mcp_server/od_mcp_server.py`，SHA256 `89caa06f96a62a6df663609fa468f00b41180970c835ceb03f3a1cf196f2e717`。
- 兩者移除第一個 module docstring AST node 後，Python AST 完全相同。此比對忽略 comments/formatting，只證明該範圍語義結構相同，不是 bit-identical/完整 supply-chain attestation。
- 新 repo 的後續變更以 `runtime-sources.json` 記錄 upstream/local hash；不能把新安全 patch 稱為原封不動來源。

## 尚未解除的授權事項

`GET /repos/WOOWTECH/Woow_opendesign_mcp_server/license?ref=d6d157a` 回 **404**；該固定 commit 的完整 recursive tree（truncated=false）没有名稱含 LICENSE/NOTICE/COPYING 的檔案。

legacy app-local MIT 已保留，但它是否充分涵蓋此先前無明示 LICENSE 的 imported file，仍需要著作權人確認/補 scoped notice。公開可下載不等於已授權再散布。不要把「full commit 已確認」誤稱「來源授權全部清除」。

## 查證命令結果

兩個 Python urllib/json/hashlib/ast 唯讀腳本均 exit0；第一腳本包含明確 caught license HTTP404，exit0只代表腳本完成，不代表 LICENSE 存在。所有對話輸出只含 metadata/hash/boolean，不傾倒 source 或私有預設值。
