# Apporo HA Core 3

Runs an isolated **Home Assistant Core** instance inside Home Assistant (instance **3**).

| Setting            | Value                     |
| ------------------ | ------------------------- |
| Host port          | `8126` → container `8123` |
| Config directory   | `/config/apporo_ha_core_3` |

## Usage

1. Install and start the add-on.
2. Open `http://<your-host>:8126` in your browser.
3. Complete the Home Assistant onboarding for this instance.

Its configuration lives in `/config/apporo_ha_core_3` and is fully independent of the host Home
Assistant and of the other Apporo HA Core instances.

Based on [jgoakley/hassio-addons](https://github.com/jgoakley/hassio-addons).
