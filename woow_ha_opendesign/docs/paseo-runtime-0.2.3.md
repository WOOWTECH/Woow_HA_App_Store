# Paseo runtime 0.2.3 in HA add-on 0.2.11

The runtime input is the public [v0.2.3 release](https://github.com/WOOWTECH/opendesign-paseo-plugin/releases/tag/v0.2.3), from merged commit `56fcee82d610b56d5263e88cff04f9ece602a9ef`. The `package.tgz` SHA-256 is `d251711d19215e03a13334319207f602c5d23c27f74dffa5a8d0003351ad4ab3`; the separately retained `package-lock.json` SHA-256 is `e38a02053d4237e2af12c0dafd60627d0a748fead4d03c5d14a7ea6578868a39`. All 75 archive members were compared byte-for-byte with the merged source, and the release assets were downloaded anonymously and checked after publication. `paseo-runtime/install.sh` verifies the two input hashes before installation.

This update creates the provider home directories when the runtime context is built (fresh PaaS volumes had no `.codex`, so the Codex login failed and its model list answered 503; this add-on's start script already creates them) and refreshes a provider model catalog once when it was cached empty or failed (Pi after its login, a provider that could not start). It also carries plugin PR #5: a runtime shipped next to the package is used when present (this add-on ships none, so the runtime is still installed from the lock), and a new daemon home starts with local dictation and voice mode off to avoid a first-start download of about 0.7 GiB of speech models; an existing daemon home is never changed. The HA wrapper, core digest, architecture, network ports, backup rules and `/data` layout stay the same. Upgrading from 0.2.10 needs no migration. A new or expired provider login still requires the user to complete the provider's official authorization flow.

Release gates before merging:

1. Run `./tests/run.sh` and pass the required PR checks, including image and browser smoke.
2. Build an immutable candidate from this branch with the existing `build.yml` candidate workflow and the w2.10 core digest. Confirm its source, runtime, image digest and container smoke receipt.
3. On the dedicated HAOS test instance, update the installed 0.2.10 to this candidate with the canonical add-on repository entry. Verify the plugin card and setup page, Paseo running with runtime 0.11.2, the model lists of the three engines, stop/start, that provider logins persist across the update, and that the existing daemon home keeps its feature settings (speech unchanged) while a new home starts with speech off.
4. Merge only after the candidate and HAOS evidence are reviewed; the version bump publishes through the repository's normal Store workflow. Verify the published image digest, Release and Store catalog afterwards.

Earlier gates: [0.2.2 runtime in 0.2.9](paseo-runtime-0.2.2.md), [0.2.7](paseo-release.md).
