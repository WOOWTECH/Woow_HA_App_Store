# ==============================================================================
# Woow Headscale VPN — HA Ingress shim（nginx 設定「模板」）
# ------------------------------------------------------------------------------
# 本檔為模板，不直接被 nginx 讀取：cont-init.d/headscale.sh 會以
# bashio::addon.ingress_entry 取得 ingress 前綴（如 /api/hassio_ingress/<token>），
# 取代下方所有 %%INGRESS_ENTRY%% 佔位後寫出 /etc/nginx/nginx.conf；
# services.d/nginx/run 再以 `exec nginx -c /etc/nginx/nginx.conf` 前景啟動
#（daemon off 已含於本檔）。
#
# 上游：Headplane 0.7.0 於 127.0.0.1:3001，image 內保留 /admin basename
#（方案 A——Dockerfile 只做 "mode": "lazy" → "mode": "initial" 的 sed，關閉
# React Router lazy route discovery；/admin/ 因此成為 body 改寫的唯一錯點）。
#
# 改寫規則依 Headplane 0.7.0 產物實機 recon 增刪（基底：yuriy1337/headscale-ha
# 的 nginx.conf，其驗證基準為 headplane 0.6.2-beta）：
#   【保留】sub_filter '/admin/' → '%%INGRESS_ENTRY%%/'：實測涵蓋 0.7.0 全部
#     body 出現形態——雙引號 "/admin/assets/…"、反引號 `/admin/events/live`、
#     CSS url(/admin/assets/inter-…)、SSR handoff "basename":"/admin/"；
#     runtime HTML 63 處 100% 帶尾斜線。
#   【刪】yuriy 版 href="/、src="/、action="/、url(/、"/assets/、"module":"/、
#     "basename":"/" 等根錯點規則：那是 sed 到根路徑（方案 B）的產物；方案 A 下
#     它們會先吃掉 href="/admin/… 的前七字，產生 %%INGRESS_ENTRY%%/admin/…
#     double-prefix 壞頁。
#   【刪】任何裸 '/admin'（無尾斜線）與 '"/admin"' 規則：runtime body 出現
#     次數 = 0；裸 /admin 更是 hp_ssh.wasm（資料段含 /adminupdate byte 序列）
#     唯一誤傷風險來源。"/admin"（無尾斜線）只以 header 形式外顯
#（302 Location、Set-Cookie Path=/admin）→ 交給 proxy_redirect /
#     proxy_cookie_path，sub_filter 本來就摸不到 header。
#
# 出處：ingress shim 與 /_ha_key 自動登入機制移植自 yuriy1337/headscale-ha，
# 依 headplane 0.7.0 實測調整；服務組裝參考
# AlessioBazzanella/homeassistant-headscale-addon。
# ⚠️ sub_filter/sed 規則版本敏感：headplane 版本 bump 時本檔須整組回歸測試。
# ==============================================================================

# worker 以 root 執行：HA add-on 容器無 CAP_CHOWN，nginx master 啟動時會嘗試
# 把 temp 目錄（/var/lib/nginx/body 等）chown 給 worker user(nobody) 而 EPERM
# crash-loop；worker=root 時 temp 目錄本已 root-owned，不觸發 chown。此為僅聽
# 127.0.0.1 上游、只經 HA Ingress 進來的內部 shim，以 root 執行可接受。
user root;
daemon off;
worker_processes 1;
error_log /proc/1/fd/1 error;
pid /var/run/nginx.pid;

events {
    worker_connections 512;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    access_log off;
    sendfile on;
    gzip off;

    # Headplane 的 node SSH 介面（hp_ssh.wasm）可能走 WebSocket，保留 Upgrade 透傳
    map $http_upgrade $connection_upgrade {
        default upgrade;
        ''      close;
    }

    server {
        # ingress-only 安全模型：3000 不在 config.yaml 的 ports（不開 host port）。
        # 但 3000 仍對整個 Supervisor 內部 Docker 網路（172.30.32.0/23）可達，
        # 而 /_ha_key 會吐出 full-admin API key，故必須把來源限縮到 HA Ingress
        # proxy 單一 IP（172.30.32.2）——HA 官方 add-on ingress 範本的標準門禁。
        # 少了這兩行，同主機上任何其他 add-on/容器都能 curl 走管理 key。
        listen 0.0.0.0:3000 default_server;
        allow 172.30.32.2;
        deny all;
        absolute_redirect off;

        # ACL / policy 編輯器的表單 POST 可能超過 nginx 預設 1m
        client_max_body_size 16m;

        # ---- 共用 proxy 參數（server 層，供各 location 繼承）----
        proxy_http_version 1.1;
        proxy_set_header Host $http_host;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Ingress-Path %%INGRESS_ENTRY%%;
        # 必要：清掉 Accept-Encoding，否則上游回 gzip、sub_filter 全部失效
        proxy_set_header Accept-Encoding "";
        proxy_buffering off;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;

        # sidebar 進站：直接落到 Machines。未登入時上游 302 轉 login，
        # 由下方 proxy_redirect 改寫回 ingress 路徑，login 頁再觸發自動登入。
        location = / {
            return 302 %%INGRESS_ENTRY%%/machines;
        }

        # 自動登入用 API key（services.d/headplane/run 產生後落檔）。
        # GUI 無 host port → 本端點天然只能經 HA Ingress（已驗證身份）到達。
        location = /_ha_key {
            default_type text/plain;
            alias /var/lib/headscale/.headplane_api_key;
            add_header Cache-Control "no-store";
        }

        # SSE：client 端 EventSource(`/admin/events/live`) 經 sub_filter 改寫為
        # %%INGRESS_ENTRY%%/events/live → HA 剥前綴後落到這裡。獨立 location
        # 確保串流不經任何 body 改寫（text/event-stream 亦不在 sub_filter_types），
        # 並沿用 server 層 buffering off / 長 timeout。
        location = /events/live {
            proxy_pass http://127.0.0.1:3001/admin/events/live;
        }

        location / {
            # HA Ingress 已剥掉 /api/hassio_ingress/<token> 前綴；這裡補回
            # Headplane 0.7.0 的 /admin basename（/machines → /admin/machines，
            # /assets/*、/favicon.ico、/hp_ssh.wasm、/fonts/* 同理）
            proxy_pass http://127.0.0.1:3001/admin/;

            # ---- header 層改寫（sub_filter 摸不到 header）----
            # 302 Location: /admin/login?s=logout、GET /admin → /admin/ 等；
            # 依序比對：先長路徑、再裸 /admin(/)（補尾斜線避免空路徑進 HA）
            proxy_redirect ~^/admin(/.+)$ %%INGRESS_ENTRY%%$1;
            proxy_redirect ~^/admin/?$ %%INGRESS_ENTRY%%/;
            # Set-Cookie: Path=/admin → ingress 前綴（session cookie 三處
            # createCookie 皆 path: "/admin"）
            proxy_cookie_path /admin %%INGRESS_ENTRY%%;

            # ---- body 層改寫 ----
            # text/html 為 sub_filter 內建預設，毋須列出；json 供 /__manifest
            # 回應與 Response.json 內的 "/admin/assets/…"（mode:"initial" sed
            # 生效時 /__manifest 已 404，此為 sed 未生效時的後援）；
            # (text|application)/javascript 供 manifest-*.js 與各 chunk 的反引號
            # URL、Vite preload helper。絕不可加 wasm / font / octet-stream 型別
            #（hp_ssh.wasm 內含 /adminupdate byte 序列，改寫即損毀）。
            sub_filter_types text/css text/javascript application/javascript application/json;
            sub_filter_once off;

            # 唯一 body 規則（見檔頭說明；取代 yuriy 版整組根錯點規則）
            sub_filter '/admin/' '%%INGRESS_ENTRY%%/';

            # <head> 注入（單行 script，僅雙引號、無 $ 字元，避免 nginx 字串
            # 插值與引號衝突）：
            #   1) window.baseUrl = ingress 前綴（供自動登入 fetch 用）
            #   2) fetch interceptor：__manifest 的 paths 參數在 query string，
            #      nginx 改不到 request query；client 在 ingress 前綴下送出的
            #      paths 會被上游比對 /admin 失敗回 {}。此攔截把 ingress 前綴
            #      還原成上游認得的 /admin/ 前綴。方案 A 的 mode:"initial" sed
            #      生效時 /__manifest 不再被呼叫，此攔截為 sed 未生效時的後援。
            #      （script 內的 "/admin/" 字面值為故意保留——sub_filter 不會
            #      重掃替換字串，不受上方規則影響。）
            #   3) /_ha_key 自動登入：login 頁（非 s=logout 登出流程）自動抓
            #      key、以隱藏表單 POST api_key → 從 HA sidebar 點開即進站。
            #      _hp_auth 殘留 cookie 以 /、%%INGRESS_ENTRY%%、
            #      %%INGRESS_ENTRY%%/ 三種 path 各清一次（proxy_cookie_path 改寫
            #      後 cookie path 為 ingress 前綴，非 yuriy 版的 /）；
            #      _ha_al（max-age=5）防連續自動登入迴圈；fetch 加 r.ok 檢查，
            #      避免 key 檔尚未產生時把 404 頁當 key POST。
            sub_filter '<head>' '<head><script>window.baseUrl="%%INGRESS_ENTRY%%/";(function(){var p="%%INGRESS_ENTRY%%/",f=window.fetch;window.fetch=function(u,o){if(typeof u==="string"||u instanceof URL){var r=new URL(u,window.location.origin);if(r.pathname.endsWith("/__manifest")){var v=r.searchParams.get("paths");if(v&&p!=="/"){r.searchParams.set("paths",v.split(",").map(function(s){return s.indexOf(p)===0?"/admin/"+s.slice(p.length):s}).join(","));u=r.toString()}}}return f.call(this,u,o)}})();(function(){var p="%%INGRESS_ENTRY%%/";if(window.location.pathname.indexOf("/login")===-1)return;if(window.location.search.indexOf("s=logout")!==-1)return;try{sessionStorage.removeItem("_ha_al")}catch(e){}if(document.cookie.indexOf("_hp_auth=")!==-1){document.cookie="_hp_auth=; max-age=0; path=/";document.cookie="_hp_auth=; max-age=0; path="+p;document.cookie="_hp_auth=; max-age=0; path="+p.slice(0,-1)}if(document.cookie.indexOf("_ha_al=")!==-1)return;document.cookie="_ha_al=1; max-age=5; path=/";fetch(window.baseUrl+"_ha_key").then(function(r){return r.ok?r.text():""}).then(function(k){k=k.trim();if(!k)return;var f=document.createElement("form");f.method="POST";f.action=window.location.pathname;f.style.display="none";var i=document.createElement("input");i.type="hidden";i.name="api_key";i.value=k;f.appendChild(i);document.documentElement.appendChild(f);f.submit()})})();</script>';

            # HA Ingress 以 iframe 內嵌：拔掉上游可能的 X-Frame-Options，
            # 換成 SAMEORIGIN（ingress 與 HA 前端同源）
            proxy_hide_header X-Frame-Options;
            add_header X-Frame-Options "SAMEORIGIN";
        }
    }
}
