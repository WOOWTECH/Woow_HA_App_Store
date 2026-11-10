import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {basename, dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {meta, run} from './app.mjs';

const cases = JSON.parse(readFileSync(new URL('./cases.json',import.meta.url),'utf8'));
const id = basename(dirname(fileURLToPath(import.meta.url)));
assert.equal(meta.id,id);
assert.equal(meta.version,'1.1.0');
for (const field of ['title','category','description']) assert.ok(typeof meta[field]==='string' && meta[field].length>0);
assert.ok(meta.example && typeof meta.example==='object' && !Array.isArray(meta.example));
assert.ok(cases.length>=4);
assert.ok(cases.filter(c=>Object.hasOwn(c,'expected')).length>=2);
assert.ok(cases.some(c=>c.error===true));
assert.equal(new Set(cases.map(c=>c.name)).size,cases.length);
function jsonSafe(value) {
  assert.notEqual(value,undefined);
  if (typeof value==='number') assert.ok(Number.isFinite(value),'output numbers must be finite');
  else if (value!==null && typeof value==='object') for (const child of Object.values(value)) jsonSafe(child);
  else assert.ok(value===null || ['string','boolean'].includes(typeof value),'output must contain JSON values');
}
let passed=0,failed=0;
for (const fixture of cases) {
  const input = structuredClone(fixture.input);
  const before = structuredClone(input);
  try {
    if (fixture.error) {
      assert.throws(()=>run(input),error=>{
        assert.ok(error instanceof Error && error.message.length>0);
        if (fixture.errorContains) assert.ok(error.message.includes(fixture.errorContains),`Expected error containing ${fixture.errorContains}; received ${error.message}`);
        return true;
      });
    } else {
      const output = run(input);
      jsonSafe(output);
      assert.deepStrictEqual(output,fixture.expected);
      assert.deepStrictEqual(JSON.parse(JSON.stringify(output)),fixture.expected);
      assert.deepStrictEqual(run(structuredClone(input)),fixture.expected,'repeat calls must be deterministic');
    }
    assert.deepStrictEqual(input,before,'run must not mutate input');
    passed++;
  } catch (error) { failed++; console.error(`FAIL ${id}: ${fixture.name}\n${error.stack}`); }
}
let smokeChecks=0;
for (const [name,check] of [
  ['meaningful sample runs',()=>{const input=structuredClone(meta.example);const before=structuredClone(input);jsonSafe(run(input));assert.deepStrictEqual(input,before);}],
  ['nonfinite input rejected',()=>assert.throws(()=>run({...meta.example,invalid:NaN}),/finite/)],
  ['cyclic input rejected',()=>{const input=structuredClone(meta.example);input.loop=input;assert.throws(()=>run(input),/cycles/);}],
  ['oversized input rejected',()=>assert.throws(()=>run({...meta.example,oversized:'x'.repeat(200001)}),/200000/)],
  ['excessive depth rejected',()=>{let nested=null;for(let i=0;i<34;i++)nested={nested};assert.throws(()=>run({...meta.example,nested}),/nesting levels/);}],
]) {
  try { check(); smokeChecks++; } catch(error) { failed++;console.error(`FAIL ${id}: ${name}\n${error.stack}`); }
}
console.log(JSON.stringify({id,fixtures:cases.length,passed,smokeChecks,failed}));
if (failed) process.exitCode=1;
