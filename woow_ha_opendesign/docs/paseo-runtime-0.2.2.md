# Paseo runtime 0.2.2 in HA add-on 0.2.9

The runtime input is the public [v0.2.2 release](https://github.com/WOOWTECH/opendesign-paseo-plugin/releases/tag/v0.2.2), from merged commit `8c7780ea3656001efaa192036b4c66e980e8419f`. The `package.tgz` SHA-256 is `d3ae421f8a20ea498556fa3264cd240a802e8fa1031ffd966b137185b7da988e`; the separately retained `package-lock.json` SHA-256 is `a8709d8c7c5aa3ccb989b8221a22a0e28db47ba5c04fb674b883a6cc1ad416e0`. All 75 archive members were compared byte-for-byte with the merged source, and all four release assets were downloaded anonymously and checked after publication. `paseo-runtime/install.sh` verifies the two input hashes before installation.

This update fixes Claude Code's official web authorization in the protected Paseo setup page. The HA wrapper, immutable core 20261026.1751 digest, architecture, network ports, backup rules, and `/data` layout stay the same. Upgrading from 0.2.8 requires no migration. A new or expired provider login still requires the user to complete the provider's official authorization flow.

Release gates before merging the version bump:

1. Run `./tests/run.sh` and pass the required PR checks, including image and browser smoke.
2. Build an immutable candidate from this branch using the existing `build.yml` candidate workflow and the current published core digest. Confirm its source, runtime, image digest, and container smoke receipt.
3. On the dedicated HAOS test instance, use the canonical add-on repository entry to update from 0.2.8 to the candidate. Verify first-run plugin card and setup page, Claude Code login through the protected GUI, model catalog, two-turn conversation, stop/start, and persistence across restart and cold backup/restore. Record any provider account or quota limit separately.
4. Merge only after the candidate and HAOS evidence are reviewed. The version bump publishes through the repository's normal Store workflow; verify the published image digest, Release, Store catalog, and a stable 0.2.9 install afterward.

The older [0.2.7 gate](paseo-release.md) remains historical context for the first native Paseo integration.
