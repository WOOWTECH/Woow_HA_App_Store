ARG BUILD_FROM
FROM ${BUILD_FROM}

RUN apk add --no-cache python3
COPY rootfs /
RUN chmod 0755 /etc/services.d/haos-enrollment-bridge/run /app/bridge.py
