# Changelog

## 2026.9.1-1

- Initial minimal Supervisor wrapper around the official HA Core 2026.9.1 image.
- Pin amd64/aarch64 upstream platform digests.
- No rebranding, custom components or configuration seed.
- Independent addon_config, manual boot, cold backup and disabled host-port mapping by default.
- Filter Supervisor credentials/discovery variables from the Core process environment.
- Include package tests and k3s version-alignment examples; native installation/migration acceptance remains pending.
