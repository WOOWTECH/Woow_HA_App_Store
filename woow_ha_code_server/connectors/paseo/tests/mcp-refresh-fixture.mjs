import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {refreshRecipes} from '../src/mcp-refresh-patch.mjs';

const sha = bytes => createHash('sha256').update(bytes).digest('hex');

// Simulated npm installers can copy just these four real upstream files from
// WOOW_PASEO_TEST_RUNTIME. Already-patched generations are reversed in memory
// and verified against the same frozen upstream hashes; no inline SDK blobs.
export function copyMcpRefreshFixture(sourceRoot, destinationRoot) {
  const files = refreshRecipes.map(recipe => {
    let source = fs.readFileSync(path.join(sourceRoot, recipe.path), 'utf8');
    if (sha(source) !== recipe.before) {
      assert.equal(sha(source), recipe.after, `unrecognized MCP fixture: ${recipe.path}`);
      for (const [before, after] of [...recipe.replacements].reverse()) {
        assert.equal(source.split(after).length, 2, `ambiguous MCP fixture: ${recipe.path}`);
        source = source.replace(after, before);
      }
    }
    assert.equal(sha(source), recipe.before, `upstream MCP fixture mismatch: ${recipe.path}`);
    return {file:path.join(destinationRoot, recipe.path), source};
  });
  // Check all inputs before creating or overwriting any fixture destination.
  for (const {file, source} of files) {
    fs.mkdirSync(path.dirname(file), {recursive:true});
    fs.writeFileSync(file, source);
  }
}
