#!/usr/bin/with-contenv bashio
set -euo pipefail

COLLABORA_URL="$(bashio::config 'collabora_url')"
PUBLIC_HA_URL="$(bashio::config 'public_ha_url')"
USERNAME="$(bashio::config 'username')"
PASSWORD="$(bashio::config 'password')"
AUTH="$(printf '%s:%s' "$USERNAME" "$PASSWORD" | base64 | tr -d '\n')"

cat >/etc/nginx/nginx.conf <<'NGINX'
worker_processes 1;
events { worker_connections 1024; }
http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    sendfile on;
    server_tokens off;
    client_max_body_size 0;
    proxy_buffering off;
    proxy_request_buffering off;
    map $http_upgrade $connection_upgrade { default upgrade; '' close; }
    include /etc/nginx/http.d/*.conf;
}
NGINX

cat >/etc/nginx/http.d/collabora-admin.conf <<NGINX
server {
    listen 8098 default_server;

    location = /healthz { return 200 'ok'; add_header Content-Type text/plain; }

    location / {
        proxy_pass ${COLLABORA_URL};
        proxy_http_version 1.1;
        proxy_set_header Host \$proxy_host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Prefix \$http_x_ingress_path;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;
        proxy_set_header Authorization "Basic ${AUTH}";

        proxy_hide_header Content-Security-Policy;
        proxy_hide_header X-Frame-Options;
        add_header Content-Security-Policy "frame-ancestors 'self' ${PUBLIC_HA_URL}; default-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob:; connect-src 'self' ${PUBLIC_HA_URL} ws: wss:; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; font-src 'self' data:;" always;

        proxy_cookie_path / \$http_x_ingress_path/;
        proxy_cookie_path /browser/dist/ \$http_x_ingress_path/browser/dist/;
        proxy_redirect ~^(/.*)$ \$http_x_ingress_path\$1;

        sub_filter_once off;
        sub_filter_types text/html text/css application/javascript application/json;
        sub_filter 'href="/browser/' 'href="\$http_x_ingress_path/browser/';
        sub_filter 'src="/browser/' 'src="\$http_x_ingress_path/browser/';
        sub_filter 'href="/cool/' 'href="\$http_x_ingress_path/cool/';
        sub_filter 'src="/cool/' 'src="\$http_x_ingress_path/cool/';
        sub_filter '"/browser/' '"\$http_x_ingress_path/browser/';
        sub_filter "'/browser/" "'\$http_x_ingress_path/browser/";
        sub_filter '"/cool/' '"\$http_x_ingress_path/cool/';
        sub_filter "'/cool/" "'\$http_x_ingress_path/cool/";
        sub_filter '${COLLABORA_URL}' '${PUBLIC_HA_URL}\$http_x_ingress_path';
    }
}
NGINX

nginx -t
exec nginx -g 'daemon off;'
