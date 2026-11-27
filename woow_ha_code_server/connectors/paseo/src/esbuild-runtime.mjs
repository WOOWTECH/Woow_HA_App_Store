import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {assertSafePath} from './state.mjs';

// Official npm 0.28.2 archives, verified against the managed lock's SHA-512.
// The wrapper and both installed binary paths must match the same release.
const PACKAGE_INTEGRITY='sha512-HKVLS8dvII+xoKW9kmqxbRKrnWEXfJJr/FZhhJmiqIB0e053QNYFqOBouTMO/k5sID4MvCiUCvv8b9M4h32wIA==';
const WRAPPER_FILES={
  'node_modules/esbuild/package.json':'9d0bc453f4e791553c4cc2298ba023b409241fd9801e494741666eb0f6051490',
  'node_modules/esbuild/lib/main.js':'61ec0ba144ff93f4bf0e96ad6fab6f430ede0aa13e27ace8063ed63ba416b3cd',
};
const BINARIES={
  'linux-x64':{integrity:'sha512-4xTZr1FUmSoQW4XIWmit3tzQrUTZM+N3P0XV8xROKYF50XfI7xeO90+1bZvNwxIufQ9hDQVRJH5YhgPVF8A/HQ==',sha256:'e1698a3d5c6c0798fee4fd3b5cc816651f460c63d390a7a26ea4beb0b1884100'},
  'linux-arm64':{integrity:'sha512-pW4AC0P3it8c7do9MVM4p51FzHzdM/TZrerurgRcHJ2WTa1VQ1CIq18xncfpBJw4ojkiZZrKW2yIBWBP92j6Ug==',sha256:'90bd269553d258e80b19e3ccab4f98f0831f87442a2f056510ce24fd1b425fc2'},
};
export function esbuildFiles(platform=process.platform,arch=process.arch) {
  const key=`${platform}-${arch}`,binary=BINARIES[key];
  if(!binary)return null;
  return {...WRAPPER_FILES,
    'node_modules/esbuild/bin/esbuild':binary.sha256,
    [`node_modules/@esbuild/${key}/bin/esbuild`]:binary.sha256};
}
export function esbuildRuntimeReady(root,lockedPackages) {
  try {
    const key=`${process.platform}-${process.arch}`,binary=BINARIES[key],files=esbuildFiles();
    if(!files)return false;
    for(const [name,integrity] of [['esbuild',PACKAGE_INTEGRITY],[`@esbuild/${key}`,binary.integrity]]) {
      const locked=lockedPackages['node_modules/'+name];
      if(locked?.version!=='0.28.2'||locked.integrity!==integrity)return false;
    }
    for(const [relative,expected] of Object.entries(files)) {
      const file=path.join(root,relative),stat=assertSafePath(file);
      // npm legitimately hardlinks the two binary paths. Check regular bytes,
      // executable mode and digest, without imposing a link-count restriction.
      if(!stat?.isFile()||stat.size===0)return false;
      if(relative.endsWith('/bin/esbuild')&&(stat.mode&0o111)===0)return false;
      if(createHash('sha256').update(fs.readFileSync(file)).digest('hex')!==expected)return false;
    }
    return true;
  }catch{return false;}
}
