#!/usr/bin/env python3
"""Stage a committed candidate or verified public release for source-build CI.

Default mode uses committed HEAD; --store-commit/--version verifies a published
catalog and downloads its immutable source. Use the pinned .addon-sync checkout
from the workflow. This never publishes, installs, or changes the source tree.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tooling', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--arch', choices=['amd64', 'aarch64'], required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--github-output', type=Path)
    parser.add_argument('--store-commit', help='Immutable public Store commit; requires --version')
    parser.add_argument('--version', help='Exact stable published version for Store validation')
    args = parser.parse_args()
    sys.path.insert(0, str(args.tooling.resolve()))
    import addon_sync as sync
    import download_addon as downloader

    provenance = {}
    if args.store_commit or args.version:
        if not re.fullmatch(r'[0-9a-f]{40}', args.store_commit or '') or not re.fullmatch(r'\d+\.\d+\.\d+', args.version or ''):
            raise ValueError('Published validation requires a full Store SHA and exact stable x.y.z version')
        url = f'https://raw.githubusercontent.com/WOOWTECH/Woow_HA_App_Store/{args.store_commit}/.addon-sync/catalog.json'
        catalog_raw = downloader.fetch(url)
        catalog = json.loads(catalog_raw)
        if catalog.get('schema') != 1 or sync.digest(sync.canonical(catalog['components'])) != catalog.get('catalog_id'):
            raise ValueError('Invalid public Store catalog integrity')
        entry = catalog['components']['woow_ha_pi_agent']
        if entry['id'] != 'woow_ha_pi_agent' or entry['repository'] != 'WOOWTECH/Woow_ha_pi_agent_add_on' or entry['version'] != args.version:
            raise ValueError('Public Store catalog does not contain the requested Pi Agent version')
        sha = entry['source_sha']
        if not re.fullmatch(r'[0-9a-f]{40}', sha):
            raise ValueError('Catalog source must be an immutable commit')
        api = 'https://api.github.com/repos/WOOWTECH/Woow_ha_pi_agent_add_on/'
        release = json.loads(downloader.fetch(api + 'releases/tags/v' + args.version))
        tagged = json.loads(downloader.fetch(api + 'commits/v' + args.version))
        if release.get('draft') or release.get('prerelease') or release.get('tag_name') != 'v' + args.version or tagged['sha'] != sha:
            raise ValueError('Catalog source does not match the stable published release')
        archive = downloader.fetch(f'https://codeload.github.com/WOOWTECH/Woow_ha_pi_agent_add_on/tar.gz/{sha}')
        if sync.digest(archive) != entry['archive_sha256']:
            raise ValueError('Published source archive checksum mismatch')
        provenance = {'store_commit': args.store_commit, 'catalog_id': catalog['catalog_id'],
                      'catalog_sha256': sync.digest(catalog_raw), 'release_url': release['html_url']}
    else:
        # Archive HEAD, not runner-local tooling or untracked files. On a PR
        # this is GitHub's tested merge commit, not a published catalog entry.
        root = Path(__file__).resolve().parents[1]
        sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
        archive = subprocess.check_output(
            ['git', 'archive', '--format=tar.gz', '--prefix=candidate/', 'HEAD'], cwd=root)
    files = sync.context_files(archive, '.')
    config = sync.config_from_files(files, 'config.yaml')
    if not sync.source_build_supported(files):
        raise ValueError('Candidate is missing local Dockerfile COPY/ADD inputs')
    if not provenance:
        entry = {
            'id': config['slug'], 'repository': 'WOOWTECH/Woow_ha_pi_agent_add_on',
            'source_sha': sha, 'source_path': '.', 'version': str(config['version']),
            'architectures': config['arch'], 'config_file': 'config.yaml',
            'config': config, 'config_sha256': sync.digest(files['config.yaml'][0]),
            'archive_sha256': sync.digest(archive), 'source_build_supported': True,
        }
    elif entry['source_path'] != '.' or entry['config_file'] != 'config.yaml' or entry['config'] != config:
        raise ValueError('Published catalog manifest differs from released source')
    context = downloader.stage(entry, args.destination.resolve(), args.arch,
                               source_build=True, raw=archive)
    local_config = json.loads((context / 'config.yaml').read_text())
    expected_config = dict(config, boot='manual')
    expected_config.pop('image', None)
    if local_config != expected_config:
        raise ValueError('Unexpected local source-build manifest changes')
    lock = json.loads((context / '.woow-source-lock.json').read_text())
    if lock['source'] != entry or lock['local_config_sha256'] != sync.digest((context / 'config.yaml').read_bytes()):
        raise ValueError('Local context lock does not match candidate')
    expected_policy = {'boot': 'manual', 'source_build': True,
                       'architecture': args.arch, 'digest_wrapper': False}
    if lock['local_policy'] != expected_policy:
        raise ValueError('Expected actual source compilation, not an image wrapper')
    expected_paths = {name for name in files if Path(name).parts[0] not in downloader.IGNORE}
    actual_paths = {str(path.relative_to(context)) for path in context.rglob('*') if path.is_file()}
    if actual_paths != expected_paths | {'.woow-source-lock.json'}:
        raise ValueError('Generated context lost source files or included unexpected files')
    verified = {}
    for name in sorted(expected_paths - {'config.yaml'}):
        data, mode = files[name]
        path = context / name
        if path.read_bytes() != data or path.stat().st_mode & 0o777 != mode:
            raise ValueError(f'Generated context changed source bytes or permissions: {name}')
        verified[name] = sync.digest(data)
    if (context / 'Dockerfile.source').exists():
        raise ValueError('Source Dockerfile was replaced by an image wrapper')
    generated_files = {name: ((context / name).read_bytes(), (context / name).stat().st_mode & 0o777)
                       for name in actual_paths}
    if not sync.source_build_supported(generated_files):
        raise ValueError('Generated context is missing Docker build inputs')
    # The downloader also promises not to overwrite a user's existing context.
    try:
        downloader.stage(entry, args.destination.resolve(), args.arch, source_build=True, raw=archive)
    except FileExistsError:
        pass
    else:
        raise ValueError('Downloader replaced an existing context')
    receipt = {
        'scope': 'Published public Store source-build staging' if provenance else 'Unpublished committed candidate; real Store source-build staging',
        **provenance,
        'downloader_sha256': sync.digest(Path(downloader.__file__).read_bytes()),
        'source_sha': sha, 'version': entry['version'], 'architecture': args.arch,
        'context': str(context), 'passed': True, 'compared_files': len(verified),
        'checks': ['exact_source_bytes_and_modes', 'all_build_inputs_present',
                   'manual_boot_no_image_override', 'matching_source_lock',
                   'original_source_dockerfile', 'existing_context_preserved'],
        'file_sha256': verified,
        'image_build': 'separate workflow build step; this script does not build an image',
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2) + '\n')
    if args.github_output:
        build = sync.yaml.safe_load(files['build.yaml'][0])
        outputs = {'context': str(context), 'version': entry['version'],
                   'source_sha': sha, 'base_image': build['build_from'][args.arch],
                   'name': config['name'], 'description': config['description']}
        if any(not isinstance(value, str) or '\n' in value or '\r' in value for value in outputs.values()):
            raise ValueError('Workflow metadata must be single-line strings')
        with args.github_output.open('a') as output:
            for key, value in outputs.items():
                output.write(f'{key}={value}\n')
    print(f'PASS {args.arch}: {len(verified)} source files match; local source-build context: {context}')


if __name__ == '__main__':
    main()
