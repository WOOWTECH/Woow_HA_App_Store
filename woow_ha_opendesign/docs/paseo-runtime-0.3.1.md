# Agent Connect runtime 0.3.1 in HA add-on 0.2.17

The runtime input is the public [v0.3.1 release](https://github.com/WOOWTECH/opendesign-paseo-plugin/releases/tag/v0.3.1), from merged commit `6e0add40859ce0019aff0c3a9d18af4e57088b01` (the squash of PR #13; tree identical to the reviewed head `281e9b6`). The `package.tgz` SHA-256 is `50244ae050b2eb4fda265b433ae21279ee4d35bb45c2f0cac8de81e101cc325e`; the separately retained `package-lock.json` is `f53bcc7e5a7d56ea0a1db8285e27f7ee7d27db8d78452bedb3979a612152a801`. Both are listed in the release's `SHA256SUMS` and checked against `paseo-runtime/checksums.sha256` before anything is extracted.

0.3.1 changes the image build only. `scripts/prepare-managed-runtime.mjs` points node-gyp at the image's own Node headers (`npm_config_nodedir`, used only when `include/node/node_version.h` is exactly the running Node and `common.gypi` is present), so rebuilding `node-pty` for musl downloads nothing. Before, the headers came from unofficial-builds.nodejs.org. That host publishes an IPv4 and an IPv6 address and Node's default connect gives each address 250 ms, while from Asia its IPv4 connect takes 0.23–0.26 s, so on hosts without IPv6 routing fresh Podman 4.3.0 installs failed with `NATIVE_NODE_PTY_BUILD_FAILED` (once on 2026-11-27, three times in a row on another VM on 2026-11-28). The Paseo version (0.17.5) and the runtime revision (`0.17.5-r2-186f173be43b`, derived from the runtime lock) are unchanged.

Release gates before merging:

1. Run `./tests/run.sh` and pass the required PR checks, including the container and browser smoke, the offline managed-runtime smoke, and `Upgrade comparison / compare` against the latest Stable Release (0.2.16).
2. Build an immutable candidate from this branch with the existing `build.yml` candidate workflow and the w2.11 core digest. Confirm its source, runtime, image digest and container smoke receipt.
3. On the dedicated HAOS test instance, update the installed 0.2.16 to this candidate with the canonical add-on repository entry. Verify the plugin card (Agent Connect 0.3.1), the daemon running with the unchanged runtime revision, that the installation id, server id and onboarding are kept, the model lists, and a pairing link.
4. Merge only after the candidate and HAOS evidence are reviewed; the version bump publishes through the repository's normal Store workflow. Verify the published image digest, Release and Store catalog afterwards.

Earlier gates: [0.3.0 runtime in 0.2.16](paseo-runtime-0.3.0.md), [0.2.3 runtime in 0.2.11](paseo-runtime-0.2.3.md), [0.2.2 runtime in 0.2.9](paseo-runtime-0.2.2.md), [0.2.7](paseo-release.md).
