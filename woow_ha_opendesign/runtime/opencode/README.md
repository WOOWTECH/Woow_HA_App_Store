# Locked OpenCode runtime

This directory packages the official [OpenCode](https://github.com/anomalyco/opencode)
npm distribution, [`opencode-ai`](https://www.npmjs.com/package/opencode-ai), at version
`1.18.29`. It is MIT licensed. `package-lock.json` commits npm registry tarball integrity
hashes for the launcher and the Linux musl `x64` and `arm64` binaries used by the Alpine
image. The Docker build runs `npm ci` from this lockfile into
`/opt/ha-opendesign/opencode`; its `.bin` directory is on `PATH`.
