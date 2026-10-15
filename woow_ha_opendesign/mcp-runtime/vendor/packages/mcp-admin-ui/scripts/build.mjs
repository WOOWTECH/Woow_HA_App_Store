import { build } from 'esbuild';
import { cp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('..', import.meta.url));
await rm(`${root}/dist`, { recursive: true, force: true });
await mkdir(`${root}/dist/licenses`, { recursive: true });
await build({
  absWorkingDir: root, entryPoints: ['src/app.js'], bundle: true, minify: true,
  outdir: 'dist/assets', assetNames: 'fonts/[name]-[hash]', entryNames: 'app',
  loader: { '.woff2': 'file', '.woff': 'file', '.ttf': 'file', '.eot': 'file' },
  format: 'esm', target: ['es2022'], legalComments: 'eof', sourcemap: false,
});
// esbuild content-hashes fonts already. MDI's legacy cache-busting query/IE
// fragment is unnecessary and incompatible with the strict query-free server.
const cssPath = `${root}/dist/assets/app.css`;
const css = await readFile(cssPath, 'utf8');
await writeFile(cssPath, css.replace(/(url\("[^"?]*materialdesignicons[^"?]*)\?[^"\n]*("\))/g, '$1$2'));
await cp(`${root}/src/index.html`, `${root}/dist/index.html`);
for (const name of ['poppins', 'outfit', 'noto-sans-tc']) {
  await cp(`${root}/node_modules/@fontsource/${name}/LICENSE`, `${root}/dist/licenses/${name}-OFL.txt`);
}
await cp(`${root}/node_modules/@fontsource/yellowtail/LICENSE`, `${root}/dist/licenses/yellowtail-Apache-2.0.txt`);
await cp(`${root}/node_modules/@mdi/font/LICENSE`, `${root}/dist/licenses/mdi-LICENSE.txt`);
await writeFile(`${root}/dist/licenses/NOTICE.txt`, await readFile(`${root}/NOTICE.txt`, 'utf8'));
console.log('Built local UI assets and font/icon licenses. index.html requires trusted server mount injection.');
