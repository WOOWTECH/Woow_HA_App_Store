# Sourced by woow-addon-upgrade-check.yml (pipeline #89) for the prebuilt images it pulls.
# amd64_ref <image> <version>: the image users install, as Supervisor names it: <image> from a config with {arch} ->
# amd64, tagged with the config's version. The comparison target's image and, with scan_published_image, the new one (#154).
amd64_ref() {
  printf '%s:%s' "${1//\{arch\}/amd64}" "$2"
}
# unpublished_reason <ref>: why the new image <ref> (amd64_ref of the PR's config, scan_published_image) cannot be
# pulled. The vulnerability comparison (category 4, compare) and the upgrade test (runtime, #154) both give this reason.
unpublished_reason() {
  printf '%s' "cannot pull $1, the image users would install with this PR: tag ${1##*:} of ${1%:*} is not published yet (or the registry is unreachable); publish it first (its upstream's release for a third-party image, the repository's own image publication otherwise) or bump to a version whose image is published, then re-run"
}
