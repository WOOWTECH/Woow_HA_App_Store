# 操作與還原注意事項

此app使用官方HA Core 2026.9.1，不是品牌化Core，也不是HAOS系統主Core。

## 安全預設

- Start on boot預設關閉（manual）。
- Network的8123/tcp預設沒有宿主機映射；先選未使用的埠，例如8129。
- 不啟用Ingress、不提供宿主API／Docker socket／硬體直通。
- 只使用自己的addon_config目錄，Supervisor掛載為/config。

## 建立新實例

安裝、設定埠後，Start並完成這個獨立Core的onboarding。主Core帳號不會自動登入此實例。

## 還原已有資料

1. 確認來源是對齊版本的HA Core及相同Recorder模式。
2. 準備新隔離目標，不先Start或onboarding。
3. 使用受驗證且scope正確的Supervisor備份／轉換產物；不要直接把另一平台的tar改名上傳。
4. 不漏掉/config下的.storage、secrets及DB/WAL/SHM等相關檔案。
5. 尚未Start前核對內容與資料權限；不得用新帳號、刪integration或重建資料掩蓋差異。
6. Start後驗原登入、entity/device registry、automation/script/scene、dashboard与Recorder歷史。

本repo只提供部署封裝，不提供尚未驗證的跨格式converter。備份排程、異地目的地與密鑰保管須另行設定。

## 停止與備份

使用Supervisor Stop，容許300秒正常關閉。cold backup由Supervisor協調停止；不能假定停止動作已立即完成，應確認狀態再採集資料。

不要刪除主Core或其他add-on配置。Uninstall時不要勾選刪除資料，除非已驗證備份並明確要移除這個實例。

## 版本

Core：2026.9.1。包裝：2026.9.1-1。amd64及aarch64官方基底digest已固定；實際支持須以各架構原生測試結果為準。
