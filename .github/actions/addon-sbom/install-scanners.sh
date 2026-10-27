#!/usr/bin/env bash
# Install pinned scanners (pipeline #89): install-scanners.sh <dest dir> <tool>...
# Versions and archive sha256s are in scanner-pins.json next to this script
# (same pins as Woow_ha_mcp_addons packaging/scanner-pins.json). A checksum
# mismatch or a download error fails; nothing unpinned is ever run.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
dest="$1"; shift
mkdir -p "${dest}"
for tool in "$@"; do
  url="$(jq -er --arg t "${tool}" '.[$t].url' "${here}/scanner-pins.json")"
  sha="$(jq -er --arg t "${tool}" '.[$t].sha256' "${here}/scanner-pins.json")"
  version="$(jq -er --arg t "${tool}" '.[$t].version' "${here}/scanner-pins.json")"
  archive="$(mktemp)"
  if ! curl -fsSL --retry 3 -o "${archive}" "${url}"; then
    echo "::error title=Scanner install failed::cannot download ${tool} ${version} from ${url}"; exit 1
  fi
  if ! echo "${sha}  ${archive}" | sha256sum -c --quiet -; then
    echo "::error title=Scanner install failed::${tool} ${version} archive does not match the pinned sha256"; exit 1
  fi
  tar -xzf "${archive}" -C "${dest}" "${tool}"
  rm -f "${archive}"
  "${dest}/${tool}" version | grep -q "${version}" || { echo "::error title=Scanner install failed::${tool} is not ${version}"; exit 1; }
  echo "${tool} ${version} installed (sha256 ${sha})"
done
