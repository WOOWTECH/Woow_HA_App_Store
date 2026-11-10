'use strict';
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

// Sources are inputs. Generated reports stay in ignored evidence/ by default.
const root = path.resolve(process.env.QA_ROOT || path.join(__dirname, '..'));
function makeRun(label) {
  if (!/^[a-z-]+$/.test(label)) throw Error('Invalid run label');
  const parent = path.resolve(process.env.QA_OUTPUT || path.join(root,'evidence'));
  if(!process.env.QA_OUTPUT)fs.mkdirSync(parent,{recursive:true});
  if(fs.lstatSync(parent).isSymbolicLink())throw Error('Report directory must not be a symlink');
  if (!fs.statSync(parent).isDirectory()) throw Error('QA_OUTPUT must be an existing directory');
  return fs.mkdtempSync(path.join(parent, 'project-lab-' + label + '-'));
}
function packageRoot() {
  return path.resolve(process.env.QA_PACKAGES || root);
}
module.exports = {root, runtime:path.resolve(process.env.QA_RUNTIME || path.join(root,'runtime.mjs')), makeRun, packageRoot};
