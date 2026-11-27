# R3 Web UI N-12：正式 Smart 兩站缺少多選功能

本輪官方 App 0.17.5 N-12 PASS；Woowtech／Apporo 正式 App 0.17.4 N-12 **FAIL 保留**。重新下載的實際 JS 均與該輪 SHA256 一致。Smart row 只接一般導頁 handler；兩站 bundle 都缺選取 hook/store、checkbox 狀態及 count/exit toast，因此歸因為版本功能差距。

本輪 Linux Control 正確，官方同例成功；Smart Meta／Shift 也無選取。借用 helper 硬寫 Meta 另有跨平台限制，未來改用 ControlOrMeta。最小建議：前端同步既有 0.17.5 功能 commits e52bb6e＋ba45634 的完整相依（兩種 row、selection host/toast、modifier 與 Web long-press 修正）；未實作或部署。

[精簡公開證據](agent-connect-n12-r3-public.json) 列出當輪版本、asset path/hash 與原結果。14 個隔離函式分支探針只屬診斷，不算 UI PASS；單列案例不涵蓋跨列 range 或 archive。來源 commit 歸屬包含交接宣告，未聲稱可重現 build attestation。

此證據限 **R3 baseline，不適用 R4**；本次未新增 UI／host 操作、agent 或模型呼叫（0）。HA native 與 arm64 actual acceptance 均 **NOT_TESTED**，CI build 成功不等於實機通過。無 bundle、私密 offer、帳密、session/storageState 或個人路徑。

公開 JS 固定來源：[Paseo](https://app.paseo.sh/_expo/static/js/web/index-4e549308c95a80bb80f968447a2ec3e6.js)、[Woowtech](https://smart.woowtech.io/_expo/static/js/web/index-5edec1e62b572d3ca6d23c1a2ea447ba.js)、[Apporo](https://smart.apporo.ai/_expo/static/js/web/index-020bc9cd937992d7944fe165d379aa14.js)。完整 SHA256 與當輪 visible version 見同目錄 JSON；正式 origin 可更新，本結果僅對應列出的資產。
