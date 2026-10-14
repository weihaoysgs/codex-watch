#!/usr/bin/python3
"""Build a clean, root-owned .deb and shareable zip from an explicit allowlist."""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'native'))
from version import VERSION


def main():
    dist = ROOT / 'dist'
    dist.mkdir(exist_ok=True)
    package_name = f'codex-watch_{VERSION}_all.deb'
    with tempfile.TemporaryDirectory(prefix='codex-watch-package-') as temp:
        stage = Path(temp)

        def write(relative, content, mode=0o644):
            p = stage / relative
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
            p.chmod(mode)

        # No recursive copying: user files, local screenshots, pycache and state cannot leak in.
        native_files = ['core.py', 'main.py', 'history.py', 'reminder.py', 'pet.py', 'pet_scenes.py', 'version.py', 'theme.qss', 'icon.svg']
        for name in native_files:
            write('usr/share/codex-watch/native/' + name, (ROOT / 'native' / name).read_text())
        pet_files = ['manifest.json', 'THIRD_PARTY_NOTICES.md'] + [
            f'{kind}-{action}.png' for kind in ('cat', 'dog') for action in ('idle', 'walk', 'run', 'jump')]
        for name in pet_files:
            dest = stage / 'usr/share/codex-watch/native/assets/pets' / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes((ROOT / 'native/assets/pets' / name).read_bytes())
            dest.chmod(0o644)
        write('usr/share/doc/codex-watch/THIRD_PARTY_NOTICES.md',
              (ROOT / 'native/assets/pets/THIRD_PARTY_NOTICES.md').read_text())
        write('usr/bin/codex-watch', '#!/bin/sh\nexec /usr/bin/python3 /usr/share/codex-watch/native/main.py "$@"\n', 0o755)
        write('usr/share/applications/io.local.CodexWatch.desktop', (ROOT / 'packaging/io.local.CodexWatch.desktop').read_text())
        write('usr/share/icons/hicolor/scalable/apps/io.local.CodexWatch.svg', (ROOT / 'native/icon.svg').read_text())
        write('usr/share/doc/codex-watch/INSTALL.zh-CN.md', (ROOT / 'packaging/INSTALL.zh-CN.md').read_text())
        size = sum(p.stat().st_size for p in stage.rglob('*') if p.is_file())
        write('DEBIAN/control', f'''Package: codex-watch
Version: {VERSION}
Section: utils
Priority: optional
Architecture: all
Maintainer: Codex Watch Maintainers <maintainers@codex-watch.invalid>
Depends: python3 (>= 3.8), python3-pyqt5 (>= 5.14), libqt5svg5
Installed-Size: {(size + 1023) // 1024}
Description: Local Codex work monitor and persistent completion reminders
 A read-only desktop companion for active Codex sessions, with a tray icon,
 persistent on-top reminder cards, acknowledgement and light/dark themes.
 Reads local session records only; does not require an API key.
''')
        md5s = []
        for path in sorted((stage / 'usr').rglob('*')):
            if path.is_file():
                md5s.append(hashlib.md5(path.read_bytes()).hexdigest() + '  ' + str(path.relative_to(stage)))
        write('DEBIAN/md5sums', '\n'.join(md5s) + '\n')
        # No maintainer scripts, services or auto-start changes are executed on installation.
        for path in stage.rglob('*'):
            if path.is_dir():
                path.chmod(0o755)
        stage.chmod(0o755)
        env = dict(os.environ)
        env.setdefault('SOURCE_DATE_EPOCH', '1791936000')
        subprocess.run(['dpkg-deb', '--root-owner-group', '-Zxz', '--build', str(stage), str(dist / package_name)], check=True, env=env)
    guide = dist / 'INSTALL.zh-CN.md'
    shutil.copyfile(ROOT / 'packaging/INSTALL.zh-CN.md', guide)
    manifest = dist / 'SHA256SUMS'
    manifest.write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n'
                                for p in [dist / package_name, guide]))
    bundle = dist / f'codex-watch-{VERSION}-ubuntu.zip'
    with zipfile.ZipFile(bundle, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in [dist / package_name, guide, manifest]:
            archive.write(path, path.name)
    print('Installer:', dist / package_name)
    print('Share:', bundle)


if __name__ == '__main__':
    main()
