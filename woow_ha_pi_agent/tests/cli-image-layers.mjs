#!/usr/bin/env node

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";

const root = process.cwd();
const dockerfile = existsSync(`${root}/Dockerfile`) ? "Dockerfile" : "Containerfile";
const text = readFileSync(`${root}/${dockerfile}`, "utf8");
const pins = JSON.parse(readFileSync(`${root}/cli-runtime/versions.json`, "utf8"));
const expected = {
  claude: { package: "@anthropic-ai/claude-code", version: pins.claude.version, binary: "claude" },
  codex: { package: "@openai/codex", version: pins.codex.version, binary: "codex" },
};

for (const [name, spec] of Object.entries(expected)) {
  const packageJson = JSON.parse(readFileSync(`${root}/cli-runtime/${name}/package.json`, "utf8"));
  const lock = JSON.parse(readFileSync(`${root}/cli-runtime/${name}/package-lock.json`, "utf8"));
  assert.equal(packageJson.dependencies?.[spec.package], spec.version, `${name} package.json pin`);
  assert.equal(lock.packages?.[""]?.dependencies?.[spec.package], spec.version, `${name} lock pin`);
  assert.match(text, new RegExp(`COPY cli-runtime/${name}/ /opt/pi-clis/${name}/`), `${name} builder copy is separate`);
  assert.match(text, new RegExp(`npm ci --omit=dev --prefix=/opt/pi-clis/${name}`), `${name} builder install is separate`);
  assert.match(text, new RegExp(`COPY --from=piweb-builder /opt/pi-clis/${name} /opt/pi-clis/${name}`), `${name} final image copy is separate`);
  assert.match(text, new RegExp(`/opt/pi-clis/${name}/node_modules/.bin/${spec.binary}`), `${name} pinned binary is version-checked`);
  assert.match(text, new RegExp(`COPY --from=pins /pins/${name}/ /tmp/pins/${name}/`), `${name} builder reads its version pin`);
}

assert.doesNotMatch(text, /COPY cli-runtime\/\s+\/opt\/pi-clis\//, "combined CLI builder copy is forbidden");
assert.doesNotMatch(text, /COPY --from=piweb-builder \/opt\/pi-clis\s+\/opt\/pi-clis$/, "combined CLI final copy is forbidden");

// npm also installs the musl Claude executable on Debian (the lock has no libc
// field). The builder keeps the glibc binary that bin/claude.exe links to and
// removes musl; the final stage rejects any musl copy or second large binary.
assert.match(text, /cmp -s "\$\{CLAUDE_NATIVE\}\/bin\/claude\.exe" "\$\{CLAUDE_NATIVE\}-linux-\$\(node -p process\.arch\)\/claude"/, "the glibc binary is the one in use");
assert.match(text, /rm -rf "\$\{CLAUDE_NATIVE\}"-linux-\*-musl/, "the musl Claude package is removed");
assert.match(text, /! compgen -G '\/opt\/pi-clis\/claude\/node_modules\/@anthropic-ai\/\*musl\*'/, "the shipped Claude tree has no musl copy");
assert.match(text, /test \$\(\(CLAUDE_TREE_BYTES - CLAUDE_BINARY_BYTES\)\) -le \$\(\(16 \* 1024 \* 1024\)\)/, "the shipped Claude tree holds one native binary");
console.log("Claude Code and Codex have pinned, separate builder and runtime image layers; the Claude layer ships glibc only.");
