#!/bin/bash
# Verify a Nextcloud server release archive before it is unpacked into the image.
# Usage: verify-nextcloud.sh <archive> <signature.asc> <armored-key> <expected-sha256> <expected-primary-fpr>
set -euo pipefail
archive=$1 signature=$2 key=$3 expected_sha=$4 expected_fpr=$5
printf '%s  %s\n' "$expected_sha" "$archive" | sha256sum -c -
home=$(mktemp -d); trap 'rm -rf "$home"' EXIT
gpg --homedir "$home" --batch --quiet --import "$key"
primary=$(gpg --homedir "$home" --batch --with-colons --fingerprint | awk -F: '/^fpr/{print $10; exit}')
[[ "$primary" == "$expected_fpr" ]] || { echo "Nextcloud release key fingerprint mismatch: $primary" >&2; exit 1; }
status=$(gpg --homedir "$home" --batch --status-fd 1 --verify "$signature" "$archive" 2>/dev/null) || { echo "Nextcloud release signature invalid" >&2; exit 1; }
grep -Eq "^\[GNUPG:\] VALIDSIG .* ${expected_fpr}\$" <<<"$status" || { echo "Nextcloud release not signed by pinned key" >&2; exit 1; }
echo "Nextcloud release verified: sha256 + signature by ${expected_fpr}"
