# HA Agent Connect rc.3 Companion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prepare an isolated HA add-on candidate that bundles the exact Agent Connect 0.1.27-rc.3, Omnigent 0.3.42-rc.3 and Paseo 0.17.5-r3 artifacts while preserving the published 0.15.27 bridge behavior.

**Architecture:** Start at the published HA 0.15.27 commit in a dedicated worktree. Vendor only the reviewed C3/Pi candidate archives, bind their hashes and source/runtime provenance in the existing manifest and single pin file, and let current build/test consumers derive from those pins. Update user-facing release notes as a prerelease candidate. Run source/pin/archive and focused bridge contract tests locally; leave image and release gates to CI.

**Tech Stack:** Home Assistant add-on source, Node.js tests, shell/Python manifest validation, gzip tar archives.

---

### Task 1: Establish candidate baseline

**Files:**
- Create: `docs/plans/2026-11-26-ha-agent-connect-rc3-companion.md`

**Steps:**
1. Confirm worktree starts at published HA 0.15.27 commit `e7bfcbd` and retains startup/pending bridge code.
2. Record exact C3 artifact paths, archive hashes, source SHAs, runtime revision, and existing tests that consume `cli-runtime/versions.json`.

### Task 2: Pin exact paired archives

**Files:**
- Add: `candidate-packages/woowtech-pi-paseo-0.1.27-rc.3.tgz`
- Add: `candidate-packages/woowtech-pi-omnigent-plugin-0.3.42-rc.3.tgz`
- Modify: `candidate-packages/manifest.json`
- Modify: `cli-runtime/versions.json`

**Steps:**
1. Vendor the Paseo archive from the C3 cache and the Omni archive from the rc.3 candidate artifacts; verify expected SHA-256 before and after copying.
2. Update both canonical pins and manifest provenance, including Agent Connect source, Paseo 0.17.5, and runtime `0.17.5-r3-8664f2c3f8f5`.
3. Keep shared-runtime 0.1.6 and all unrelated CLI/plugin pins unchanged.

### Task 3: Document candidate and retained bridge contract

**Files:**
- Modify: `config.yaml`
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Modify: `README_zh-TW.md`
- Modify: `docs/PASEO_HA.md`
- Modify: `docs/AGENT_CONNECT_CANDIDATE.md`

**Steps:**
1. Set the HA candidate version to `0.15.28-rc.3`; do not describe it as published or stable.
2. Explain exact plugin/runtime pairing, preserved target/pending/startup behavior, identity-preserving upgrade intent, and candidate-only status.
3. Retain the 0.15.27 startup progress and pending-target guidance in the shipped docs.

### Task 4: Verify pins and bridge behavior locally

**Files:**
- Test: `tests/versions.test.mjs`
- Test: `tests/paseo-ha.test.mjs`
- Test: `tests/paseo-settings-ui.test.mjs`
- Test: `tests/paseo-contract.test.mjs`

**Steps:**
1. Run manifest/version/archive consistency checks and source build-context validation.
2. Run focused bridge and settings UI contract tests to prove the 0.15.27 target/pending/start feedback behavior remains intact.
3. Do not build the HA image locally; record CI-required image, upgrade-comparison, mock-Supervisor and multi-architecture gates.

### Task 5: Review and commit local candidate

**Steps:**
1. Inspect full diff, status, exact SHA/provenance binding and test receipts.
2. Commit on the isolated candidate branch using the repository author/footer convention. Do not push, tag, merge, publish, or contact hosts.
