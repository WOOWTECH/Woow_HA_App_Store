# Changelog

## 0.1.2

- This repository is now the canonical source of the add-on. The App Store copy
  (`Woow_HA_App_Store/woow-tailscale`) is synchronized from here and no longer
  edited by hand; its 0.1.1 change is carried over below.
- Fix the image build again. Alpine 3.24 has replaced `bind-tools=9.20.27-r0`
  with `9.20.29-r0` for both `x86_64` and `aarch64`, so the 0.1.1 pin can no
  longer be satisfied and the build fails before Tailscale is downloaded. The
  pin is now `9.20.29-r0`; the other eight pins are still available unchanged.
- The tests resolve the add-on directory from their own location, so they run
  both here (`tailscale/`) and in the App Store copy (`woow-tailscale/`).
- CI builds the image for `amd64` and `aarch64` from the `build.yaml` base
  images and smoke-tests the installed tools. Nothing is pushed: Home Assistant
  still builds this add-on locally.

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
