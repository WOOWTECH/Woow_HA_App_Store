#!/bin/sh
# ==============================================================================
# Home Assistant App (Add-on): Cloudflared
#
# Container build of Cloudflared
# ==============================================================================

set -eux

# The `sed` on /etc/apk/world is load-bearing. Base images record the exact
# package builds present when they were made (e.g. libssl3 at 3.5.4-r0) as hard
# constraints in world. Alpine publishes new revisions continuously, so those
# pins go stale and then EVERY apk operation in the image fails to resolve,
# including installs unrelated to the pinned package. Stripping the
# constraints leaves the package NAMES, so world still describes what the
# image actually contains and nothing gets purged.
sed -i 's/[<>=~].*$//' /etc/apk/world
apk upgrade --no-cache libssl3 libcrypto3

# yq is to avoid depending on Home Assistant API on startup. Not pinned:
# Alpine keeps only the newest revision of each package, so an exact
# `-rN` pin stops resolving as soon as the package is rebuilt.
apk add --no-cache yq-go

# Adapt the architecture to the cloudflared specific names if needed
# see HA archs: https://developers.home-assistant.io/docs/add-ons/configuration/#:~:text=the%20add%2Don.-,arch,-list
# see Cloudflared archs: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation
case "${BUILD_ARCH}" in
"aarch64")
    cloudflared_arch="arm64"
    ;;
*)
    cloudflared_arch="${BUILD_ARCH}"
    ;;
esac

# Download the cloudflared bin
wget -q -O /usr/bin/cloudflared "https://github.com/cloudflare/cloudflared/releases/download/${CLOUDFLARED_VERSION}/cloudflared-linux-${cloudflared_arch}"

# Make the downloaded bin executeable
chmod +x /usr/bin/cloudflared

# Remove legacy cont-init.d services
rm -rf /etc/cont-init.d

# Remove s-6 legacy/deprecated (and not needed) services
rm -f /package/admin/s6-overlay/etc/s6-rc/sources/base/contents.d/legacy-cont-init
rm -f /package/admin/s6-overlay/etc/s6-rc/sources/base/contents.d/fix-attrs
rm -f /package/admin/s6-overlay/etc/s6-rc/sources/top/contents.d/legacy-services
