import { build, root } from './build.mjs';
import { mkdir, readFile, writeFile, rm, readdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
await build();
const dist = path.join(root, 'dist');
await mkdir(dist, { recursive: true });
for (const file of await readdir(dist)) {
  if (/^woowtech\.(paseo|omnigent)-[\w.-]+\.vsix$/.test(file)) await rm(path.join(dist, file));
}
const manifest = [];
const epoch = process.env.SOURCE_DATE_EPOCH || '1794240000';
for (const connector of ['paseo', 'omnigent']) {
  const pkg = JSON.parse(await readFile(path.join(root, connector, 'package.json'), 'utf8'));
  const file = `${pkg.publisher}.${pkg.name}-${pkg.version}.vsix`;
  const dest = path.join(dist, file);
  await rm(dest, { force: true });
  const command = spawnSync(process.execPath, [path.join(root, 'node_modules/@vscode/vsce/vsce'), 'package', '--no-dependencies', '--allow-missing-repository', '--out', dest], {
    cwd: path.join(root, connector), stdio: 'inherit', env: { ...process.env, SOURCE_DATE_EPOCH: epoch }, shell: false,
  });
  if (command.status !== 0) throw new Error(`${connector} VSIX packaging failed`);
  // ZIP timestamps are normalized after vsce. Rebuilds from identical sources,
  // lockfile and SOURCE_DATE_EPOCH produce identical installable VSIX bytes.
  const normalize = spawnSync('python3', ['-c', `import sys,zipfile,datetime,os
p=sys.argv[1]; epoch=int(sys.argv[2]); t=datetime.datetime.fromtimestamp(epoch,datetime.timezone.utc)
fixed=(max(1980,t.year),t.month,t.day,t.hour,t.minute,t.second//2*2)
with zipfile.ZipFile(p) as src: entries=[(i,src.read(i.filename)) for i in src.infolist()]
with zipfile.ZipFile(p+'.tmp','w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as out:
 for info,data in sorted(entries,key=lambda v:v[0].filename):
  info.date_time=fixed; info.create_system=3; info.external_attr=(0o100644 << 16); info.extra=b''
  out.writestr(info,data,compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
os.replace(p+'.tmp',p)
`, dest, epoch], { stdio: 'inherit', shell: false });
  if (normalize.status !== 0) throw new Error(`${connector} ZIP normalization failed`);
  manifest.push({ id: `${pkg.publisher}.${pkg.name}`, version: pkg.version, file, sha256: createHash('sha256').update(await readFile(dest)).digest('hex') });
}
await writeFile(path.join(dist, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n');
await writeFile(path.join(dist, 'SHA256SUMS'), manifest.map(item => `${item.sha256}  ${item.file}`).join('\n') + '\n');
console.log(JSON.stringify(manifest, null, 2));
