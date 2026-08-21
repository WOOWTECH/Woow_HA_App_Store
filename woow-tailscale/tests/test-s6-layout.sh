#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
service_dir="${repo_root}/woow-tailscale/rootfs/etc/s6-overlay/s6-rc.d/init-login-server-migration"
tailscaled_dependencies="${repo_root}/woow-tailscale/rootfs/etc/s6-overlay/s6-rc.d/tailscaled/dependencies.d"
run_script="${service_dir}/run"
up_script="${service_dir}/up"
expected_up_target='/etc/s6-overlay/s6-rc.d/init-login-server-migration/run'

[[ "$(<"${service_dir}/type")" == 'oneshot' ]]
test -f "${service_dir}/dependencies.d/base"
test -x "${run_script}"
test -x "${up_script}"
grep -Fqx "${expected_up_target}" "${up_script}"
test -f "${tailscaled_dependencies}/init-login-server-migration"
# The migration dependency is additive; retain the upstream prerequisites.
test -f "${tailscaled_dependencies}/base"
test -f "${tailscaled_dependencies}/init-magicdns-ingress-proxy"
test -f "${tailscaled_dependencies}/magicdns-egress-proxy"
grep -Fqx '#!/command/with-contenv bashio' "${run_script}"
grep -Fq "login_server=\"\$(bashio::config 'login_server')\"" "${run_script}"
grep -Fq '/usr/local/lib/woow-tailscale/reconcile-login-server' "${run_script}"
grep -Fq 'Checking configured Tailscale control server' "${run_script}"
grep -Fq 'bashio::exit.nok' "${run_script}"

printf 'PASS: s6 migration layout\n'
