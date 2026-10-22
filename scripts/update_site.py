"""Build and validate a complete update before replacing the published snapshot."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

SOURCE = Path(__file__).resolve().parents[1]


def update(pinned=False, force=False):
    parent = SOURCE / '.sync-staging'
    parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='complete-update-', dir=parent) as directory:
        stage = Path(directory).resolve()
        if not stage.is_relative_to(parent.resolve()):
            raise ValueError('Unsafe update staging directory')
        for name in ['assets', 'data']:
            shutil.copytree(SOURCE / name, stage / name)
        for name in ['app.js', 'card-renderer.js', 'styles.css', 'collections.css', 'index.html']:
            shutil.copyfile(SOURCE / name, stage / name)
        (stage / '.sync-staging').mkdir()
        for path in parent.glob('*-tree.json'):
            shutil.copyfile(path, stage / '.sync-staging' / path.name)
        env = {**os.environ, 'STS2_MOD_BUILD_ROOT': str(stage), 'STS2_SOURCE_CACHE': str(parent / 'cache')}
        sync_args = (['--pinned'] if pinned else []) + (['--force'] if force else [])
        for script, args in [('sync_mods.py', sync_args), ('import_game_ui.py', []), ('optimize_assets.py', []), ('validate_catalog.py', [])]:
            subprocess.run([sys.executable, '-X', 'utf8', str(SOURCE / 'scripts' / script), *args], cwd=stage, env=env, check=True)
        # All source parsing, UI compilation and hash checks have succeeded.
        for name in ['data', 'assets']:
            shutil.copytree(stage / name, SOURCE / name, dirs_exist_ok=True)
        for path in (stage / '.sync-staging').glob('*-tree.json'):
            shutil.copyfile(path, parent / path.name)
        print('Complete site snapshot updated; previous snapshot is preserved on build failure.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pinned', action='store_true')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    update(args.pinned, args.force)
