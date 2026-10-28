# Shared Paseo runtime input

`package.tgz` is npm pack output from the reviewed source commit recorded in
VENDOR.json. npm excludes package-lock.json from packs, so the source lock is
retained separately and independently hashed. `install.sh` verifies both before
extracting/installing; tests verify metadata, lock dependencies and required
runtime files. Package licences are included in the archive.

This directory owns no OpenDesign source patch. Native launcher and MCP CAS
come from the shared core. See ../docs/paseo-runtime-0.2.2.md for the current HA 0.2.9 release gate and ../docs/paseo-release.md for the earlier 0.2.7 gate.
