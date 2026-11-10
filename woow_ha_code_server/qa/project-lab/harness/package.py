from pathlib import Path
import hashlib
import json
import re
import tempfile
import zipfile
import argparse
import os

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
IDS = [f'p{i:02}' for i in range(1, 51)]
SOURCE_FILES = {'app.mjs', 'cases.json', 'test.mjs', 'README.txt'}
REQUIRED_FILES = SOURCE_FILES | {'runtime.mjs', 'main.mjs', 'package.json', 'Containerfile'}
BULK_README = '''WOOW 50 independent application downloads

This archive contains p01.zip through p50.zip. Each inner ZIP contains one
self-contained pNN/ directory, including source, fixtures, tests and HTTP runtime.
Node.js 22+ is required. No npm install or network access is needed to run apps.

After extracting this outer ZIP, extract an individual ZIP and run:
  unzip p01.zip
  cd p01
  npm test
  npm start
Open http://127.0.0.1:18750/ in a browser. Stop the server with Ctrl+C.
Use PORT=18751 npm start to choose a different port. BIND defaults to 127.0.0.1.

To extract and test all 50 in a POSIX shell with unzip and Node installed:
  for archive in p[0-9][0-9].zip; do unzip -n "$archive"; done
  for project in p[0-9][0-9]/; do (cd "$project" && npm test) || exit 1; done
Start projects individually; each defaults to the same port, so use different
PORT values when running several simultaneously. Windows users can extract
both ZIP layers with their archive tool and run npm test/npm start in each folder.

This bulk download is a collection of independent applications. The shared
portal and its integration harness are supplied separately. Read each project's
README.txt for input fields, examples, bounds and limitations.
'''


def package(root, output=None):
    ROOT = Path(root).resolve()
    isolated = output is not None
    output = Path(output).absolute() if isolated else ROOT
    projects = ROOT / 'projects'
    actual = sorted(p.name for p in projects.iterdir() if re.fullmatch(r'p\d{2}', p.name))
    if actual != IDS:
        raise ValueError(f'Expected exactly p01..p50; missing={sorted(set(IDS)-set(actual))}, extra={sorted(set(actual)-set(IDS))}')
    runtime_path = ROOT / 'runtime.mjs'
    if not runtime_path.is_file() or runtime_path.is_symlink():
        raise ValueError('runtime.mjs must be a regular source file')
    runtime = runtime_path.read_bytes()
    snapshots = {}
    # Complete preflight before changing any download or manifest. Read each source once.
    for pid in IDS:
        project = projects / pid
        if not project.is_dir() or project.is_symlink():
            raise ValueError(f'{pid}: expected a regular project directory')
        for name in SOURCE_FILES:
            p = project / name
            if not p.is_file() or p.is_symlink():
                raise ValueError(f'{pid}: missing/nonregular required source {name}')
        files = {name: (project / name).read_bytes() for name in sorted(SOURCE_FILES)}
        cases = json.loads(files['cases.json'])
        if not isinstance(cases, list) or len(cases) < 4 or not all(isinstance(c, dict) for c in cases):
            raise ValueError(f'{pid}: cases.json requires at least four fixture objects')
        positive = [c for c in cases if c.get('error') is not True and 'expected' in c]
        if len(positive) < 2 or not any(c.get('error') is True for c in cases):
            raise ValueError(f'{pid}: requires two expected successes and one rejection')
        version = re.search(r'version\s*:\s*[\'\"]([0-9.]+)[\'\"]', files['app.mjs'].decode())
        if not version:
            raise ValueError(f'{pid}: cannot find application version')
        # Generated integration files live only in archives; never mutate projects/.
        files['runtime.mjs'] = runtime
        files['main.mjs'] = b"import {start} from './runtime.mjs';\nimport {fileURLToPath} from 'node:url';\nawait start({root:fileURLToPath(new URL('./',import.meta.url)),single:true,port:Number(process.env.PORT||18750)});\n"
        files['package.json'] = (json.dumps({'name': 'woow-50-'+pid, 'private': True, 'version': version[1], 'type': 'module', 'scripts': {'start': 'node main.mjs', 'test': 'node test.mjs'}}, indent=2)+'\n').encode()
        files['Containerfile'] = b'FROM docker.io/library/node:22-alpine\nWORKDIR /app\nCOPY --chown=node:node . .\nUSER node\nENV PORT=8080 BIND=0.0.0.0\nEXPOSE 8080\nCMD ["node", "main.mjs"]\n'
        if b'Standalone run' not in files['README.txt']:
            files['README.txt'] += b'\nStandalone run (Node.js 22+): npm test; npm start\nPORT=18750 BIND=127.0.0.1 defaults. No npm install needed.\nSource downloads are supplied by the multi-project portal.\n'
        if not REQUIRED_FILES <= files.keys():
            raise ValueError(f'{pid}: incomplete standalone payload')
        snapshots[pid] = files

    # Explicit --output creates a new artifact tree; default updates only the
    # suite's generated downloads and manifest, never application sources.
    if isolated:
        output.mkdir(mode=0o700)
    downloads, evidence = output / 'downloads', output / 'evidence'
    if downloads.is_symlink() or evidence.is_symlink():
        raise ValueError('Generated output directories must not be symlinks')
    downloads.mkdir(exist_ok=True)
    evidence.mkdir(exist_ok=True)
    receipts = []
    with tempfile.TemporaryDirectory(prefix='.package-', dir=downloads) as staging:
        stage = Path(staging)
        for pid, files in snapshots.items():
            dest = stage / (pid+'.zip')
            with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as archive:
                for name, data in sorted(files.items()):
                    # Fixed metadata makes identical source snapshots produce identical ZIPs.
                    member = zipfile.ZipInfo(pid+'/'+name, date_time=(2026, 1, 1, 0, 0, 0))
                    member.compress_type = zipfile.ZIP_DEFLATED
                    member.external_attr = 0o100644 << 16
                    archive.writestr(member, data)
            with zipfile.ZipFile(dest) as archive:
                assert {pid+'/'+name for name in REQUIRED_FILES} <= set(archive.namelist())
                assert archive.testzip() is None
            receipts.append({'id': pid, 'bytes': dest.stat().st_size, 'sha256': hashlib.sha256(dest.read_bytes()).hexdigest(), 'files': {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}})
        with zipfile.ZipFile(stage/'all-projects.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
            for pid in IDS:
                member = zipfile.ZipInfo(pid+'.zip', date_time=(2026, 1, 1, 0, 0, 0))
                member.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(member, (stage/(pid+'.zip')).read_bytes())
            member = zipfile.ZipInfo('README.txt', date_time=(2026, 1, 1, 0, 0, 0))
            member.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(member, BULK_README)
        for name in [pid+'.zip' for pid in IDS]+['all-projects.zip']:
            (stage/name).replace(downloads/name)
        manifest = stage/'package-manifest.json'
        manifest.write_text(json.dumps(receipts, indent=2)+'\n')
        manifest.replace(evidence/'package-manifest.json')
    print(json.dumps({'output': str(output), 'packaged': len(receipts), 'totalBytes': sum(r['bytes'] for r in receipts), 'bulkSha256': hashlib.sha256((downloads/'all-projects.zip').read_bytes()).hexdigest(), 'projectSourcesModified': False}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Package fifty apps into suite downloads/ and evidence/; never modify project sources.')
    parser.add_argument('--root', default=os.environ.get('QA_ROOT', str(DEFAULT_ROOT)))
    parser.add_argument('--output', help='optional separate artifact tree; must not exist; parent must exist')
    args = parser.parse_args()
    package(args.root, args.output)
