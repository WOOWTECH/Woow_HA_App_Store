FROM ghcr.io/home-assistant/amd64-base:3.24-2026.08.0

RUN apk add --no-cache iproute2 iptables nftables python3
COPY rootfs /
RUN chmod 0755 \
    /etc/services.d/woow-lan-gateway/run \
    /etc/services.d/woow-lan-gateway/finish

ENV PYTHONPATH=/opt/woow-lan-gateway
