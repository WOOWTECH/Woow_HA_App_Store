# K3s Blueprint — pi agent + pi-web on Kubernetes

> **Status.** Design-only. This document is the blueprint for a k3s port of the HA-add-on distribution described in [`DEPLOYMENT.md`](DEPLOYMENT.md). No k3s manifests are shipped yet in this repo — see §10 "Next steps" for the delivery plan.

Design goal: **the same pi-web + pi coding agent + skill store + video pipeline** currently running as a HA Supervisor add-on, redeployed on a k3s cluster with per-team isolation, native Ingress TLS, secret-store-backed API keys, and Helm-based upgrades.

Everything below is a decision matrix, not a spec. Where the HA-addon path made a decision we can inherit, it's called out with **HA→K3s**; where the HA model doesn't translate, the tradeoff is named and a default is picked.

## 0. What we inherit from the add-on (unchanged)

| Component | Same on k3s? | Notes |
|---|---|---|
| Container image (Debian bookworm + Node 22 + ffmpeg + Chromium libs + rclone + git + openssh-client + pi-web@0.8.4) | **Yes** — reuse `ghcr.io/woowtech/woow-ha-pi-agent-<arch>:<version>` | The image is HA-agnostic; only `bashio::config` calls in `pi-web/run` are HA-specific (see §3) |
| Provider catalog + `models.json` layout | **Yes** — 7 providers, same seed order | Bootstrap moves to an init-container (§3) |
| pi coding agent SDK model (in-process, no daemon) | **Yes** | Node process on port 30141 |
| Skill install flow (git/ssh backing `skills` CLI) | **Yes** | `git`+`openssh-client` already in image |
| Persistent state layout under one dir | **Yes**, but the dir moves — see §4 (PVC mount at `/data/pi-agent`) |
| Video pipeline two-tier install (baked + first-boot venv/chromium) | **Yes** — same bootstrap, different lifecycle hook (initContainer instead of s6 oneshot) |

## 1. Deployment shape

Two viable shapes; pick per team scale:

| Model | When | Trade-off |
|---|---|---|
| **Single Deployment + PVC, one replica per team-namespace** | ≤ 10 concurrent users per team; simplest | pi-web keeps everything in local files — SSE, sessions, worktrees, skills. Zero shared state; only one replica can safely own the PVC. `replicas: 1` + `strategy: Recreate`. |
| **StatefulSet + PVC, one replica** | Same footprint but stable pod name (`pi-agent-0`) so per-user `pi-cwd-*` worktrees address by pod DNS if we later add sidecars (VS Code server, JupyterLab) | Slight overhead vs Deployment; pays off when we want to attach dev sidecars |
| **Deployment with multiple replicas** | ❌ NOT VIABLE without upstream changes | pi-web has no distributed session store — two replicas would double-write `sessions/*.jsonl`, corrupt `models.json` on concurrent merges, and split-brain on skills |

**Default: StatefulSet, `replicas: 1`, `strategy: OnDelete`.** Gives us pod name stability without giving up the option to later add sidecars, and rules out accidental horizontal scale.

## 2. Namespaces / multi-tenancy

Per team ⇒ one namespace. Naming convention `pi-agent-<team>` (mirrors the existing `hermes`, `n8n`, `odoo` namespaces on the WoowTech k3s cluster).

| Reason | Trade-off |
|---|---|
| Clean quota + NetworkPolicy scope per team | 1 replica per team = per-team resource overhead. Fine at team scale, would need consolidation at seat scale. |
| Skills and sessions physically isolated | Cross-team skill sharing requires re-installing per team (or a shared PVC + RWX SC — punt for v1) |
| Rotate secrets per team without churn | — |

## 3. Config → Kubernetes primitives (HA→K3s mapping)

| Addon primitive | K3s primitive | Details |
|---|---|---|
| `config.yaml` `options` (7 provider keys) | `kind: Secret` `pi-agent-provider-keys` in each namespace | Keys mounted as env vars via `envFrom.secretRef`. No `password?` schema needed — Kubernetes Secret already redacts in kubectl output |
| `bashio::config 'api_key'` in `pi-web/run` | Direct env var reads (`$GLM_API_KEY`) | The `pi-web/run` script becomes plain bash — the `bashio::config` layer is HA-specific and drops out |
| `bashio::log.*` | `echo` to stdout | K8s handles log capture via `kubectl logs` |
| `SUPERVISOR_TOKEN` + sidebar POST | **Removed** — no sidebar, k8s Ingress is the entry point | See §5 |
| `/data` (addon-config mount) | `PersistentVolumeClaim` mounted at `/data/pi-agent` | See §4 |
| `hassio_api: true` | Not needed | — |
| `ingress_port: 30142` | Container port + Service + Ingress | See §5 |
| `watchdog` | `livenessProbe` + `readinessProbe` on `/api/home` | See §6 |
| `backup: cold`, `backup_exclude` | Velero + VolumeSnapshot with `.backupExcludePaths` in a PreBackup hook — or a CronJob that rsyncs to S3 | See §8 |
| `video-tools-init` s6 oneshot | `initContainers` — same script, `restartPolicy: OnFailure` | Runs before pi-web container starts; sentinel logic identical |
| s6-overlay 3-service tree | 2 containers in one pod: `nginx` + `pi-web` (both `longrun`); `initContainer` for `video-tools-init` | s6 goes away — kubelet is the supervisor |
| `nginx` config with X-Ingress-Path shim | Simplified — see §5. The `sub_filter` + `</head>` shim is **not needed** because k8s Ingress can host pi-web at path `/` (no prefix rewriting) |

**Key simplification: the entire `nginx.conf` sub_filter + `</head>` shim can be deleted on k3s.** HA Ingress forces pi-web to a `/api/hassio_ingress/<token>/` prefix; k8s Ingress can host it at either subdomain root (`pi-agent.woowtech.io/`) or a clean path (`/pi/`) with path rewriting handled by the ingress controller. We choose subdomain root — no rewriting, no shim, no `sub_filter`. Retain nginx only if we want an on-path guard (see §5). Otherwise drop nginx entirely and expose pi-web:30141 directly via Service.

## 4. Storage

| PVC | Size | StorageClass | RWX? |
|---|---|---|---|
| `pi-agent-data` (mount `/data/pi-agent`) | 20 Gi request, 50 Gi limit | `longhorn` (or cluster default) | **RWO** — StatefulSet single-replica |

Sub-tree usage:

- `sessions/`, `models.json`, `auth.json`, `home/pi-cwd-*/`, `skills/`, `projects/*/final.mp4`, `rclone/rclone.conf` — **backup on**
- `venv/`, `playwright-cache/`, `projects/*/clips/`, `projects/*/segments/` — **backup off** (rebuildable — same policy as `backup_exclude` in `config.yaml`)

Backup exclusion is handled at snapshot time (Velero `--exclude-pattern` or a PreBackup hook that empties the excluded dirs — see §8), not at the mount level.

## 5. Networking

### Ingress

Assume the cluster already runs Traefik (k3s default) or ingress-nginx. Per-team ingress:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: pi-agent
  namespace: pi-agent-<team>
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod        # or internal ACME
    nginx.ingress.kubernetes.io/proxy-buffering: "off"       # SSE chat stream
    nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "3600"
spec:
  ingressClassName: nginx
  tls:
    - hosts: [pi-agent-<team>.woowtech.io]
      secretName: pi-agent-tls
  rules:
    - host: pi-agent-<team>.woowtech.io
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: pi-agent
                port:
                  number: 30141
```

### Service

```yaml
apiVersion: v1
kind: Service
metadata: { name: pi-agent, namespace: pi-agent-<team> }
spec:
  selector: { app: pi-agent }
  ports:
    - name: http
      port: 30141
      targetPort: 30141
```

**No nginx sidecar in v1.** If we later need on-path body inspection (e.g., strip `Authorization: Bearer` before forwarding to pi-web), add it back. But there is no ingress-prefix problem to solve on k3s, so the sub_filter + shim entirely disappear.

### Auth

HA delegated auth to HA's session cookie. K3s has no equivalent. Options in priority order:

1. **oauth2-proxy in front of the Ingress**, backed by Google Workspace / Authentik / Dex. Same UX as HA (SSO login redirects to Google → pi-web loads). Only pi-web-authorized users see the app; roles enforced by oauth2-proxy group claim.
2. **NetworkPolicy** restricting Ingress to a VPN/WireGuard CIDR — cheap fallback if oauth2-proxy is overkill; assumes users are already on the corp network.
3. **App-level auth in pi-web** — upstream doesn't ship this; punt.

**Default v1: oauth2-proxy with Google Workspace as IdP** (matches how the WoowTech team already accesses `woowtech-ha.woowtech.io`).

## 6. Health probes

```yaml
livenessProbe:
  httpGet: { path: /api/home, port: 30141 }
  initialDelaySeconds: 60           # cold start on ARM64 with venv install can hit 45s
  periodSeconds: 30
  timeoutSeconds: 5
  failureThreshold: 3               # ~90s of failure → restart
readinessProbe:
  httpGet: { path: /api/home, port: 30141 }
  initialDelaySeconds: 20
  periodSeconds: 10
  failureThreshold: 2
```

Same `/api/home` endpoint as the HA watchdog. kubelet handles restart on failure — replaces the Supervisor watchdog entirely.

## 7. Secrets

Per namespace:

```yaml
apiVersion: v1
kind: Secret
metadata: { name: pi-agent-provider-keys, namespace: pi-agent-<team> }
type: Opaque
stringData:
  GLM_API_KEY:        ""
  ANTHROPIC_API_KEY:  ""
  OPENAI_API_KEY:     ""
  OPENROUTER_API_KEY: ""
  DEEPSEEK_API_KEY:   ""
  GROQ_API_KEY:       ""
  MINIMAX_API_KEY:    ""
```

Mounted:

```yaml
envFrom:
  - secretRef:
      name: pi-agent-provider-keys
```

Rotation: `kubectl edit secret` (or SealedSecret / ExternalSecret upstream) → delete the pod → new pod picks up the fresh env. No file edit needed (models.json still references `$GLM_API_KEY` etc., resolved from env at request time — same behavior as on the addon).

## 8. Backup

Recommended: **Velero + CSI VolumeSnapshotter** with these hook annotations on the pod:

```yaml
pre.hook.backup.velero.io/container: pi-web
pre.hook.backup.velero.io/command: >
  ["/bin/bash", "-c",
   "rm -rf /data/pi-agent/venv /data/pi-agent/playwright-cache
    && find /data/pi-agent/projects -type d \\( -name clips -o -name segments \\) -exec rm -rf {} +"]
post.hook.restore.velero.io/container: pi-web
post.hook.restore.velero.io/command: >
  ["/bin/bash", "-c", "rm -f /data/pi-agent/.video-tools-installed"]
```

Rationale: exclude the same rebuildable caches the addon excludes (`venv/`, `playwright-cache/`, `projects/*/clips/`, `projects/*/segments/`), and force the venv/chromium re-download on restore by clearing the sentinel — mirrors the addon's post-restore behavior. `rclone.conf` stays inside the snapshot because losing the Drive OAuth would silently break every push (same rationale as `backup_exclude` on the addon).

Fallback (no Velero): CronJob that `tar --exclude ... /data/pi-agent | rclone rcat` to S3.

## 9. Delivery — Helm chart layout

```
charts/pi-agent/
├── Chart.yaml
├── values.yaml                    # defaults + doc for every knob
├── values-example.yaml            # per-team override sample
└── templates/
    ├── _helpers.tpl
    ├── namespace.yaml             # optional; usually pre-created
    ├── serviceaccount.yaml
    ├── secret.yaml                # provider keys (or ExternalSecret ref)
    ├── configmap-models-seed.yaml # optional; models.json bootstrap alternative
    ├── pvc-data.yaml              # 20Gi / RWO / storageClassName from values
    ├── statefulset.yaml           # single replica, initContainer, probes
    ├── service.yaml               # ClusterIP :30141
    ├── ingress.yaml               # TLS + oauth2-proxy annotations
    ├── networkpolicy.yaml         # allow ingress-controller → pod; deny everything else
    └── tests/
        └── smoke.yaml             # `helm test` — curls /api/home
```

Key `values.yaml` knobs:

- `image.tag` (default: chart appVersion)
- `image.pullPolicy`
- `providerKeys.*` (or `externalSecret.enabled`, `externalSecret.remoteRef`)
- `persistence.size`, `persistence.storageClassName`
- `ingress.host`, `ingress.tls.enabled`, `ingress.oauth2Proxy.enabled`
- `videoPipeline.enabled` (if false, skip initContainer + omit `PATH`/`PLAYWRIGHT_BROWSERS_PATH`/`RCLONE_CONFIG` env)
- `resources.requests` / `.limits`

## 10. What we drop, what we simplify, what we add

| Category | Verdict | Reason |
|---|---|---|
| `nginx` sub_filter body-rewrite + `</head>` shim | **Drop** | No ingress prefix problem on k3s (subdomain root) |
| Whitelist-validated `X-Ingress-Path` | **Drop** | Same reason |
| Sidebar auto-enable via Supervisor API | **Drop** | No sidebar; Ingress URL is the entry point |
| `bashio::config` / `bashio::log.*` | **Drop** | Not HA — use plain bash + stdout logging |
| Per-provider self-check | **Keep** | Still valuable — logs surface bad keys in seconds via `kubectl logs` |
| Idempotent `jq` merge on `models.json` | **Keep** | Same logic, initContainer path instead of `pi-web/run` inline |
| `video-tools-init` sentinel + non-fatal fail | **Keep** as initContainer with `restartPolicy: Never` — same sentinel path |
| HA cold backup | **Replace** with Velero + CSI snapshotter (§8) |
| HA watchdog | **Replace** with kubelet liveness/readiness probes (§6) |
| — | **Add** oauth2-proxy Ingress annotation stack |
| — | **Add** NetworkPolicy (default-deny egress + explicit provider allowlist) |
| — | **Add** Prometheus ServiceMonitor if the cluster runs kube-prometheus-stack |

## 11. Next steps (checklist)

- [ ] Fork the current `pi-web/run` into `charts/pi-agent/templates/scripts/pi-web-init.sh` — strip `bashio` calls, replace with plain bash.
- [ ] Fork the current `video-tools-init` into an initContainer script.
- [ ] Draft `Chart.yaml` + `values.yaml` per §9.
- [ ] Pick an oauth2-proxy config template that matches the existing WoowTech Workspace SSO.
- [ ] Provision one Longhorn `StorageClass` on the woow-k3s cluster (if not already present) for the 20 Gi PVC.
- [ ] E2E: install into `pi-agent-hermes` namespace, verify skill install + first chat + video pipeline dry-run.
- [ ] Compare screenshots side-by-side (HA addon vs k3s deploy) and write a `docs/K3S_DEPLOYMENT.md` mirror of `DEPLOYMENT.md`.
- [ ] Publish chart to `oci://ghcr.io/woowtech/charts/pi-agent`.

## 12. Open questions

1. **Cross-team skill sharing.** v1 requires re-installing skills per namespace. Do we want a `pi-agent-shared` namespace with a RWX PVC that other namespaces mount read-only? Tradeoff: RWX SC (NFS / Longhorn NFS provisioner) is heavier than RWO.
2. **Session archival.** `sessions/*.jsonl` grows unbounded. On the addon, the user manages it manually. On k3s should we ship a CronJob that rotates > 90 days into S3?
3. **Autoscaling.** Truly not viable with pi-web's file-based state. Do we accept "one team = one pod" as permanent, or invest in a shared Postgres/Redis session store upstream?
4. **Cost accounting.** Provider keys are per-namespace, so token usage is easy to attribute. Do we surface per-team usage via a Prometheus exporter, or wait for pi-web upstream to add a `/metrics` endpoint?
5. **GPU-hosted local models.** If any team wants to run vLLM alongside pi-agent (e.g. Llama-70B on cluster GPU), the pi-web `models.json` schema already supports `baseUrl: http://vllm.<team>.svc.cluster.local:8000/v1` — no code change needed, just a NetworkPolicy allow. Worth a v1.1 example manifest.

---

Cross-references you'll want open while implementing:

- [`DEPLOYMENT.md`](DEPLOYMENT.md) — what "currently deployed" actually means, file-by-file
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — deeper on the ingress shim (mostly obsolete on k3s) and the provider-catalog rationale (fully carries over)
- [`../CHANGELOG.md`](../CHANGELOG.md) — every quirk we've hit end-to-end; if the k3s port surfaces a new one, the changelog format is the model
- [`../rootfs/etc/s6-overlay/s6-rc.d/pi-web/run`](../rootfs/etc/s6-overlay/s6-rc.d/pi-web/run) — the script to port into an initContainer + entrypoint pair
