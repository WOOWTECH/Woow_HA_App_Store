# Codex nested sandbox in containers

Codex 0.167.0's preflight recognizes `Can't mount proc on /newroot/proc`.
Bubblewrap 0.12.0 can report the same denied mount as `/proc`. The image's
`woow-codex` launcher puts a root-owned compatibility shim on Codex's PATH;
`codex-code` uses the same launcher. Only that exact diagnostic, for the
`/bin/true` or `/usr/bin/true` preflight, is normalized. Codex then applies its
own inherited-proc fallback. Arguments, namespace flags, exit status, auth,
actual-command stderr and the requested sandbox mode are preserved.

This does not cure an outer AppArmor/seccomp denial of user namespaces.
The image does not disable either policy or add capabilities. On hosts that
block nested bubblewrap, an administrator can provision the optional profiles
in this directory. They retain the Moby baseline restrictions, allow nested
user/mount namespaces, and deny AF_ALG/AF_VSOCK sockets. They are broader than
RuntimeDefault for namespace/mount syscalls, so apply them only to the target
container, with `allowPrivilegeEscalation: false`, non-root UID and `drop: [ALL]`.

## Kubernetes host provisioning (opt-in)

Install on **every eligible node**, outside the application container:

```sh
sudo install -m 0644 apparmor /etc/apparmor.d/woow-code-server-bwrap
sudo apparmor_parser -r /etc/apparmor.d/woow-code-server-bwrap
sudo install -d -m 0755 /var/lib/kubelet/seccomp/woow-code-server
sudo install -m 0644 seccomp.json /var/lib/kubelet/seccomp/woow-code-server/codex.json
```

Use the actual kubelet seccomp root if it differs. A loaded kernel profile
alone does not survive reboot; the `/etc/apparmor.d` file must be loaded by the
host's AppArmor service. Verify the profile is loaded after reboot before
scheduling workloads. Restrict scheduling to nodes that have both profiles.
The code-server chart accepts these fields in `securityContext`; review the
rendered containers because that value also applies to chart sidecars:

```yaml
securityContext:
  allowPrivilegeEscalation: false
  capabilities:
    drop: [ALL]
  seccompProfile:
    type: Localhost
    localhostProfile: woow-code-server/codex.json
  appArmorProfile:
    type: Localhost
    localhostProfile: woow-code-server-bwrap
```

For Docker, load AppArmor on the Docker **daemon host**, then use
`--user 1000:1000 --cap-drop ALL --security-opt no-new-privileges=true
--security-opt apparmor=woow-code-server-bwrap
--security-opt seccomp=/absolute/path/seccomp.json`.
Do not add `--privileged`, `SYS_ADMIN`, an unconfined profile or a full-access
Codex policy to make a probe pass. Rootless Podman on the tested host only
needed the diagnostic shim; its outer runtime was already permitting userns.

HA Supervisor manages its own add-on profiles. The Docker example proves the
image works under an explicitly provisioned profile; it does **not** install
or validate a Supervisor-managed production policy. A normal add-on upgrade
alone must not be described as completing that host integration.

## Verification

`node --test tests/codex-sandbox-compat.test.mjs` checks diagnostics, exit codes,
arguments, descriptors and both launchers. Inside the target container, run
`python3 tests/codex-sandbox-live.py` (copy the script in first). No model login
is required. It must allow workspace read/write and reject an outside write
with EROFS plus a socket with EPERM; it verifies the outside fixture is intact
and removes all fixtures. A process-start failure is never counted as a denied
operation passing. Repeat the probe after runtime/kernel/profile changes.

On 2026-11-10 this four-case probe passed on rootless Podman, a dedicated HA
Docker test container, and the PaaS QA deployment. PaaS additionally completed
a native authenticated Codex conversation: shared skill read, shell arithmetic,
and a successful Home Assistant MCP call, with `workspace-write` and approvals
set to `never`. No production HA add-on profile was replaced by these tests.

Sources:
- https://github.com/openai/codex/blob/rust-v0.167.0/codex-rs/linux-sandbox/src/linux_run_main.rs
- https://github.com/openai/codex/blob/rust-v0.167.0/codex-rs/linux-sandbox/README.md
- https://github.com/jonasjancarik/codex-broker/tree/main/examples
