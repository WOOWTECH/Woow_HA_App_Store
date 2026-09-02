#!/usr/bin/env python3
"""Guard the apk bootstrap against Alpine database compatibility regressions."""

from pathlib import Path


DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"


def main() -> None:
    dockerfile = DOCKERFILE.read_text()
    bootstrap = dockerfile.split("RUN \\\n    set -eux; \\\n    cd /tmp;", 1)[1].split(
        "\nRUN \\\n    set -eux; \\\n    apk add --no-cache", 1
    )[0]

    assert "--initdb" not in bootstrap
    assert 'for STATIC_BRANCH in "${ALPINE_BRANCH}" v3.22; do' in bootstrap
    assert (
        'STATIC_BASE="http://dl-cdn.alpinelinux.org/alpine/${STATIC_BRANCH}/main/${ARCH}"'
        in bootstrap
    )
    assert "grep -o 'apk-tools-static-[0-9][^\"]*\\.apk'" in bootstrap
    assert 'wget -nv -O "${CANDIDATE_DIR}/apk-tools-static.apk"' in bootstrap
    assert 'tar -xzf "${CANDIDATE_DIR}/apk-tools-static.apk" -C "${CANDIDATE_DIR}"' in bootstrap
    compatibility_check = (
        'if "${CANDIDATE_DIR}/sbin/apk.static" --no-network info >/dev/null 2>&1; then'
    )
    assert compatibility_check in bootstrap
    assert 'APK_STATIC="${CANDIDATE_DIR}/sbin/apk.static"' in bootstrap
    assert 'APK_REPO="http://dl-cdn.alpinelinux.org/alpine/${STATIC_BRANCH}/main"' in bootstrap
    assert "No apk-tools-static candidate can read the base apk database" in bootstrap

    # The static binary must only be used after it has successfully read the
    # pre-existing database; installing against an initialized/empty database
    # would reconcile world by deleting the base image's packages.
    assert bootstrap.index(compatibility_check) < bootstrap.index("sed -i 's/><.*$//'")
    assert '"${APK_STATIC}" -X "${APK_REPO}" add apk-tools;' in bootstrap
    assert "apk del" not in bootstrap

    print("apk bootstrap test passed: compatible static fallback and base database preservation verified")


if __name__ == "__main__":
    main()
