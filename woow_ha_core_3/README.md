# Woowtech HA Core 3

Runs an isolated **Home Assistant Core** instance inside Home Assistant (instance **3**).

| Setting          | Value                     |
| ---------------- | ------------------------- |
| Host port        | `8126` → container `8123` |
| Config directory | `/config` (add-on config folder → host `/addon_configs/<slug>`) |

## Usage

1. Install and start the add-on.
2. Open `http://<your-host>:8126` in your browser.
3. Complete the Home Assistant onboarding for this instance.

Its configuration lives in the add-on's private `/data` partition and is fully independent of
the host Home Assistant and of the other Woowtech HA Core instances. Uninstalling with "Also
remove add-on config and data" **off** keeps this instance's data (reinstall restores it); **on**
wipes it. Updating the add-on always keeps it.

Based on [jgoakley/hassio-addons](https://github.com/jgoakley/hassio-addons).
