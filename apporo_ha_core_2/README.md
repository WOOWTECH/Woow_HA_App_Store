# Apporo HA Core 2

Runs an isolated **Home Assistant Core** instance inside Home Assistant (instance **2**).

| Setting            | Value                     |
| ------------------ | ------------------------- |
| Host port          | `8125` → container `8123` |
| Config directory   | `/config/apporo_ha_core_2` |

## Usage

1. Install and start the add-on.
2. Open `http://<your-host>:8125` in your browser.
3. Complete the Home Assistant onboarding for this instance.

Its configuration lives in `/config/apporo_ha_core_2` and is fully independent of the host Home
Assistant and of the other Apporo HA Core instances.

Based on [jgoakley/hassio-addons](https://github.com/jgoakley/hassio-addons).
