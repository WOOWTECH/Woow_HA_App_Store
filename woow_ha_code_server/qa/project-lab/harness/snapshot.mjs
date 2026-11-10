import fs from 'node:fs/promises';
import path from 'node:path';

export async function copyRegular(source,destination) {
  const st=await fs.lstat(source);
  if(!st.isFile()||st.isSymbolicLink()) throw Error('Snapshot requires regular input files');
  await fs.copyFile(source,destination,fs.constants.COPYFILE_EXCL);
}
export async function snapshot(root,destination,{packages,runtime=path.join(root,'runtime.mjs')}={}) {
  // The caller owns destination; mkdir refuses an existing tree, including links.
  await fs.mkdir(destination,{mode:0o700});
  await copyRegular(runtime,path.join(destination,'runtime.mjs'));
  await fs.mkdir(path.join(destination,'projects'));
  for(let n=1;n<=50;n++) {
    const id='p'+String(n).padStart(2,'0');
    const source=path.join(root,'projects',id);
    const st=await fs.lstat(source);
    if(!st.isDirectory()||st.isSymbolicLink())throw Error('Snapshot requires regular project directories');
    const target=path.join(destination,'projects',id);
    await fs.mkdir(target);
    for(const name of ['app.mjs','cases.json','test.mjs','README.txt'])await copyRegular(path.join(source,name),path.join(target,name));
  }
  if(packages) {
    await fs.mkdir(path.join(destination,'downloads'));
    for(const name of [...Array.from({length:50},(_,i)=>'p'+String(i+1).padStart(2,'0')+'.zip'),'all-projects.zip']) {
      await copyRegular(path.join(packages,'downloads',name),path.join(destination,'downloads',name));
    }
  }
  await fs.mkdir(path.join(destination,'evidence'));
}
