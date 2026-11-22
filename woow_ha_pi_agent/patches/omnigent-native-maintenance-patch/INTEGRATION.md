# Proposed root-owned build integration

No main or frozen files have been edited. This is a concrete reviewable source package, not permission to integrate, build, publish or deploy.

The primary repo seam supplied by root is `paas-odoo-ci/pi-agent/`. Its `Dockerfile` hash is `0adb7b84ae5bec310e224b025992c8d9ca792b627c676321cc2c4c8f6d503336`, byte-identical to `Woow_k3s_pi_agent_package/paas/image/Dockerfile`. It installs pinned Omnigent 0.16.0 using `uv pip sync --require-hashes` into `/opt/omnigent/venv` (lines 104–132), then applies existing exact-anchor reminder and model-options patches (lines 144–173). The reviewed insertion point is **after both existing patches**, as a new standalone patch package and strict step. A plugin-only 0.3.34 patch cannot change the shared core maintenance pruner.

Root can copy this reviewed child to a new build-context directory such as `omnigent-native-maintenance-patch/`. The proposed Dockerfile addition is:

```dockerfile
COPY omnigent-native-maintenance-patch/ /opt/patches/omnigent-native-maintenance-patch/
RUN set -eux; \
    SP=/opt/omnigent/venv/lib/python3.12/site-packages; \
    /opt/omnigent/venv/bin/python /opt/patches/omnigent-native-maintenance-patch/apply_maintenance_patch.py \
      --site-packages "$SP" --strict; \
    cd /opt/patches/omnigent-native-maintenance-patch; \
    /opt/omnigent/venv/bin/python -B tests/test_build_patch.py; \
    /opt/omnigent/venv/bin/python apply_maintenance_patch.py --site-packages "$SP" --strict --check-only; \
    PI_NATIVE_MAINTENANCE_TEST_SOURCE="$SP/omnigent/native/native_bridge_common.py" \
      /opt/omnigent/venv/bin/python -B tests/test_maintenance_preservation.py; \
    chmod -R a+rX,go-w /opt/omnigent
```

This snippet is documentation only; it has not been inserted or executed. The installed-source test environment variable is exactly `PI_NATIVE_MAINTENANCE_TEST_SOURCE`; it must point to the installed common module with the lock's exact after-hash. The standalone default is the overlay. Fixtures use the system tempfile directory or explicit `TMPDIR`, never a required writable package directory. The AST fixture boundary remains explicit: no SDK/provider import. Run source tests before/after strict installation as appropriate for the build. The applicator requires an explicit target, checks the entire original source hash and the reviewed payload hash/size, rejects symlinks/hardlinks/source drift, compiles source syntax without executing imports, installs one source file atomically while preserving its owner/mode, then regenerates checked-hash pyc for optimizations 0/1/2 under the build interpreter. It imports no installed Omnigent code. Exact already-applied bytes are accepted, modified variants fail. Check-only mode performs no writes. A failure during source/pyc installation fails the build; it is not a live transactional updater. Do not invoke it against a running installation.

The generated payload is the full exact-source overlay. Review `source-lock.json` and `maintenance-preservation.diff` together; hash-locking does not substitute for reviewing the guard semantics. If another core patch changes this file, the applicator must fail, and root must reconcile/review a new explicit source anchor. Never fall back to a fuzzy anchor or rewrite the expected hash to admit an unreviewed file.

The local source repository `work/omnigent-mcp-server-20261121` at `459340b0d9516fd3ecb4c35a95eb6e17cc3a5340` is a separate upstream port option. Its common/pruner source hashes differ from the captured installed file, so this exact overlay must not be applied there blindly. Root can port the same maintenance-only predicate plus fixtures for upstream review. No repository, PR or publication was modified/created here.

Integration validation still required under root ownership: execute the portable fixture tests under the actual image Python 3.12, verify installed exact payload/pyc in the candidate image, extend the image's source inventory/rootfs lock to include this reviewed patch, and use the existing canonical proof/build/rollout process if later authorized. This package neither grants admission nor changes migration evidence. It does not restore the missing 15 histories, reclassify cleanup as safe, protect explicit DELETEs, or waive Pi3 HOLD/Pi4 NO APPLY.
