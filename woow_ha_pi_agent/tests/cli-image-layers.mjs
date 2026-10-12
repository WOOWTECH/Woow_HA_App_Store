#!/usr/bin/env node

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";

const root = process.cwd();
const dockerfile = existsSync(`${root}/Dockerfile`) ? "Dockerfile" : "Containerfile";
const text = readFileSync(`${root}/${dockerfile}`, "utf8");
const expected = {
  claude: { package: "@anthropic-ai/claude-code", version: "2.1.296", binary: "claude" },
  codex: { package: "@openai/codex", version: "0.162.1", binary: "codex" },
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
}

assert.doesNotMatch(text, /COPY cli-runtime\/\s+\/opt\/pi-clis\//, "combined CLI builder copy is forbidden");
assert.doesNotMatch(text, /COPY --from=piweb-builder \/opt\/pi-clis\s+\/opt\/pi-clis$/, "combined CLI final copy is forbidden");
console.log("Claude Code and Codex have pinned, separate builder and runtime image layers.");
