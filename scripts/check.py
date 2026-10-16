#!/usr/bin/env python3
"""Build both artifacts, install into clean environments, test the installed CLI."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import venv

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / '.private/evidence'
EVIDENCE.mkdir(parents=True, exist_ok=True)


def run(command, name, cwd=ROOT, env=None):
    with (EVIDENCE / (name + '.txt')).open('w') as output:
        p = subprocess.run(command, cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT)
    (EVIDENCE / (name + '.exit')).write_text(str(p.returncode) + '\n')
    if p.returncode:
        print((EVIDENCE / (name + '.txt')).read_text())
        raise SystemExit(p.returncode)
    print(name + ': exit 0', flush=True)


run([sys.executable, '-m', 'build', '--no-isolation'], 'final-build')
wheel = ROOT / 'dist/orion_pm-0.1.1-py3-none-any.whl'
sdist = ROOT / 'dist/orion_pm-0.1.1.tar.gz'
manifest = {'artifacts': {}, 'profiles': {}}
for artifact in (wheel, sdist):
    manifest['artifacts'][artifact.name] = hashlib.sha256(artifact.read_bytes()).hexdigest()
with tempfile.TemporaryDirectory(prefix='pm-core-conformance-') as tmp:
    tmp = Path(tmp)
    source_dir = tmp / 'source'
    source_dir.mkdir()
    with tarfile.open(sdist) as archive:
        # This is our inspected build artifact, not an arbitrary remote archive.
        for member in archive.getmembers():
            parts = Path(member.name).parts
            if Path(member.name).is_absolute() or '..' in parts or not (member.isfile() or member.isdir()):
                raise RuntimeError('Unsafe sdist member')
        archive.extractall(source_dir)
    extracted = source_dir / 'orion_pm-0.1.1'
    rebuilt = tmp / 'sdist-wheel'
    run([sys.executable, '-m', 'build', '--no-isolation', '--wheel', '--outdir', str(rebuilt)],
        'sdist-rebuild', cwd=extracted)
    source_wheel = next(rebuilt.glob('*.whl'))
    manifest['sdist_rebuilt_wheel_sha256'] = hashlib.sha256(source_wheel.read_bytes()).hexdigest()
    for label, artifact in (('wheel', wheel), ('sdist', source_wheel)):
        environment = tmp / label
        # Match Linux `python -m venv`: relocatable interpreter builds require
        # symlinks so their relative shared-library lookup stays valid.
        venv.EnvBuilder(with_pip=True, symlinks=True).create(environment)
        executable = environment / 'bin/orion-pm'
        run([str(environment / 'bin/pip'), 'install', '--no-index', '--no-deps', str(artifact)], label + '-install')
        env = {**os.environ, 'PM_TEST_BIN': str(executable), 'PYTHONPATH': '', 'PYTHONDONTWRITEBYTECODE': '1'}
        run([sys.executable, '-m', 'unittest', 'discover', '-s', str(ROOT / 'tests'), '-v'],
            label + '-suite', cwd=tmp, env=env)
        p = subprocess.run([str(executable), '--json', 'version'], capture_output=True, text=True, check=True, cwd=tmp, env=env)
        manifest['profiles'][label] = json.loads(p.stdout)['data']
(EVIDENCE / 'artifact-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print('Clean wheel and sdist-derived installations verified. Receipts: .private/evidence')
