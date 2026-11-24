# Changelog

## 0.1.7

- Fix: the app image could stop building whenever Alpine published a newer
  build of one of its system packages, as happened with nginx in 0.1.6. The
  image no longer locks those packages to one exact build, and lifts the
  locks the base image keeps for its own packages before installing
  anything. Tailscale (v1.102.3) and how the app behaves do not change.

## 0.1.6

- Stopping the app before its first login now ends in **stopped** after about
  3.5 seconds (measured on an N2840 HAOS box). Until now the start-up step
  that runs `tailscale up` waited for the login inside s6's start-up, so a
  stop waited for it too until Supervisor killed the container after 10
  seconds (`exit code 137`). This was the known limitation listed under
  0.1.3. Waiting for the login is now a long-running service; the
  authentication URL still appears in the log.
- The services that need a logged-in node (forwarding, MSS clamping, the
  MagicDNS ingress proxy, Serve/Funnel, Taildrive, Taildrop) start once
  Tailscale is connected, as before, now from that service. A node that is
  already logged in reconnects on start as before.
- On stop, `tailscaled` itself now receives SIGTERM and shuts down. Outside
  debug mode it used to run in a pipeline, so the signal went to its shell
  and `tailscaled` was only killed with the container. Its log is still cut
  after 200 lines. A `tailscale up` still waiting for the login is stopped
  the same way.
- The image builds again. Alpine no longer serves `nginx=1.30.6-r0`, which
  0.1.5 pinned; the pin is now `nginx=1.30.7-r0`. The other pins are
  unchanged.
- CI runs the new `tests/test-login-wait-layout.sh` and
  `tests/test-tailscaled-signal.sh`.

## 0.1.5

- Add a masked, optional one-use Headscale pairing key to the Home Assistant
  Configuration page. The key is passed to `tailscale up` through a temporary
  file and cleared from the add-on options only after the node connects.
- Preserve an already connected node when a key is entered. Failed or stalled
  enrollments keep the option editable and remove the temporary key file.
- Document the Headplane owner/key GUI flow and same-server recovery.
- For custom control servers, omit client-requested tags during login; assign
  Headscale ACL tags to the pre-auth key in Headplane instead.
- Add Traditional Chinese labels and help text for the control URL and pairing key.

## 0.1.4

- The image builds again. Alpine no longer serves the package versions 0.1.3
  pinned (`bind-tools=9.20.29-r0`, `nginx=1.30.4-r1`), so 0.1.3 can no longer
  be rebuilt on a device. The pins are now `bind-tools=9.20.30-r0` and
  `nginx=1.30.6-r0`. Nothing else changes in the app.

## 0.1.3

- Stopping the app now leaves it **stopped** instead of **error**. When
  Supervisor stops the container, s6 ends every service with SIGTERM, and the
  service finish scripts recorded that as a failure (exit code 128 + 15 = 143).
  Supervisor treats any non-zero container exit code as a crash, logged
  "did not handle SIGTERM … (exit code 143)" and showed the app as `error`
  after a normal stop or restart. A service ended by SIGTERM no longer sets the
  container exit code; other signals and real service failures are still
  reported. This is upstream hassio-addons/app-tailscale#703.
- Known limitation (unchanged, shared with upstream): stopping the app while it
  is still waiting for its first login (`NeedsLogin`, an authentication URL in
  the log) still takes about 10 seconds and ends in `error`, because the
  start-up step that runs `tailscale up` blocks the s6 shutdown until
  Supervisor kills the container. Nothing is lost: starting the app again
  works normally. Tracked in this repository's issues.
- CI runs the new `tests/test-finish-exit-code.sh`.

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
