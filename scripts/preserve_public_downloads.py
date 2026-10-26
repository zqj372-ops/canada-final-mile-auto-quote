"""Carry independently released, hash-pinned public downloads into the web build.

These are public installers, not user state. Fail closed if a release changed;
never copy credentials, arbitrary container files, or an unverified payload.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile


def validate_name(name: str):
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or not (
        name in {'skill.sh', 'skill.ps1'} or name.startswith('skills/')
    ):
        raise ValueError('invalid public download path')


def install_downloads(source: Path, destination: Path, manifest: dict[str, str]):
    checked = []
    for name, digest in manifest.items():
        validate_name(name)
        src = source / name
        if src.is_symlink() or not src.is_file() or hashlib.sha256(src.read_bytes()).hexdigest() != digest:
            raise ValueError(f'public download hash mismatch: {name}')
        checked.append((name, src, digest))
    # Validate the whole set before changing the build context.
    for name, src, digest in checked:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
        target.chmod(0o644)
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError(f'public download copy failed: {name}')
    return len(checked)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--container', required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    with tempfile.TemporaryDirectory(prefix='quote-public-downloads-') as folder:
        source = Path(folder)
        for name in manifest:
            validate_name(name)
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('wb') as output:
                subprocess.run(['sudo', '-n', 'docker', 'exec', args.container,
                                'cat', f'/usr/share/nginx/html/{name}'], stdout=output, check=True)
        count = install_downloads(source, args.destination, manifest)
        print(f'Preserved and verified {count} public downloads')


if __name__ == '__main__':
    main()
