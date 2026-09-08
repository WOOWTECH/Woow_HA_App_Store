# Changelog

## 0.1.1

- Fix the image build. `bind-tools` was pinned to `9.20.26-r0`, which Alpine
  has replaced with `9.20.27-r0`, so `apk add` could not satisfy it and the
  build failed before Tailscale was ever downloaded:

      ERROR: unable to select packages:
        bind-tools-9.20.27-r0:
          breaks: world[bind-tools=9.20.26-r0]

  The base image `ghcr.io/hassio-addons/base:21.0.2` is Alpine 3.24.1, whose
  repositories carry `9.20.27-r0` for both `x86_64` and `aarch64`. Upstream
  `hassio-addons/app-tailscale` made the same one-line bump and left its other
  eight pins untouched; this fork now matches it exactly.

## 0.1.0

- Initial WoowTech fork of Home Assistant Community Tailscale add-on.
- Added safe automatic state migration when `login_server` changes.
